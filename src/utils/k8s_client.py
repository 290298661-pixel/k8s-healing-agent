"""
K8s 客户端封装 —— 统一的 K8s API 调用层
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from kubernetes import client

logger = logging.getLogger(__name__)


class K8sClient:
    """Kubernetes API 客户端封装 (kubernetes 导入是 lazy 的)"""

    def __init__(self):
        try:
            from kubernetes import client, config
        except ImportError:
            raise ImportError(
                "kubernetes package not installed. "
                "Install with: pip install kubernetes"
            )

        try:
            config.load_incluster_config()
            logger.info("使用 InCluster 配置连接 K8s")
        except config.ConfigException:
            config.load_kube_config()
            logger.info("使用 kubeconfig 连接 K8s")

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    # ── Pod operations ──────────────────────────────

    def get_pod(self, name: str, namespace: str) -> Optional[client.V1Pod]:
        """获取 Pod 对象"""
        try:
            return self.core_v1.read_namespaced_pod(name, namespace)
        except Exception as e:
            logger.error("获取 Pod %s/%s 失败: %s", namespace, name, e)
            return None

    def get_pod_logs(
        self,
        name: str,
        namespace: str,
        previous: bool = False,
        tail_lines: int = 200,
        container: Optional[str] = None,
    ) -> str:
        """获取 Pod 日志"""
        try:
            kwargs = {
                "name": name,
                "namespace": namespace,
                "previous": previous,
                "tail_lines": tail_lines,
            }
            if container:
                kwargs["container"] = container
            return self.core_v1.read_namespaced_pod_log(**kwargs)
        except Exception as e:
            logger.warning(
                "获取日志失败 %s/%s (previous=%s): %s",
                namespace, name, previous, e.reason,
            )
            return ""

    # ── Event operations ────────────────────────────

    def list_events(
        self,
        namespace: str,
        field_selector: str = "",
        limit: int = 50,
    ) -> list[client.CoreV1Event]:
        """获取 Namespace Events"""
        try:
            kwargs = {"namespace": namespace, "limit": limit}
            if field_selector:
                kwargs["field_selector"] = field_selector
            events = self.core_v1.list_namespaced_event(**kwargs)
            return events.items or []
        except Exception as e:
            logger.error("获取 Events 失败 %s: %s", namespace, e.reason)
            return []

    # ── Node operations ─────────────────────────────

    def get_node(self, name: str) -> Optional[client.V1Node]:
        """获取 Node 对象"""
        try:
            return self.core_v1.read_node(name)
        except Exception as e:
            logger.error("获取 Node %s 失败: %s", name, e.reason)
            return None

    # ── Owner resolution ────────────────────────────

    def find_pod_owner(
        self, pod_name: str, namespace: str,
    ) -> Optional[dict]:
        """
        找到 Pod 的 Owner。
        返回 {"kind": "Deployment", "name": "...", "namespace": "..."}
        RevisionSet → 继续上溯到 Deployment。
        """
        pod = self.get_pod(pod_name, namespace)
        if not pod or not pod.metadata.owner_references:
            return None

        owner = pod.metadata.owner_references[0]

        # ReplicaSet → Deployment
        if owner.kind == "ReplicaSet":
            try:
                rs = self.apps_v1.read_namespaced_replica_set(
                    owner.name, namespace,
                )
                if rs.metadata.owner_references:
                    dep = rs.metadata.owner_references[0]
                    return {
                        "kind": dep.kind,
                        "name": dep.name,
                        "namespace": namespace,
                    }
            except Exception as e:
                logger.warning("查找 ReplicaSet owner 失败: %s", e.reason)

        return {
            "kind": owner.kind,
            "name": owner.name,
            "namespace": namespace,
        }

    # ── Write operations ────────────────────────────

    def get_deployment(
        self, name: str, namespace: str,
    ) -> Optional[client.V1Deployment]:
        """获取 Deployment 对象"""
        try:
            return self.apps_v1.read_namespaced_deployment(name, namespace)
        except Exception as e:
            logger.error("获取 Deployment %s/%s 失败: %s",
                         namespace, name, e.reason)
            return None

    def get_statefulset(
        self, name: str, namespace: str,
    ) -> Optional[client.V1StatefulSet]:
        """获取 StatefulSet 对象"""
        try:
            return self.apps_v1.read_namespaced_stateful_set(name, namespace)
        except Exception as e:
            logger.error("获取 StatefulSet %s/%s 失败: %s",
                         namespace, name, e.reason)
            return None

    def patch_deployment(
        self, name: str, namespace: str, body,
    ) -> bool:
        """Patch Deployment"""
        try:
            self.apps_v1.patch_namespaced_deployment(name, namespace, body)
            return True
        except Exception as e:
            logger.error("Patch Deployment %s/%s 失败: %s",
                         namespace, name, e.reason)
            return False

    def patch_statefulset(
        self, name: str, namespace: str, body,
    ) -> bool:
        """Patch StatefulSet"""
        try:
            self.apps_v1.patch_namespaced_stateful_set(name, namespace, body)
            return True
        except Exception as e:
            logger.error("Patch StatefulSet %s/%s 失败: %s",
                         namespace, name, e.reason)
            return False

    def get_pod_resource_limits(
        self, pod_name: str, namespace: str,
    ) -> tuple[dict, dict, str]:
        """
        获取 Pod 中主容器的资源限制和请求。
        返回 (limits, requests, image)
        """
        pod = self.get_pod(pod_name, namespace)
        if not pod or not pod.spec.containers:
            return {}, {}, ""

        # 取第一个容器作为主容器
        container = pod.spec.containers[0]
        limits = {}
        requests = {}
        if container.resources:
            if container.resources.limits:
                limits = dict(container.resources.limits)
            if container.resources.requests:
                requests = dict(container.resources.requests)

        return limits, requests, container.image or ""
