"""
Tests for mqtt_publisher module.

Tests MQTT Discovery message format, topic generation, and publish logic.
"""

import json
import sys
import os
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mqtt_publisher import MQTTPublisher, DISCOVERY_PREFIX, STATE_PREFIX, AVAILABILITY_TOPIC


class TestMQTTTopics:
    """Test topic naming conventions."""

    def test_availability_topic(self):
        assert AVAILABILITY_TOPIC == "emporia/collector/status"

    def test_discovery_prefix(self):
        assert DISCOVERY_PREFIX == "homeassistant"

    def test_state_prefix(self):
        assert STATE_PREFIX == "emporia"


class TestMQTTPublisherInit:
    """Test publisher initialization."""

    @patch("mqtt_publisher.mqtt.Client")
    def test_creates_client_with_id(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost", broker_port=1883)

        mock_client_class.assert_called_once()
        # LWT should be set
        mock_client.will_set.assert_called_once_with(
            AVAILABILITY_TOPIC,
            payload="offline",
            qos=1,
            retain=True,
        )

    @patch("mqtt_publisher.mqtt.Client")
    def test_sets_credentials(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(
            broker_host="localhost",
            username="user",
            password="pass",
        )

        mock_client.username_pw_set.assert_called_once_with("user", "pass")

    @patch("mqtt_publisher.mqtt.Client")
    def test_no_credentials_when_none(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        mock_client.username_pw_set.assert_not_called()


class TestMQTTDiscovery:
    """Test HA MQTT Discovery message format."""

    @patch("mqtt_publisher.mqtt.Client")
    def test_discovery_message_format(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_discovery(
            device_gid=12345,
            device_model="VUE003",
            device_name="Home Panel",
            channel_num="1,2,3",
            channel_name="Main",
            channel_slug="main",
        )

        # Check the discovery topics (power + energy = 2 messages)
        publish_calls = mock_client.publish.call_args_list
        assert len(publish_calls) == 2

        # Power sensor discovery
        topic = publish_calls[0][0][0]
        assert topic == "homeassistant/sensor/emporia_12345_main/config"

        payload = json.loads(publish_calls[0][0][1])
        assert payload["name"] == "Main Power"
        assert payload["unique_id"] == "emporia_12345_main"
        assert payload["unit_of_measurement"] == "W"
        assert payload["device_class"] == "power"
        assert payload["state_class"] == "measurement"
        assert payload["availability_topic"] == AVAILABILITY_TOPIC
        assert payload["state_topic"] == "emporia/device/12345/channel/main/state"
        assert payload["value_template"] == "{{ value_json.watts }}"

        # Energy sensor discovery
        energy_topic = publish_calls[1][0][0]
        assert energy_topic == "homeassistant/sensor/emporia_12345_main_energy/config"

        energy_payload = json.loads(publish_calls[1][0][1])
        assert energy_payload["name"] == "Main Energy"
        assert energy_payload["unique_id"] == "emporia_12345_main_energy"
        assert energy_payload["unit_of_measurement"] == "kWh"
        assert energy_payload["device_class"] == "energy"
        assert energy_payload["state_class"] == "total_increasing"
        assert energy_payload["value_template"] == "{{ value_json.total_kwh }}"

    @patch("mqtt_publisher.mqtt.Client")
    def test_discovery_device_info(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_discovery(
            device_gid=99,
            device_model="VUE003",
            device_name="My Vue",
            channel_num="5",
            channel_name="Dryer",
            channel_slug="dryer",
        )

        # Should publish two configs: power and energy
        assert mock_client.publish.call_count == 2

        # Check power sensor (first call)
        power_payload = json.loads(mock_client.publish.call_args_list[0][0][1])
        assert power_payload["device_class"] == "power"
        assert power_payload["unit_of_measurement"] == "W"
        device = power_payload["device"]
        assert device["identifiers"] == ["emporia_vue_99"]
        assert device["name"] == "Emporia Vue - My Vue"
        assert device["manufacturer"] == "Emporia Energy"

        # Check energy sensor (second call)
        energy_payload = json.loads(mock_client.publish.call_args_list[1][0][1])
        assert energy_payload["device_class"] == "energy"
        assert energy_payload["state_class"] == "total_increasing"
        assert energy_payload["unit_of_measurement"] == "kWh"
        assert energy_payload["unique_id"] == "emporia_99_dryer_energy"

    @patch("mqtt_publisher.mqtt.Client")
    def test_discovery_retained(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_discovery(
            device_gid=1, device_name="X", device_model="VUE003",
            channel_num="1", channel_name="Y", channel_slug="y",
        )

        # Both power and energy discovery messages should be retained
        for call_item in mock_client.publish.call_args_list:
            assert call_item[1]["qos"] == 1
            assert call_item[1]["retain"] is True

    @patch("mqtt_publisher.mqtt.Client")
    def test_discovery_not_sent_twice(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_discovery(
            device_gid=1, device_name="X", device_model="VUE003",
            channel_num="1", channel_name="Y", channel_slug="y",
        )
        pub.publish_discovery(
            device_gid=1, device_name="X", device_model="VUE003",
            channel_num="1", channel_name="Y", channel_slug="y",
        )

        # 2 messages (power + energy) on first call, nothing on second
        assert mock_client.publish.call_count == 2


class TestMQTTPublishEnergyCost:
    """Test energy cost sensor publishing."""

    @patch("mqtt_publisher.mqtt.Client")
    def test_publishes_cost_sensor(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_energy_cost(
            device_gid=605039,
            device_name="Inhab",
            device_model="VUE003",
            cost_cent_per_kwh=13.2,
        )

        # Should publish discovery config + state value
        assert mock_client.publish.call_count == 2

        # Discovery config
        discovery_call = mock_client.publish.call_args_list[0]
        assert "homeassistant/sensor/emporia_605039_energy_cost/config" in discovery_call[0]
        config = json.loads(discovery_call[0][1])
        assert config["unit_of_measurement"] == "$/kWh"
        assert config["name"] == "Inhab Energy Cost"
        assert config["unique_id"] == "emporia_605039_energy_cost"

        # State value (cents to dollars)
        state_call = mock_client.publish.call_args_list[1]
        assert "energy_cost" in state_call[0][0]
        assert state_call[0][1] == "0.132"

    @patch("mqtt_publisher.mqtt.Client")
    def test_cost_not_sent_twice(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_energy_cost(
            device_gid=1, device_name="X", device_model="VUE003",
            cost_cent_per_kwh=10.0,
        )
        pub.publish_energy_cost(
            device_gid=1, device_name="X", device_model="VUE003",
            cost_cent_per_kwh=10.0,
        )

        # 2 messages on first call (discovery + state), nothing on second
        assert mock_client.publish.call_count == 2

    @patch("mqtt_publisher.mqtt.Client")
    def test_cost_is_retained(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_energy_cost(
            device_gid=1, device_name="X", device_model="VUE003",
            cost_cent_per_kwh=16.5,
        )

        # Both discovery and state should be retained
        for call_item in mock_client.publish.call_args_list:
            assert call_item[1]["retain"] is True


class TestMQTTPublishUsage:
    """Test usage data publishing."""

    @patch("mqtt_publisher.mqtt.Client")
    def test_publishes_correct_topic_and_payload(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_usage(
            device_gid=12345,
            channel_slug="oven",
            watts=1500.5,
            usage_kwh=0.025,
            total_kwh=8.5,
            percentage=25.0,
        )

        mock_client.publish.assert_called_once()
        topic = mock_client.publish.call_args[0][0]
        assert topic == "emporia/device/12345/channel/oven/state"

        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["watts"] == 1500.5
        assert payload["kwh"] == 0.025
        assert payload["total_kwh"] == 8.5
        assert payload["percentage"] == 25.0

    @patch("mqtt_publisher.mqtt.Client")
    def test_publishes_null_watts(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_usage(
            device_gid=1,
            channel_slug="offline",
            watts=None,
            usage_kwh=None,
            total_kwh=None,
            percentage=0.0,
        )

        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["watts"] is None
        assert payload["kwh"] is None
        assert payload["total_kwh"] is None

    @patch("mqtt_publisher.mqtt.Client")
    def test_skips_publish_when_disconnected(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = False

        pub.publish_usage(
            device_gid=1, channel_slug="x",
            watts=100.0, usage_kwh=0.01, total_kwh=1.5, percentage=5.0,
        )

        mock_client.publish.assert_not_called()

    @patch("mqtt_publisher.mqtt.Client")
    def test_usage_not_retained(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.publish_usage(
            device_gid=1, channel_slug="x",
            watts=100.0, usage_kwh=0.01, total_kwh=1.5, percentage=5.0,
        )

        kwargs = mock_client.publish.call_args[1]
        assert kwargs["retain"] is False


class TestMQTTConnection:
    """Test connection handling."""

    @patch("mqtt_publisher.mqtt.Client")
    @patch("mqtt_publisher.time.sleep")
    def test_publishes_online_on_connect(self, mock_sleep, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")

        # Simulate successful connection callback
        pub._on_connect(mock_client, None, None, 0)

        assert pub._connected is True
        mock_client.publish.assert_called_with(
            AVAILABILITY_TOPIC, "online", qos=1, retain=True,
        )

    @patch("mqtt_publisher.mqtt.Client")
    def test_marks_disconnected_on_disconnect(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub._on_disconnect(mock_client, None, None, 0)
        assert pub._connected is False

    @patch("mqtt_publisher.mqtt.Client")
    @patch("mqtt_publisher.time.sleep")
    def test_disconnect_publishes_offline(self, mock_sleep, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        pub = MQTTPublisher(broker_host="localhost")
        pub._connected = True

        pub.disconnect()

        # Should publish offline before disconnecting
        offline_call = None
        for c in mock_client.publish.call_args_list:
            if c[0][0] == AVAILABILITY_TOPIC and c[0][1] == "offline":
                offline_call = c
                break
        assert offline_call is not None
        mock_client.loop_stop.assert_called_once()
        mock_client.disconnect.assert_called_once()
