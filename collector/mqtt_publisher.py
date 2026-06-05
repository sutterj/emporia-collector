"""
MQTT publisher with Home Assistant Discovery support.

Publishes energy data to MQTT and auto-configures HA sensor entities.
"""

import json
import logging
import time

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# MQTT topic prefixes
DISCOVERY_PREFIX = "homeassistant"
STATE_PREFIX = "emporia"
AVAILABILITY_TOPIC = f"{STATE_PREFIX}/collector/status"


class MQTTPublisher:
    """Publishes Emporia data to MQTT with HA Discovery."""

    def __init__(
        self,
        broker_host: str = "mosquitto",
        broker_port: int = 1883,
        username: str | None = None,
        password: str | None = None,
    ):
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._client = mqtt.Client(
            client_id="emporia-collector",
            protocol=mqtt.MQTTv5,
        )

        if username and password:
            self._client.username_pw_set(username, password)

        # Last Will and Testament: mark offline if we disconnect unexpectedly
        self._client.will_set(
            AVAILABILITY_TOPIC,
            payload="offline",
            qos=1,
            retain=True,
        )

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._connected = False
        self._discovery_sent: set[str] = set()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("Connected to MQTT broker")
            self._connected = True
            # Publish online status
            self._client.publish(
                AVAILABILITY_TOPIC, "online", qos=1, retain=True
            )
        else:
            logger.error("MQTT connection failed: %s", reason_code)
            self._connected = False

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        logger.warning("Disconnected from MQTT broker: %s", reason_code)
        self._connected = False

    def connect(self) -> None:
        """Connect to the MQTT broker with retries."""
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                self._client.connect(self._broker_host, self._broker_port)
                self._client.loop_start()
                # Wait for connection
                deadline = time.time() + 10
                while not self._connected and time.time() < deadline:
                    time.sleep(0.1)
                if self._connected:
                    return
                logger.warning("Connection timed out, attempt %d", attempt + 1)
            except (ConnectionRefusedError, OSError) as e:
                logger.warning(
                    "MQTT connect failed (attempt %d/%d): %s",
                    attempt + 1, max_attempts, e,
                )
            wait = min(2 ** attempt, 30)
            time.sleep(wait)

        raise RuntimeError("Failed to connect to MQTT broker")

    def disconnect(self) -> None:
        """Gracefully disconnect."""
        if self._connected:
            self._client.publish(
                AVAILABILITY_TOPIC, "offline", qos=1, retain=True
            )
            time.sleep(0.5)
        self._client.loop_stop()
        self._client.disconnect()

    def publish_discovery(
        self,
        device_gid: int,
        device_name: str,
        device_model: str,
        channel_num: str,
        channel_name: str,
        channel_slug: str,
    ) -> None:
        """Publish HA MQTT Discovery configs for power (W) and energy (kWh) sensors."""
        unique_id = f"emporia_{device_gid}_{channel_slug}"

        if unique_id in self._discovery_sent:
            return

        state_topic = (
            f"{STATE_PREFIX}/device/{device_gid}"
            f"/channel/{channel_slug}/state"
        )

        # Map model codes to friendly names
        model_names = {
            "VUE001": "Vue Gen 1",
            "VUE002": "Vue Gen 2",
            "VUE003": "Vue Gen 3",
        }
        friendly_model = model_names.get(device_model, device_model)

        device_info = {
            "identifiers": [f"emporia_vue_{device_gid}"],
            "name": f"Emporia Vue - {device_name}",
            "manufacturer": "Emporia Energy",
            "model": friendly_model,
        }

        # Power sensor (W) - for real-time display
        power_config = {
            "name": f"{channel_name} Power",
            "unique_id": unique_id,
            "state_topic": state_topic,
            "value_template": "{{ value_json.watts }}",
            "unit_of_measurement": "W",
            "device_class": "power",
            "state_class": "measurement",
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device_info,
            "json_attributes_topic": state_topic,
        }

        self._client.publish(
            f"{DISCOVERY_PREFIX}/sensor/{unique_id}/config",
            json.dumps(power_config),
            qos=1,
            retain=True,
        )

        # Energy sensor (kWh) - for HA Energy dashboard
        energy_unique_id = f"{unique_id}_energy"
        energy_config = {
            "name": f"{channel_name} Energy",
            "unique_id": energy_unique_id,
            "state_topic": state_topic,
            "value_template": "{{ value_json.total_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "state_class": "total_increasing",
            "availability_topic": AVAILABILITY_TOPIC,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device_info,
        }

        self._client.publish(
            f"{DISCOVERY_PREFIX}/sensor/{energy_unique_id}/config",
            json.dumps(energy_config),
            qos=1,
            retain=True,
        )

        self._discovery_sent.add(unique_id)
        logger.debug("Published discovery for %s (power + energy)", unique_id)

    def publish_usage(
        self,
        device_gid: int,
        channel_slug: str,
        watts: float | None,
        usage_kwh: float | None,
        total_kwh: float | None,
        percentage: float,
    ) -> None:
        """Publish a usage reading."""
        if not self._connected:
            logger.warning("Not connected to MQTT, skipping publish")
            return

        state_topic = (
            f"{STATE_PREFIX}/device/{device_gid}"
            f"/channel/{channel_slug}/state"
        )

        payload = {
            "watts": watts,
            "kwh": usage_kwh,
            "total_kwh": total_kwh,
            "percentage": percentage,
        }

        self._client.publish(
            state_topic,
            json.dumps(payload),
            qos=0,
            retain=False,
        )

    @property
    def is_connected(self) -> bool:
        return self._connected
