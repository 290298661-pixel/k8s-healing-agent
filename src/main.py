"""
K8s Healing Agent — FastAPI 入口
接收 Prometheus AlertManager Webhook，编排自愈流程

Pipeline: 诊断 → AI 分析 → 验证 → 安全审查 → 决策 → 修复 → 验证 → 通知
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from pydantic import BaseModel

from src.config import Config
from src.models.alert import AlertPayload
from src.models.fix import HealingResult, Decision
from src.engine.diagnosis import DiagnosisEngine
from src.engine.analyzer import AIAnalyzer
from src.engine.decision import DecisionEngine
from src.engine.healer import HealingExecutor
from src.engine.verifier import VerificationEngine
from src.safety.guard import SafetyGuard
from src.safety.loop_guard import HealingLoopGuard
from src.safety.validator import AIResponseValidator
from src.notification.dingtalk import DingTalkNotifier
from src.audit.logger import AuditLogger
from src.utils.metrics import Metrics

# ── Logging ──────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("healing-agent")

# ── Config ───────────────────────────────────────────

config = Config.from_yaml()

# ── FastAPI App ──────────────────────────────────────

app = FastAPI(
    title="K8s Healing Agent",
    description="AI-driven Kubernetes self-healing agent",
    version="0.1.0",
)

# ── Components ───────────────────────────────────────

diagnosis_engine = DiagnosisEngine()
ai_analyzer = AIAnalyzer(
    api_key=config.claude_api_key,
)
decision_engine = DecisionEngine()
healing_executor = HealingExecutor()
verification_engine = VerificationEngine()
safety_guard = SafetyGuard()
loop_guard = HealingLoopGuard()
response_validator = AIResponseValidator()
notifier = DingTalkNotifier(config.dingtalk_webhook)
audit = AuditLogger(config.audit_db_path)
metrics = Metrics()

# ── Concurrency control ──────────────────────────────

_active_healings: dict[str, asyncio.Task] = {}
_recently_handled: dict[str, datetime] = {}
_dedup_lock = asyncio.Lock()

# ── Data models ──────────────────────────────────────

class AlertManagerWebhook(BaseModel):
    """AlertManager V4 Webhook 格式"""
    receiver: str = ""
    status: str = ""            # "firing" | "resolved"
    alerts: list[dict] = []
    groupLabels: dict = {}
    commonLabels: dict = {}
    externalURL: str = ""


def _parse_alert(raw: dict) -> AlertPayload:
    """从 AlertManager webhook alert 解析为 AlertPayload"""
    labels = raw.get("labels", {})
    annotations = raw.get("annotations", {})

    alert_name = labels.get("alertname", "Unknown")
    pod_name = labels.get("pod", labels.get("pod_name", "unknown"))
    namespace = labels.get("namespace", "default")
    severity = labels.get("severity", "warning")

    starts_at_str = raw.get("startsAt", "")
    starts_at = None
    if starts_at_str:
        try:
            starts_at = datetime.fromisoformat(
                starts_at_str.replace("Z", "+00:00"),
            )
        except (ValueError, TypeError):
            pass

    # 生成去重指纹
    fingerprint = raw.get("fingerprint", "")
    if not fingerprint:
        fingerprint = f"{alert_name}:{namespace}:{pod_name}"

    return AlertPayload(
        alert_name=alert_name,
        pod_name=pod_name,
        namespace=namespace,
        severity=severity,
        labels=labels,
        annotations=annotations,
        starts_at=starts_at,
        fingerprint=fingerprint,
    )


# ── API Routes ───────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/metrics")
async def get_metrics():
    """暴露 Prometheus 指标"""
    from fastapi.responses import Response
    return Response(
        content=metrics.get_latest(),
        media_type="text/plain; charset=utf-8",
    )


@app.post("/webhook/alertmanager")
async def handle_alert(webhook: AlertManagerWebhook):
    """
    AlertManager Webhook 入口。
    对于 firing 告警中的每个 Pod 故障，启动一个独立的修复管道。
    """
    if webhook.status != "firing":
        return {"status": "ok", "message": "resolved alert skipped"}

    metrics.record_alert_received()

    results = []
    for alert_raw in webhook.alerts:
        try:
            alert = _parse_alert(alert_raw)
        except Exception as e:
            logger.warning("告警解析失败: %s", e)
            continue

        # 去重检查
        async with _dedup_lock:
            fp = alert.fingerprint
            if fp in _recently_handled:
                elapsed = datetime.now() - _recently_handled[fp]
                if elapsed < timedelta(
                    seconds=config.alert_dedup_window_seconds,
                ):
                    metrics.record_alert_deduped()
                    logger.debug("告警去重: %s (%.0fs 前)", fp, elapsed.total_seconds())
                    continue

        # 并发控制
        pod_key = f"{alert.namespace}/{alert.pod_name}"
        if pod_key in _active_healings:
            existing = _active_healings[pod_key]
            if not existing.done():
                logger.warning("Pod %s 已有修复任务进行中", pod_key)
                continue

        # 异步启动修复管道
        task = asyncio.create_task(_healing_pipeline(alert))
        _active_healings[pod_key] = task
        results.append({
            "pod": pod_key,
            "alert": alert.alert_name,
            "status": "processing",
        })

    return {
        "received": len(webhook.alerts),
        "processed": len(results),
        "results": results,
    }


# ── Core Pipeline ────────────────────────────────────

async def _healing_pipeline(alert: AlertPayload) -> HealingResult:
    """
    修复管道：诊断 → AI 分析 → 验证 → 安全审查 → 决策 → 修复 → 验证 → 通知
    """
    pipeline_start = time.monotonic()
    audit_id = audit.start_healing(alert)

    try:
        # ── Step 1: 诊断 ─────────────────────────────
        logger.info("Step 1/5: 开始诊断 %s/%s", alert.namespace, alert.pod_name)
        diag_start = time.monotonic()
        diagnosis = await diagnosis_engine.collect(
            alert.pod_name, alert.namespace,
        )
        diagnosis_time = time.monotonic() - diag_start
        metrics.record_diagnosis(diagnosis_time)
        logger.info("诊断完成 (%.1fs)", diagnosis_time)

        # ── Step 2: AI 分析 ──────────────────────────
        logger.info("Step 2/5: AI 分析中...")
        analyze_start = time.monotonic()
        ai_response = await ai_analyzer.analyze(diagnosis)
        analyze_time = time.monotonic() - analyze_start
        metrics.record_analysis(analyze_time)
        logger.info(
            "AI 分析完成 (%.1fs): root_cause=%s, confidence=%.2f",
            analyze_time,
            ai_response.get("root_cause", "")[:80],
            ai_response.get("confidence", 0.0),
        )

        # ── Step 2.5: 验证 AI 响应 ───────────────────
        valid, error_msg = response_validator.validate(
            ai_response, diagnosis,
        )
        if not valid:
            logger.error("AI 响应验证失败: %s", error_msg)
            audit.log_validation_failure(audit_id, error_msg)
            await notifier.send_error(alert, f"AI 响应验证失败: {error_msg}")
            return HealingResult(success=False, error=error_msg)

        # ── Step 3: 安全审查 + 决策 ──────────────────
        logger.info("Step 3/5: 安全审查 + 决策")
        safe, safety_msg = safety_guard.check(alert, ai_response)
        if not safe:
            logger.warning("安全检查拦截: %s", safety_msg)
            audit.log_safety_block(audit_id, safety_msg)
            await notifier.send_safety_block(alert, safety_msg)
            return HealingResult(
                success=False, error=f"安全拦截: {safety_msg}",
            )

        decision = decision_engine.decide(
            ai_response["confidence"], ai_response["fix_type"],
        )
        metrics.record_decision(decision.value)
        audit.log_decision(
            audit_id, ai_response, decision.value,
            diagnosis_time, analyze_time,
        )
        logger.info("决策: %s (confidence=%.2f)", decision.value,
                     ai_response["confidence"])

        # ── Step 4: 执行 ─────────────────────────────
        pod_key = f"{alert.namespace}/{alert.pod_name}"

        if decision == Decision.AUTO_EXEC:
            # 循环保护检查
            allow, reason = loop_guard.should_allow(pod_key, ai_response)
            if not allow:
                logger.warning("循环保护拦截: %s", reason)
                audit.log_loop_guard_block(audit_id, reason)
                await notifier.send_loop_guard_block(alert, reason)
                return HealingResult(success=False, error=reason)

            logger.info("Step 4/5: 执行修复 %s", ai_response.get("fix_type"))
            heal_start = time.monotonic()
            heal_result = await healing_executor.execute(
                alert.pod_name, alert.namespace, ai_response,
            )
            heal_time = time.monotonic() - heal_start
            metrics.record_healing(heal_time, heal_result.success)

            if not heal_result.success:
                logger.error("修复失败: %s", heal_result.error)
                audit.log_healing_failure(audit_id, heal_result)
                await notifier.send_healing_failure(alert, heal_result)
                return heal_result

            # 记录修复（循环保护追踪）
            loop_guard.record(pod_key, ai_response)

            # ── Step 5: 验证 ─────────────────────────
            logger.info("Step 5/5: 验证修复结果")
            verify_result = await verification_engine.verify(
                alert.pod_name, alert.namespace,
                timeout=config.verification_timeout,
            )
            metrics.record_verification(verify_result.success)
            audit.log_healing_complete(audit_id, heal_result, verify_result)

            total_time = time.monotonic() - pipeline_start
            metrics.record_pipeline(total_time)
            audit.log_completion(audit_id, heal_time, total_time)

            await notifier.send_healing_success(
                alert, ai_response, heal_result, verify_result,
                total_time, diagnosis_time, heal_time,
            )

            return HealingResult(
                success=verify_result.success,
                action=heal_result.action,
                resource=heal_result.resource,
                container=heal_result.container,
                status="completed" if verify_result.success else "verification_failed",
            )

        elif decision == Decision.NEED_APPROVAL:
            logger.info("发送人工审批请求")
            await notifier.send_approval_request(alert, ai_response)
            return HealingResult(
                success=False, status="pending_approval",
            )

        else:  # ONLY_NOTIFY
            logger.info("仅发送诊断通知（置信度过低）")
            await notifier.send_diagnosis_only(alert, ai_response)
            return HealingResult(
                success=False, status="notified_only",
            )

    except Exception as exc:
        total_time = time.monotonic() - pipeline_start
        logger.exception("管道异常: %s", exc)
        audit.log_pipeline_error(audit_id, str(exc))
        metrics.record_error(type(exc).__name__)
        await notifier.send_error(alert, f"管道异常: {exc}")
        return HealingResult(success=False, error=str(exc))

    finally:
        # 清理去重记录
        async with _dedup_lock:
            _recently_handled[alert.fingerprint] = datetime.now()


# ── Entrypoint ───────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level=config.log_level.lower(),
    )
