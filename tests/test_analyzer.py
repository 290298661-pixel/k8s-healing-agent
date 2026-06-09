"""AI 分析引擎单元测试"""
import json
import pytest
from src.engine.analyzer import AIAnalyzer


class TestJSONExtraction:
    """测试从 Claude 回复中提取 JSON"""

    def test_extract_bare_json(self):
        """裸 JSON 对象"""
        text = '{"root_cause": "OOM", "fix_type": "memory", "confidence": 0.95}'
        result = AIAnalyzer._extract_json(text)
        assert result["root_cause"] == "OOM"
        assert result["confidence"] == 0.95

    def test_extract_json_in_code_block(self):
        """JSON 在 ```json 代码块中"""
        text = """```json
{"root_cause": "OOM", "fix_type": "memory", "confidence": 0.95}
```"""
        result = AIAnalyzer._extract_json(text)
        assert result["fix_type"] == "memory"

    def test_extract_json_with_surrounding_text(self):
        """JSON 周围有说明文字"""
        text = """分析结果如下：
{"root_cause": "OOMKilled", "fix_type": "memory", "confidence": 0.95}
以上是我的诊断。"""
        result = AIAnalyzer._extract_json(text)
        assert result["fix_type"] == "memory"
        assert result["confidence"] == 0.95

    def test_extract_nested_json(self):
        """嵌套 JSON 对象"""
        text = '{"root_cause": "OOM", "fix_type": "memory", "fix_params": {"new_memory_limit": "1Gi"}, "confidence": 0.9}'
        result = AIAnalyzer._extract_json(text)
        assert result["fix_params"]["new_memory_limit"] == "1Gi"

    def test_extract_invalid_json_raises(self):
        """无效 JSON 应抛出异常"""
        text = "这不是 JSON"
        with pytest.raises(json.JSONDecodeError):
            AIAnalyzer._extract_json(text)


class TestUserPrompt:
    """测试 User Prompt 构建"""

    def test_oom_diagnosis_prompt(self):
        """OOM 故障的 User Prompt 构建"""
        from src.models.diagnosis import DiagnosisReport, ContainerStatus

        report = DiagnosisReport(
            pod_name="test-pod",
            namespace="default",
            phase="Running",
            node_name="node-1",
            owner_kind="Deployment",
            owner_name="test-app",
            restart_count=5,
            container_statuses=[
                ContainerStatus(
                    name="app",
                    state="terminated",
                    reason="OOMKilled",
                    exit_code=137,
                    restart_count=5,
                ),
            ],
            resource_limits={"memory": "256Mi", "cpu": "500m"},
            resource_requests={"memory": "128Mi", "cpu": "250m"},
            image="myapp:v1.2.3",
        )

        # 不需要 API key，只测试 prompt 构建
        analyzer = AIAnalyzer(api_key="test-key")
        prompt = analyzer._build_user_prompt(report)

        assert "test-pod" in prompt
        assert "OOMKilled" in prompt
        assert "256Mi" in prompt
        assert "exit_code=137" in prompt or "137" in prompt
        assert "myapp:v1.2.3" in prompt
