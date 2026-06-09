"""端到端集成测试 — 验证诊断→分析→决策→修复核心逻辑"""
import pytest

from src.models.fix import Decision, FixType
from src.models.diagnosis import DiagnosisReport
from src.engine.decision import DecisionEngine
from src.safety.validator import AIResponseValidator


# ═══════════════════════════════════════════════════════
# Decision Engine
# ═══════════════════════════════════════════════════════

class TestDecisionEngine:
    """决策引擎测试"""

    @pytest.fixture
    def engine(self):
        return DecisionEngine()

    def test_high_confidence_auto_exec(self, engine):
        """confidence >= 0.8 → AUTO_EXEC"""
        assert engine.decide(0.95, "memory") == Decision.AUTO_EXEC
        assert engine.decide(0.80, "cpu") == Decision.AUTO_EXEC

    def test_medium_confidence_approval(self, engine):
        """0.5 <= confidence < 0.8 → NEED_APPROVAL"""
        assert engine.decide(0.70, "config") == Decision.NEED_APPROVAL
        assert engine.decide(0.50, "probe") == Decision.NEED_APPROVAL

    def test_low_confidence_notify(self, engine):
        """confidence < 0.5 → ONLY_NOTIFY"""
        assert engine.decide(0.40, "memory") == Decision.ONLY_NOTIFY
        assert engine.decide(0.00, "unknown") == Decision.ONLY_NOTIFY

    def test_pvc_always_needs_approval(self, engine):
        """PVC 操作即使高置信度也要审批"""
        assert engine.decide(0.95, "pvc") == Decision.NEED_APPROVAL

    def test_resource_quota_always_needs_approval(self, engine):
        """ResourceQuota 操作即使高置信度也要审批"""
        assert engine.decide(0.99, "resource_quota") == Decision.NEED_APPROVAL


# ═══════════════════════════════════════════════════════
# AI Response Validator
# ═══════════════════════════════════════════════════════

class TestAIResponseValidator:
    """AI 响应校验器测试"""

    @pytest.fixture
    def validator(self):
        return AIResponseValidator()

    @pytest.fixture
    def valid_response(self):
        return {
            "root_cause": "Pod test-pod 内存不足 OOMKilled，limit=256Mi 但启动需要 ~500Mi",
            "fix_type": "memory",
            "fix_action": "增加 memory limit 到 1Gi",
            "confidence": 0.95,
            "evidence": ["Exit Code 137", "Events 显示 OOMKilled"],
            "alternative_causes": ["内存泄漏"],
            "severity_assessment": "服务不可用",
            "fix_params": {"new_memory_limit": "1Gi"},
        }

    @pytest.fixture
    def diagnosis(self):
        return DiagnosisReport(pod_name="test-pod", namespace="default")

    def test_valid_response_passes(self, validator, valid_response, diagnosis):
        valid, msg = validator.validate(valid_response, diagnosis)
        assert valid, f"Expected valid but got: {msg}"

    def test_missing_field_fails(self, validator, diagnosis):
        response = {"fix_type": "memory", "confidence": 0.9}
        valid, msg = validator.validate(response, diagnosis)
        assert not valid
        assert "root_cause" in msg

    def test_invalid_fix_type_fails(self, validator, valid_response):
        valid_response["fix_type"] = "delete_pod"
        valid, msg = validator.validate(
            valid_response, DiagnosisReport(pod_name="test-pod"),
        )
        assert not valid

    def test_confidence_out_of_range_fails(self, validator, valid_response):
        valid_response["confidence"] = 1.5
        valid, msg = validator.validate(
            valid_response, DiagnosisReport(pod_name="test-pod"),
        )
        assert not valid

    def test_negative_confidence_fails(self, validator, valid_response):
        valid_response["confidence"] = -0.1
        valid, msg = validator.validate(
            valid_response, DiagnosisReport(pod_name="test-pod"),
        )
        assert not valid

    def test_forbidden_action_kubectl_delete(self, validator, valid_response):
        valid_response["fix_action"] = "kubectl delete pod test-pod --force"
        valid, msg = validator.validate(
            valid_response, DiagnosisReport(pod_name="test-pod"),
        )
        assert not valid
        assert "禁止" in msg

    def test_forbidden_action_force_delete(self, validator, valid_response):
        valid_response["fix_action"] = "建议 force delete 该 Pod"
        valid, msg = validator.validate(
            valid_response, DiagnosisReport(pod_name="test-pod"),
        )
        assert not valid


# ═══════════════════════════════════════════════════════
# Safety Guard
# ═══════════════════════════════════════════════════════

class TestSafetyGuard:
    """安全护栏测试"""

    @pytest.fixture
    def guard(self):
        from src.safety.guard import SafetyGuard
        return SafetyGuard()

    @pytest.fixture
    def alert(self):
        from src.models.alert import AlertPayload
        return AlertPayload(
            alert_name="KubePodOOMKilled",
            pod_name="test-pod",
            namespace="default",
            severity="critical",
        )

    def test_allowed_namespace_and_action(self, guard, alert):
        """合法 namespace + 合法 fix_type → 通过"""
        fix_plan = {"fix_type": "memory", "fix_params": {"new_memory_limit": "1Gi"}}
        ok, msg = guard.check(alert, fix_plan)
        assert ok, f"Expected pass but got: {msg}"

    def test_blocked_namespace(self, guard, alert):
        """kube-system namespace → 拦截"""
        alert.namespace = "kube-system"
        ok, msg = guard.check(alert, {"fix_type": "memory"})
        assert not ok
        assert "kube-system" in msg

    def test_unknown_fix_type(self, guard, alert):
        """不在白名单的 fix_type → 拦截"""
        ok, msg = guard.check(alert, {"fix_type": "delete_everything"})
        assert not ok

    def test_resource_parse_memory(self, guard):
        """K8s 内存值解析"""
        assert guard._parse_resource("256Mi") == 256 * 1024 * 1024
        assert guard._parse_resource("1Gi") == 1024 * 1024 * 1024
        assert guard._parse_resource("512Ki") == 512 * 1024

    def test_resource_parse_cpu(self, guard):
        """K8s CPU 值解析"""
        assert guard._parse_resource("500m") == 500
        assert guard._parse_resource("4") is not None


# ═══════════════════════════════════════════════════════
# Loop Guard
# ═══════════════════════════════════════════════════════

class TestLoopGuard:
    """修复循环保护测试"""

    @pytest.fixture
    def guard(self):
        from src.safety.loop_guard import HealingLoopGuard
        return HealingLoopGuard()

    def test_first_healing_allowed(self, guard):
        """首次修复 → 允许"""
        ok, msg = guard.should_allow("default/test-pod", {"fix_type": "memory"})
        assert ok, msg

    def test_second_different_type_allowed(self, guard):
        """不同类型修复 → 允许"""
        pod = "default/test-pod-2"
        guard.record(pod, {"fix_type": "memory"})
        ok, msg = guard.should_allow(pod, {"fix_type": "cpu"})
        assert ok, msg

    def test_same_type_blocked(self, guard):
        """同类型修复24h内 → 拦截"""
        pod = "default/test-pod-3"
        guard.record(pod, {"fix_type": "memory"})
        ok, msg = guard.should_allow(pod, {"fix_type": "memory"})
        assert not ok, f"Expected blocked but got: {msg}"


# ═══════════════════════════════════════════════════════
# Main App
# ═══════════════════════════════════════════════════════

class TestFastAPIApp:
    """FastAPI 应用测试 (需要 kubernetes 包)"""

    @pytest.mark.skip(reason="需要 kubernetes 包和 K8s 配置")
    def test_app_initializes(self):
        """FastAPI app 应能成功导入和初始化"""
        from src.main import app
        assert app.title == "K8s Healing Agent"
        assert app.version == "0.1.0"

    @pytest.mark.skip(reason="需要 kubernetes 包和 K8s 配置")
    def test_health_endpoint(self):
        """健康检查端点应返回 200"""
        from src.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
