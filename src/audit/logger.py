"""
审计日志 —— 记录每次诊断、决策、修复的完整信息

目标：能回答"AI 什么时候做了什么、为什么"

Schema:
  healing_audit (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    alert_name TEXT,
    pod_name TEXT,
    namespace TEXT,
    severity TEXT,
    root_cause TEXT,
    fix_type TEXT,
    fix_action TEXT,
    confidence REAL,
    decision TEXT,
    result TEXT,
    error TEXT,
    diagnosis_time REAL,
    analyze_time REAL,
    heal_time REAL,
    total_time REAL,
  )
"""

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS healing_audit (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    alert_name TEXT,
    pod_name TEXT,
    namespace TEXT,
    severity TEXT,
    root_cause TEXT,
    fix_type TEXT,
    fix_action TEXT,
    confidence REAL,
    decision TEXT,
    result TEXT,
    error TEXT,
    diagnosis_time REAL,
    analyze_time REAL,
    heal_time REAL,
    total_time REAL,
    details TEXT
);
"""


class AuditLogger:
    """自愈操作审计日志"""

    def __init__(self, db_path: str = "data/healing_audit.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库 schema"""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(SCHEMA_SQL)
            conn.commit()

    def _generate_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Public API ──────────────────────────────────

    def start_healing(self, alert) -> str:
        """记录一次自愈流程开始，返回 audit_id"""
        audit_id = self._generate_id()

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO healing_audit
                       (id, created_at, alert_name, pod_name,
                        namespace, severity)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        audit_id,
                        self._now(),
                        getattr(alert, "alert_name", ""),
                        getattr(alert, "pod_name", ""),
                        getattr(alert, "namespace", ""),
                        getattr(alert, "severity", ""),
                    ),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error("写入审计日志失败: %s", e)

        return audit_id

    def log_validation_failure(self, audit_id: str, error: str):
        self._update(audit_id, result="validation_failed", error=error)

    def log_safety_block(self, audit_id: str, reason: str):
        self._update(audit_id, result="safety_blocked", error=reason)

    def log_loop_guard_block(self, audit_id: str, reason: str):
        self._update(audit_id, result="loop_guard_blocked", error=reason)

    def log_healing_failure(self, audit_id: str, result):
        self._update(
            audit_id,
            result="healing_failed",
            error=result.error if hasattr(result, "error") else str(result),
        )

    def log_healing_complete(
        self, audit_id: str, heal_result, verify_result,
    ):
        success = verify_result.success if hasattr(verify_result, "success") else False
        self._update(
            audit_id,
            result="healed" if success else "verification_failed",
            error="" if success else getattr(verify_result, "reason", ""),
        )

    def log_pipeline_error(self, audit_id: str, error: str):
        self._update(audit_id, result="pipeline_error", error=error)

    def log_decision(
        self, audit_id: str, ai_response: dict, decision: str,
        diagnosis_time: float, analyze_time: float,
    ):
        """记录 AI 分析结果和决策"""
        self._update(
            audit_id,
            root_cause=ai_response.get("root_cause", ""),
            fix_type=ai_response.get("fix_type", ""),
            fix_action=ai_response.get("fix_action", ""),
            confidence=ai_response.get("confidence", 0.0),
            decision=decision,
            diagnosis_time=diagnosis_time,
            analyze_time=analyze_time,
        )

    def log_completion(
        self, audit_id: str, heal_time: float, total_time: float,
    ):
        self._update(audit_id, heal_time=heal_time, total_time=total_time)

    # ── Internal ────────────────────────────────────

    def _update(self, audit_id: str, **kwargs):
        """更新审计记录"""
        if not kwargs:
            return

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [audit_id]

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    f"UPDATE healing_audit SET {set_clause} WHERE id = ?",
                    values,
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error("更新审计日志失败: %s", e)
