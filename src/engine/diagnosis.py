"""
诊断引擎 —— 收集故障 Pod 的全量诊断数据

并发请求 K8s API：
- Pod Status
- Namespace Events
- Pod Logs (previous + current)
- Node Conditions

策略：
1. 并发收集（Pod Status + Events + Logs 同时请求）
2. 超时控制（单个 API 调用 10s 超时）
3. 降级处理（某项数据拿不到不阻塞整体流程）
"""

import asyncio
import logging

from src.models.diagnosis import (
    DiagnosisReport, ContainerStatus, K8sEvent, NodeCondition,
)
from src.utils.k8s_client import K8sClient

logger = logging.getLogger(__name__)

# 单次 K8s API 调用超时
_API_TIMEOUT = 10.0


class DiagnosisEngine:
    """收集并聚合 K8s 诊断数据"""

    def __init__(self, k8s_client: K8sClient | None = None):
        self.k8s = k8s_client or K8sClient()

    async def collect(
        self, pod_name: str, namespace: str,
    ) -> DiagnosisReport:
        """并发收集诊断数据，构建 DiagnosisReport"""

        report = DiagnosisReport(pod_name=pod_name, namespace=namespace)

        # ── 并发请求 K8s API ────────────────────────
        pod_task = asyncio.create_task(
            self._safe_call(self.k8s.get_pod, pod_name, namespace),
        )
        events_task = asyncio.create_task(
            self._safe_call(
                self.k8s.list_events, namespace,
                field_selector=f"involvedObject.name={pod_name}",
                limit=50,
            ),
        )
        node_task: asyncio.Task | None = None
        log_current_task: asyncio.Task | None = None
        log_previous_task: asyncio.Task | None = None

        # 先拿到 Pod 基本信息，再异步获取 node + logs
        pod = await pod_task
        if pod:
            report.phase = pod.status.phase or "Unknown"
            report.node_name = pod.spec.node_name or ""
            report.restart_count = sum(
                c.restart_count or 0
                for c in (pod.status.container_statuses or [])
            )
            report.service_account = pod.spec.service_account_name or ""

            # 容器状态
            for cs in (pod.status.container_statuses or []):
                report.container_statuses.append(
                    ContainerStatus.from_k8s_status(cs),
                )

            # 资源限制
            limits, requests, image = self.k8s.get_pod_resource_limits(
                pod_name, namespace,
            )
            report.resource_limits = limits
            report.resource_requests = requests
            report.image = image

            # 镜像拉取密钥
            if pod.spec.image_pull_secrets:
                report.image_pull_secrets = [
                    s.name for s in pod.spec.image_pull_secrets
                ]

            # Owner
            owner = self.k8s.find_pod_owner(pod_name, namespace)
            if owner:
                report.owner_kind = owner["kind"]
                report.owner_name = owner["name"]

            # 异步启动 node + logs 请求
            if report.node_name:
                node_task = asyncio.create_task(
                    self._safe_call(self.k8s.get_node, report.node_name),
                )
            log_current_task = asyncio.create_task(
                self._safe_call(
                    self.k8s.get_pod_logs, pod_name, namespace,
                    previous=False, tail_lines=100,
                ),
            )
            log_previous_task = asyncio.create_task(
                self._safe_call(
                    self.k8s.get_pod_logs, pod_name, namespace,
                    previous=True, tail_lines=200,
                ),
            )

        # ── 收拢异步结果 ─────────────────────────────
        events = await events_task

        if node_task:
            node = await node_task
            if node:
                for cond in (node.status.conditions or []):
                    report.node_conditions.append(
                        NodeCondition.from_k8s_condition(cond),
                    )

        if log_current_task:
            report.current_logs = await log_current_task or ""

        if log_previous_task:
            report.previous_logs = await log_previous_task or ""

        # 事件
        if events:
            for ev in events:
                report.recent_events.append(K8sEvent.from_k8s_event(ev))

        return report

    @staticmethod
    async def _safe_call(func, *args, **kwargs):
        """
        安全调用 K8s API，带超时和异常保护。
        单个 API 失败不阻塞整体流程。
        """
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(func, *args, **kwargs),
                timeout=_API_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning("K8s API 调用超时: %s", func.__name__)
            return None
        except Exception as e:
            logger.warning("K8s API 调用失败 %s: %s", func.__name__, e)
            return None
