"""诊断引擎单元测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.diagnosis import DiagnosisReport


class TestDiagnosisReport:
    """测试诊断数据模型 (不需要 K8s)"""

    def test_create_minimal_report(self):
        report = DiagnosisReport(pod_name="test-pod", namespace="default")
        assert report.pod_name == "test-pod"
        assert report.namespace == "default"
        assert report.phase == ""

    def test_container_status_from_k8s(self):
        """ContainerStatus.from_k8s_status 工厂方法"""
        from src.models.diagnosis import ContainerStatus

        # Mock a terminated container status
        mock_status = MagicMock()
        mock_status.name = "app"
        mock_status.state.running = None
        mock_status.state.waiting = None
        mock_status.state.terminated.reason = "OOMKilled"
        mock_status.state.terminated.exit_code = 137
        mock_status.restart_count = 3

        cs = ContainerStatus.from_k8s_status(mock_status)
        assert cs.name == "app"
        assert cs.state == "terminated"
        assert cs.reason == "OOMKilled"
        assert cs.exit_code == 137
        assert cs.restart_count == 3

    def test_k8s_event_from_k8s(self):
        """K8sEvent.from_k8s_event 工厂方法"""
        from src.models.diagnosis import K8sEvent

        mock_event = MagicMock()
        mock_event.type = "Warning"
        mock_event.reason = "OOMKilling"
        mock_event.message = "Memory cgroup out of memory"
        mock_event.last_timestamp = None
        mock_event.event_time = None

        ev = K8sEvent.from_k8s_event(mock_event)
        assert ev.type == "Warning"
        assert ev.reason == "OOMKilling"

    def test_report_with_containers(self):
        """完整的诊断报告包含容器状态"""
        from src.models.diagnosis import ContainerStatus

        cs = ContainerStatus(
            name="app",
            state="terminated",
            reason="Error",
            exit_code=1,
            restart_count=4,
        )

        report = DiagnosisReport(
            pod_name="crash-pod",
            namespace="staging",
            phase="Running",
            node_name="node-2",
            restart_count=4,
            container_statuses=[cs],
            resource_limits={"memory": "512Mi", "cpu": "1"},
            resource_requests={"memory": "256Mi", "cpu": "500m"},
            owner_kind="Deployment",
            owner_name="my-app",
            image="myapp:v2.0.0",
        )

        assert len(report.container_statuses) == 1
        assert report.container_statuses[0].reason == "Error"
        assert report.resource_limits["memory"] == "512Mi"
        assert report.owner_kind == "Deployment"
