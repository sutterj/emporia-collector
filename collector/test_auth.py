"""
One-shot authentication test.

Verifies Emporia credentials work without starting the full collector.
Exits 0 on success, 1 on failure.
"""

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test_auth")


def main():
    email = os.environ.get("EMPORIA_EMAIL", "")
    password = os.environ.get("EMPORIA_PASSWORD", "")

    if not email or not password:
        logger.error("EMPORIA_EMAIL and EMPORIA_PASSWORD must be set")
        sys.exit(1)

    logger.info("Testing Emporia authentication for: %s", email)

    from cognito_srp import CognitoAuth
    from emporia_api import EmporiaAPI

    # Test authentication
    auth = CognitoAuth(email, password)
    try:
        auth.authenticate()
        logger.info("Authentication successful")
        logger.info("Token expires in ~55 minutes (refreshes automatically)")
    except Exception as e:
        logger.error("Authentication FAILED: %s", e)
        sys.exit(1)

    # Test device listing
    api = EmporiaAPI(auth)
    try:
        devices = api.get_devices()
        logger.info("Found %d device(s):", len(devices))
        for dev in devices:
            logger.info(
                "  %s (gid=%d, model=%s)",
                dev.device_name, dev.device_gid, dev.model,
            )
            for ch in dev.channels:
                logger.info("    Channel %s: %s", ch.channel_num, ch.display_name)
    except Exception as e:
        logger.error("Device fetch FAILED: %s", e)
        sys.exit(1)

    # Test a single usage poll
    try:
        gids = [d.device_gid for d in devices]
        usages = api.get_usage(gids)
        logger.info("Usage poll returned %d channel readings", len(usages))
        for u in usages[:5]:
            name = u.name or u.channel_num
            logger.info("  %s: %s W", name, u.watts)
        if len(usages) > 5:
            logger.info("  ... and %d more", len(usages) - 5)
    except Exception as e:
        logger.error("Usage poll FAILED: %s", e)
        sys.exit(1)

    logger.info("All tests passed.  Collector is ready to run.")
    sys.exit(0)


if __name__ == "__main__":
    main()
