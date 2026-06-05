"""
Tests for main.py module.

Tests configuration validation, signal handling, and polling loop logic.
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestValidateConfig:
    """Test environment variable validation."""

    @patch.dict(os.environ, {
        "EMPORIA_EMAIL": "test@test.com",
        "EMPORIA_PASSWORD": "pass",
        "MQTT_USERNAME": "user",
        "MQTT_PASSWORD": "mqttpass",
    })
    def test_valid_config(self):
        # Need to reimport to pick up env vars
        import importlib
        import main
        importlib.reload(main)
        assert main.validate_config() is True

    @patch.dict(os.environ, {
        "EMPORIA_EMAIL": "",
        "EMPORIA_PASSWORD": "pass",
        "MQTT_USERNAME": "user",
        "MQTT_PASSWORD": "mqttpass",
    })
    def test_missing_email(self):
        import importlib
        import main
        importlib.reload(main)
        assert main.validate_config() is False

    @patch.dict(os.environ, {
        "EMPORIA_EMAIL": "test@test.com",
        "EMPORIA_PASSWORD": "",
        "MQTT_USERNAME": "user",
        "MQTT_PASSWORD": "mqttpass",
    })
    def test_missing_password(self):
        import importlib
        import main
        importlib.reload(main)
        assert main.validate_config() is False

    @patch.dict(os.environ, {
        "EMPORIA_EMAIL": "test@test.com",
        "EMPORIA_PASSWORD": "pass",
        "MQTT_USERNAME": "",
        "MQTT_PASSWORD": "",
    })
    def test_missing_mqtt_creds(self):
        import importlib
        import main
        importlib.reload(main)
        assert main.validate_config() is False


class TestSignalHandling:
    """Test graceful shutdown via signals."""

    def test_shutdown_flag_set_on_signal(self):
        import main
        main.shutdown_requested = False
        main.handle_signal(15, None)
        assert main.shutdown_requested is True
