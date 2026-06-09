"""修复方案模型"""
from dataclasses import dataclass, field
from enum import Enum


class FixType(str, Enum):
    MEMORY = "memory"
    CPU = "cpu"
    IMAGE = "image"
    CONFIG = "config"
    RESOURCE_QUOTA = "resource_quota"
    PROBE = "probe"
    PVC = "pvc"
    UNKNOWN = "unknown"


class Decision(str, Enum):
    AUTO_EXEC = "AUTO_EXEC"        # confidence >= 0.8
    NEED_APPROVAL = "APPROVAL"     # 0.5 <= c < 0.8
    ONLY_NOTIFY = "ONLY_NOTIFY"    # c < 0.5


@dataclass
class FixPlan:
    root_cause: str = ""
    fix_type: FixType = FixType.UNKNOWN
    fix_action: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    alternative_causes: list[str] = field(default_factory=list)
    severity_assessment: str = ""
    fix_params: dict = field(default_factory=dict)


@dataclass
class HealingResult:
    success: bool = False
    action: str = ""
    resource: str = ""
    container: str = ""
    error: str = ""
    rollback_applied: bool = False
    status: str = ""  # completed | pending_approval | notified_only | failed


@dataclass
class VerifyResult:
    success: bool = False
    reason: str = ""
