"""
修复执行器 —— 将 AI 的修复方案转化为具体的 K8s API 调用

每个修复操作：
1. 执行前快照（用于回滚）
2. 幂等执行
3. 失败自动回滚

支持的修复类型：
- memory: 增加容器 memory limit（翻倍，上限 4Gi）
- cpu: 调整 CPU limit
- probe: 调整 readiness/liveness probe 参数
"""

import copy
import logging
from dataclasses import dataclass

from src.models.fix import HealingResult
from src.utils.k8s_client import K8sClient

logger = logging.getLogger(__name__)


@dataclass
class OwnerRef:
    kind: str       # Deployment | StatefulSet
    name: str
    namespace: str


class HealingExecutor:
    """K8s 资源修复执行器"""

    def __init__(self, k8s_client: K8sClient | None = None):
        self.k8s = k8s_client or K8sClient()

    async def execute(
        self, pod_name: str, namespace: str, fix_plan: dict,
    ) -> HealingResult:
        """
        执行修复操作的主入口。
        1. 找到 Pod 的 Owner
        2. 分发到对应 handler
        3. 执行前快照 → 修复 → 失败则回滚
        """

        # 找到 Owner
        owner = self._find_owner(pod_name, namespace)
        if not owner:
            return HealingResult(
                success=False, error="无法找到 Pod Owner",
            )

        # 分发 handler
        fix_type = fix_plan.get("fix_type", "unknown")
        handlers = {
            "memory": self._fix_memory,
            "cpu": self._fix_cpu,
            "probe": self._fix_probe,
        }

        handler = handlers.get(fix_type)
        if not handler:
            return HealingResult(
                success=False,
                error=f"不支持的修复类型: {fix_type}",
            )

        # 执行前快照
        snapshot = self._snapshot(owner)
        if snapshot is None:
            return HealingResult(
                success=False, error="创建快照失败",
            )

        try:
            result = handler(owner, fix_plan)
            if result.success:
                return result
            else:
                # 修复失败 → 回滚
                logger.warning(
                    "修复失败，尝试回滚 %s/%s: %s",
                    owner.kind, owner.name, result.error,
                )
                self._rollback(owner, snapshot)
                return result

        except Exception as e:
            logger.error("K8s API 异常: %s", e.reason)
            self._rollback(owner, snapshot)
            return HealingResult(
                success=False,
                error=f"K8s API 异常: {e.reason}",
                rollback_applied=True,
            )

    # ── Owner 解析 ──────────────────────────────────

    def _find_owner(
        self, pod_name: str, namespace: str,
    ) -> OwnerRef | None:
        """找到 Pod 的 Owner（Deployment / StatefulSet）"""

        pod = self.k8s.get_pod(pod_name, namespace)
        if not pod or not pod.metadata.owner_references:
            return None

        owner = pod.metadata.owner_references[0]

        # ReplicaSet → 上溯到 Deployment
        if owner.kind == "ReplicaSet":
            try:
                rs = self.k8s.apps_v1.read_namespaced_replica_set(
                    owner.name, namespace,
                )
                if rs.metadata.owner_references:
                    dep = rs.metadata.owner_references[0]
                    return OwnerRef(
                        kind=dep.kind,
                        name=dep.name,
                        namespace=namespace,
                    )
            except Exception as e:
                logger.warning("查找 ReplicaSet Owner 失败: %s", e.reason)
                return None

        # 只支持 Deployment 和 StatefulSet
        if owner.kind not in ("Deployment", "StatefulSet"):
            logger.warning("不支持的 Owner 类型: %s", owner.kind)
            return None

        return OwnerRef(
            kind=owner.kind, name=owner.name, namespace=namespace,
        )

    # ── Memory 修复 ─────────────────────────────────

    def _fix_memory(
        self, owner: OwnerRef, fix_plan: dict,
    ) -> HealingResult:
        """增加容器的 memory limit"""

        params = fix_plan.get("fix_params", {})
        container_name = params.get("container_name")
        new_memory = params.get("new_memory_limit")

        if not new_memory:
            return HealingResult(
                success=False, error="缺少 new_memory_limit 参数",
            )

        resource = self._get_resource(owner)
        if not resource:
            return HealingResult(
                success=False, error=f"获取 {owner.kind} 失败",
            )

        containers = self._get_containers(resource)
        target = None
        for c in containers:
            if c.name == container_name or container_name is None:
                target = c
                break

        if not target:
            return HealingResult(
                success=False,
                error=f"未找到容器: {container_name}",
            )

        old_memory = (
            target.resources.limits.get("memory", "未设置")
            if target.resources and target.resources.limits
            else "未设置"
        )
        logger.info(
            "修改 %s/%s 容器 %s: memory %s → %s",
            owner.kind, owner.name, target.name, old_memory, new_memory,
        )

        # 修改
        if not target.resources:
            from kubernetes import client as k8s_client
            target.resources = k8s_client.V1ResourceRequirements()
        if not target.resources.limits:
            target.resources.limits = {}
        target.resources.limits["memory"] = new_memory

        # 应用
        self._patch_resource(owner, resource)

        return HealingResult(
            success=True,
            action=f"memory: {old_memory} → {new_memory}",
            resource=f"{owner.kind}/{owner.name}",
            container=target.name,
        )

    # ── CPU 修复 ────────────────────────────────────

    def _fix_cpu(
        self, owner: OwnerRef, fix_plan: dict,
    ) -> HealingResult:
        """调整容器的 CPU limit"""

        params = fix_plan.get("fix_params", {})
        container_name = params.get("container_name")
        new_cpu = params.get("new_cpu_limit")

        if not new_cpu:
            return HealingResult(
                success=False, error="缺少 new_cpu_limit 参数",
            )

        resource = self._get_resource(owner)
        if not resource:
            return HealingResult(
                success=False, error=f"获取 {owner.kind} 失败",
            )

        containers = self._get_containers(resource)
        target = None
        for c in containers:
            if c.name == container_name or container_name is None:
                target = c
                break

        if not target:
            return HealingResult(
                success=False,
                error=f"未找到容器: {container_name}",
            )

        old_cpu = (
            target.resources.limits.get("cpu", "未设置")
            if target.resources and target.resources.limits
            else "未设置"
        )

        if not target.resources:
            from kubernetes import client as k8s_client
            target.resources = k8s_client.V1ResourceRequirements()
        if not target.resources.limits:
            target.resources.limits = {}
        target.resources.limits["cpu"] = new_cpu

        self._patch_resource(owner, resource)

        return HealingResult(
            success=True,
            action=f"cpu: {old_cpu} → {new_cpu}",
            resource=f"{owner.kind}/{owner.name}",
            container=target.name,
        )

    # ── Probe 修复 ──────────────────────────────────

    def _fix_probe(
        self, owner: OwnerRef, fix_plan: dict,
    ) -> HealingResult:
        """调整 readiness/liveness probe 参数"""

        params = fix_plan.get("fix_params", {})
        container_name = params.get("container_name")
        probe_type = params.get("probe_type", "readiness")
        field = params.get("field")
        new_value = params.get("new_value")

        if not field or new_value is None:
            return HealingResult(
                success=False, error="缺少 probe 修改参数",
            )

        resource = self._get_resource(owner)
        if not resource:
            return HealingResult(
                success=False, error=f"获取 {owner.kind} 失败",
            )

        containers = self._get_containers(resource)
        target = None
        for c in containers:
            if c.name == container_name or container_name is None:
                target = c
                break

        if not target:
            return HealingResult(
                success=False,
                error=f"未找到容器: {container_name}",
            )

        # 获取目标 probe
        probe = None
        if probe_type == "readiness" and target.readiness_probe:
            probe = target.readiness_probe
        elif probe_type == "liveness" and target.liveness_probe:
            probe = target.liveness_probe

        if not probe:
            return HealingResult(
                success=False,
                error=f"容器 {target.name} 无 {probe_type} probe",
            )

        old_value = getattr(probe, field, "未设置")
        setattr(probe, field, new_value)

        self._patch_resource(owner, resource)

        return HealingResult(
            success=True,
            action=f"probe {probe_type}.{field}: {old_value} → {new_value}",
            resource=f"{owner.kind}/{owner.name}",
            container=target.name,
        )

    # ── 快照与回滚 ──────────────────────────────────

    def _snapshot(self, owner: OwnerRef) -> dict | None:
        """创建资源的 deep copy 快照，用于回滚"""
        resource = self._get_resource(owner)
        if resource is None:
            return None

        # 用 K8s client 的 serialize/deserialize 做 deep copy
        body = self.k8s.apps_v1.api_client.sanitize_for_serialization(
            resource,
        )
        return copy.deepcopy(body)

    def _rollback(self, owner: OwnerRef, snapshot: dict):
        """回滚到快照状态"""
        try:
            logger.warning(
                "回滚 %s/%s 到修复前状态",
                owner.kind, owner.name,
            )
            self._patch_resource(owner, snapshot)
        except Exception as e:
            logger.error("回滚失败! %s", e)

    # ── 辅助方法 ────────────────────────────────────

    def _get_resource(self, owner: OwnerRef):
        """根据 Owner 类型获取资源对象"""
        if owner.kind == "Deployment":
            return self.k8s.get_deployment(owner.name, owner.namespace)
        elif owner.kind == "StatefulSet":
            return self.k8s.get_statefulset(owner.name, owner.namespace)
        raise ValueError(f"不支持的资源类型: {owner.kind}")

    @staticmethod
    def _get_containers(resource) -> list:
        """从资源对象中提取 containers"""
        if hasattr(resource, "spec") and hasattr(resource.spec, "template"):
            spec = resource.spec.template.spec
            if hasattr(spec, "containers"):
                return spec.containers
        return []

    def _patch_resource(self, owner: OwnerRef, body):
        """Patch 资源到 K8s"""
        if owner.kind == "Deployment":
            self.k8s.apps_v1.patch_namespaced_deployment(
                owner.name, owner.namespace, body,
            )
        elif owner.kind == "StatefulSet":
            self.k8s.apps_v1.patch_namespaced_stateful_set(
                owner.name, owner.namespace, body,
            )
