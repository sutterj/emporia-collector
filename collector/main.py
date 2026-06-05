"""
Emporia Vue Energy Collector - Main entry point.

Polls Emporia cloud API and publishes energy data to MQTT
for Home Assistant consumption via MQTT Discovery.
"""

import logging
import os
import random
import signal
import sys
import time

from cognito_srp import CognitoAuth
from emporia_api import EmporiaAPI
from mqtt_publisher import MQTTPublisher

# Configuration from environment variables
EMPORIA_EMAIL = os.environ.get("EMPORIA_EMAIL", "")
EMPORIA_PASSWORD = os.environ.get("EMPORIA_PASSWORD", "")
MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Configure logging (never log secrets)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("collector")

# Graceful shutdown
shutdown_requested = False


def handle_signal(signum, frame):
    global shutdown_requested
    logger.info("Shutdown signal received")
    shutdown_requested = True


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def validate_config() -> bool:
    """Validate required configuration is present."""
    missing = []
    if not EMPORIA_EMAIL:
        missing.append("EMPORIA_EMAIL")
    if not EMPORIA_PASSWORD:
        missing.append("EMPORIA_PASSWORD")
    if not MQTT_USERNAME:
        missing.append("MQTT_USERNAME")
    if not MQTT_PASSWORD:
        missing.append("MQTT_PASSWORD")

    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        return False
    return True


def main():
    logger.info("Emporia Vue Collector starting")
    logger.info(
        "Config: poll_interval=%ds, mqtt=%s:%d",
        POLL_INTERVAL, MQTT_HOST, MQTT_PORT,
    )

    if not validate_config():
        sys.exit(1)

    # Initialize components
    auth = CognitoAuth(EMPORIA_EMAIL, EMPORIA_PASSWORD)
    api = EmporiaAPI(auth)
    publisher = MQTTPublisher(
        broker_host=MQTT_HOST,
        broker_port=MQTT_PORT,
        username=MQTT_USERNAME,
        password=MQTT_PASSWORD,
    )

    # Connect to MQTT
    logger.info("Connecting to MQTT broker...")
    publisher.connect()
    logger.info("MQTT connected")

    # Authenticate with Emporia
    logger.info("Authenticating with Emporia...")
    try:
        auth.authenticate()
        logger.info("Emporia authentication successful")
    except Exception as e:
        logger.error("Authentication failed: %s", e)
        publisher.disconnect()
        sys.exit(1)

    # Fetch device list
    logger.info("Fetching device list...")
    try:
        devices = api.get_devices()
        logger.info("Found %d device(s)", len(devices))
        for dev in devices:
            logger.info(
                "  Device: %s (gid=%d, model=%s, %d channels)",
                dev.device_name, dev.device_gid, dev.model, len(dev.channels),
            )
    except Exception as e:
        logger.error("Failed to fetch devices: %s", e)
        publisher.disconnect()
        sys.exit(1)

    # Publish MQTT Discovery configs
    for dev in devices:
        for ch in dev.channels:
            publisher.publish_discovery(
                device_gid=dev.device_gid,
                device_name=dev.device_name,
                device_model=dev.model,
                channel_num=ch.channel_num,
                channel_name=ch.display_name,
                channel_slug=ch.slug,
            )
        if dev.usage_cent_per_kwh is not None:
            publisher.publish_energy_cost(
                device_gid=dev.device_gid,
                device_name=dev.device_name,
                device_model=dev.model,
                cost_cent_per_kwh=dev.usage_cent_per_kwh,
            )
    logger.info("MQTT Discovery configs published")

    # Main polling loop
    device_gids = [d.device_gid for d in devices]
    consecutive_failures = 0
    max_consecutive_failures = 10

    logger.info("Starting polling loop (interval=%ds)", POLL_INTERVAL)

    while not shutdown_requested:
        try:
            usages = api.get_usage(device_gids, scale="1MIN")
            daily_totals = api.get_daily_totals(device_gids)

            for usage in usages:
                # Find channel slug
                slug = None
                for dev in devices:
                    for ch in dev.channels:
                        if (
                            ch.device_gid == usage.device_gid
                            and ch.channel_num == usage.channel_num
                        ):
                            slug = ch.slug
                            break
                    if slug:
                        break

                if slug is None:
                    # Unknown channel (possibly nested device)
                    name = usage.name or usage.channel_num
                    slug = "".join(
                        c if c.isalnum() else "_" for c in name.lower()
                    ).strip("_") or f"ch_{usage.channel_num}"

                # Look up daily total for this channel
                total_kwh = daily_totals.get(
                    (usage.device_gid, usage.channel_num)
                )

                publisher.publish_usage(
                    device_gid=usage.device_gid,
                    channel_slug=slug,
                    watts=usage.watts,
                    usage_kwh=usage.usage_kwh,
                    total_kwh=total_kwh,
                    percentage=usage.percentage,
                )

            consecutive_failures = 0
            logger.debug("Published %d channel readings", len(usages))

        except Exception as e:
            consecutive_failures += 1
            logger.error(
                "Poll failed (%d/%d): %s",
                consecutive_failures, max_consecutive_failures, e,
            )
            if consecutive_failures >= max_consecutive_failures:
                logger.error("Too many consecutive failures, exiting")
                break

        # Sleep with jitter (avoid synchronized polling)
        jitter = random.uniform(-5, 5)
        sleep_time = max(10, POLL_INTERVAL + jitter)

        # Sleep in small increments to respond to shutdown quickly
        end_time = time.time() + sleep_time
        while time.time() < end_time and not shutdown_requested:
            time.sleep(1)

    # Graceful shutdown
    logger.info("Shutting down...")
    publisher.disconnect()
    logger.info("Goodbye")


if __name__ == "__main__":
    main()
