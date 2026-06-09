"""诊断数据模型"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContainerStatus:
    name: str = ""
    state: str = ""           # running | waiting | terminated
    reason: str = ""
    exit_code: Optional[int] = None
    restart_count: int = 0

    @classmethod
    def from_k8s_status(cls, status) -> "ContainerStatus":
        """从 K8s ContainerStatus 对象构造"""
        state = "unknown"
        reason = ""
        exit_code = None

        if status.state.running:
            state = "running"
        elif status.state.waiting:
            state = "waiting"
            reason = status.state.waiting.reason or ""
        elif status.state.terminated:
            state = "terminated"
            reason = status.state.terminated.reason or ""
            exit_code = status.state.terminated.exit_code

        return cls(
            name=status.name,
            state=state,
            reason=reason,
            exit_code=exit_code,
            restart_count=status.restart_count or 0,
        )


@dataclass
class K8sEvent:
    type: str = ""            # Normal | Warning
    reason: str = ""
    message: str = ""
    timestamp: str = ""

    @classmethod
    def from_k8s_event(cls, event) -> "K8sEvent":
        """从 K8s Event 对象构造"""
        return cls(
            type=event.type or "",
            reason=event.reason or "",
            message=event.message or "",
            timestamp=str(event.last_timestamp or event.event_time or ""),
        )


@dataclass
class NodeCondition:
    type: str = ""
    status: str = ""
    reason: str = ""

    @classmethod
    def from_k8s_condition(cls, condition) -> "NodeCondition":
        """从 K8s NodeCondition 对象构造"""
        return cls(
            type=condition.type,
            status=condition.status,
            reason=condition.reason or "",
        )


@dataclass
class DiagnosisReport:
    # Pod 层
    pod_name: str = ""
    namespace: str = ""
    phase: str = ""           # Running | Pending | Failed | Unknown
    container_statuses: list[ContainerStatus] = field(default_factory=list)
    restart_count: int = 0
    node_name: str = ""

    # 事件层
    recent_events: list[K8sEvent] = field(default_factory=list)

    # 日志层
    previous_logs: str = ""
    current_logs: str = ""

    # 资源层
    resource_limits: dict = field(default_factory=dict)
    resource_requests: dict = field(default_factory=dict)
    node_conditions: list[NodeCondition] = field(default_factory=list)

    # 上下文
    owner_kind: str = ""      # Deployment | StatefulSet | DaemonSet | Job
    owner_name: str = ""
    service_account: str = ""
    image_pull_secrets: list[str] = field(default_factory=list)
    image: str = ""
