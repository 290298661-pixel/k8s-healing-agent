"""配置管理单元测试"""
import os


class TestConfig:
    """Config 加载测试"""

    def test_from_example_yaml(self):
        """从 config.example.yaml 加载配置"""
        from src.config import Config
        config = Config.from_yaml("config/config.example.yaml")
        assert config.log_level == "INFO"
        assert config.confidence_auto_exec == 0.8
        assert config.confidence_approval == 0.5
        assert "default" in config.allowed_namespaces

    def test_default_values(self):
        """无配置文件时使用默认值"""
        from src.config import Config
        config = Config.from_yaml("config/nonexistent.yaml")
        assert config.audit_db_path == "data/healing_audit.db"
        assert len(config.allowed_namespaces) == 3

    def test_env_override(self):
        """环境变量覆盖配置"""
        os.environ["CLAUDE_API_KEY"] = "test-key-123"
        os.environ["DINGTALK_WEBHOOK"] = "https://test.example.com/webhook"

        from src.config import Config
        config = Config.from_yaml("config/config.example.yaml")
        assert config.claude_api_key == "test-key-123"
        assert config.dingtalk_webhook == "https://test.example.com/webhook"

        # Cleanup
        del os.environ["CLAUDE_API_KEY"]
        del os.environ["DINGTALK_WEBHOOK"]
