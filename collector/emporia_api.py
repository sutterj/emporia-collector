"""
Emporia Vue API client.

Talks to https://api.emporiaenergy.com using only urllib (stdlib).
No requests library, no PyEmVue.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cognito_srp import CognitoAuth

logger = logging.getLogger(__name__)

API_BASE = "https://api.emporiaenergy.com"

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0


@dataclass
class Channel:
    """A single circuit/channel on a Vue device."""
    device_gid: int
    channel_num: str
    name: str
    multiplier: float = 1.0

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.channel_num == "1,2,3":
            return "Main"
        if self.channel_num == "Balance":
            return "Balance"
        return f"Circuit {self.channel_num}"

    @property
    def slug(self) -> str:
        """URL/topic-safe identifier."""
        name = self.display_name.lower()
        # Replace non-alphanumeric with underscore
        return "".join(c if c.isalnum() else "_" for c in name).strip("_")


@dataclass
class Device:
    """An Emporia Vue device."""
    device_gid: int
    model: str
    device_name: str
    time_zone: str
    usage_cent_per_kwh: float | None = None
    channels: list[Channel] = field(default_factory=list)

    @property
    def slug(self) -> str:
        name = self.device_name.lower()
        return "".join(c if c.isalnum() else "_" for c in name).strip("_")


@dataclass
class ChannelUsage:
    """Usage reading for a single channel."""
    device_gid: int
    channel_num: str
    name: str
    usage_kwh: float | None
    watts: float | None
    percentage: float


class EmporiaAPI:
    """Minimal Emporia Vue API client."""

    def __init__(self, auth: CognitoAuth):
        self._auth = auth
        self._devices: list[Device] | None = None

    def _request(self, path: str, params: dict | None = None) -> dict | list:
        """Make authenticated GET request to Emporia API."""
        token = self._auth.ensure_valid_token()

        url = f"{API_BASE}/{path}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(
                url,
                headers={"authtoken": token},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    # Token may have expired server-side; force refresh
                    logger.warning("Got 401, refreshing token")
                    token = self._auth.ensure_valid_token()
                    continue
                if e.code >= 500:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning(
                        "Server error %d, retrying in %.1fs", e.code, wait
                    )
                    time.sleep(wait)
                    continue
                body = e.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Emporia API error ({e.code}): {body}"
                ) from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning(
                        "Network error: %s, retrying in %.1fs", e, wait
                    )
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError("Max retries exceeded")

    def get_devices(self) -> list[Device]:
        """Fetch and cache the device list with channels."""
        data = self._request("customers/devices")
        devices = []

        for dev_data in data.get("devices", []):
            gid = dev_data["deviceGid"]

            # Get location properties for device name
            loc = dev_data.get("locationProperties", {})
            device_name = loc.get("deviceName", f"Vue {gid}")
            time_zone = loc.get("timeZone", "UTC")
            usage_cent_per_kwh = loc.get("usageCentPerKwHour")

            channels = []

            # Top-level channels (Main "1,2,3")
            for ch_data in dev_data.get("channels", []):
                channels.append(Channel(
                    device_gid=ch_data["deviceGid"],
                    channel_num=ch_data["channelNum"],
                    name=ch_data.get("name") or "",
                    multiplier=ch_data.get("channelMultiplier", 1.0),
                ))

            # Nested sub-device channels (individual circuits)
            # Vue Gen 3 puts branch circuits under devices[].devices[].channels
            for sub_dev in dev_data.get("devices", []):
                for ch_data in sub_dev.get("channels", []):
                    # Skip individual legs of merged 240V circuits
                    # (they have parentChannelNum set, indicating they roll up
                    # into a merged channel like "Air Conditioner" or "Dryer")
                    if ch_data.get("parentChannelNum"):
                        continue

                    channels.append(Channel(
                        device_gid=ch_data["deviceGid"],
                        channel_num=ch_data["channelNum"],
                        name=ch_data.get("name") or "",
                        multiplier=ch_data.get("channelMultiplier", 1.0),
                    ))

            devices.append(Device(
                device_gid=gid,
                model=dev_data.get("model", ""),
                device_name=device_name,
                time_zone=time_zone,
                usage_cent_per_kwh=usage_cent_per_kwh,
                channels=channels,
            ))

        self._devices = devices
        return devices

    def get_usage(
        self,
        device_gids: list[int],
        scale: str = "1MIN",
    ) -> list[ChannelUsage]:
        """
        Fetch real-time usage for all channels on specified devices.

        Returns usage in watts (converted from kWh at the given scale).
        """
        gids_str = "+".join(str(g) for g in device_gids)
        instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Scale multiplier to convert kWh to kW
        scale_multipliers = {
            "1S": 3600.0,
            "1MIN": 60.0,
            "15MIN": 4.0,
            "1H": 1.0,
        }
        kw_multiplier = scale_multipliers.get(scale, 60.0)

        data = self._request("AppAPI", {
            "apiMethod": "getDeviceListUsages",
            "deviceGids": gids_str,
            "instant": instant,
            "scale": scale,
            "energyUnit": "KilowattHours",
        })

        usages = []
        device_list = data.get("deviceListUsages", {}).get("devices", [])

        for device_data in device_list:
            self._extract_channel_usages(
                device_data, kw_multiplier, usages
            )

        return usages

    def _extract_channel_usages(
        self,
        device_data: dict,
        kw_multiplier: float,
        usages: list[ChannelUsage],
    ) -> None:
        """Recursively extract channel usages including nested devices."""
        device_gid = device_data.get("deviceGid", 0)

        for ch in device_data.get("channelUsages", []):
            usage_kwh = ch.get("usage")
            watts = None
            if usage_kwh is not None:
                # Convert kWh to watts: kWh * scale_mult * 1000
                watts = round(usage_kwh * kw_multiplier * 1000, 1)

            usages.append(ChannelUsage(
                device_gid=device_gid,
                channel_num=ch.get("channelNum", ""),
                name=ch.get("name") or "",
                usage_kwh=usage_kwh,
                watts=watts,
                percentage=ch.get("percentage", 0.0),
            ))

            # Handle nested devices (smart plugs, utility connect)
            for nested in ch.get("nestedDevices", []):
                self._extract_channel_usages(nested, kw_multiplier, usages)

    def get_daily_totals(
        self,
        device_gids: list[int],
    ) -> dict[tuple[int, str], float]:
        """
        Fetch today's cumulative energy usage per channel.

        Uses scale=1D which returns total kWh consumed since midnight
        in the device's local timezone.

        Returns dict mapping (device_gid, channel_num) -> total_kwh.
        """
        gids_str = "+".join(str(g) for g in device_gids)
        instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        data = self._request("AppAPI", {
            "apiMethod": "getDeviceListUsages",
            "deviceGids": gids_str,
            "instant": instant,
            "scale": "1D",
            "energyUnit": "KilowattHours",
        })

        totals: dict[tuple[int, str], float] = {}
        device_list = data.get("deviceListUsages", {}).get("devices", [])

        for device_data in device_list:
            self._extract_daily_totals(device_data, totals)

        return totals

    def _extract_daily_totals(
        self,
        device_data: dict,
        totals: dict[tuple[int, str], float],
    ) -> None:
        """Recursively extract daily kWh totals."""
        device_gid = device_data.get("deviceGid", 0)

        for ch in device_data.get("channelUsages", []):
            usage = ch.get("usage")
            if usage is not None:
                channel_num = ch.get("channelNum", "")
                totals[(device_gid, channel_num)] = round(usage, 4)

            for nested in ch.get("nestedDevices", []):
                self._extract_daily_totals(nested, totals)
