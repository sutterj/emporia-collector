"""
Tests for emporia_api module.

Tests data parsing, slug generation, usage extraction, and API request logic.
"""

import json
import sys
import os
from unittest.mock import patch, MagicMock
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emporia_api import Channel, Device, ChannelUsage, EmporiaAPI


class TestChannel:
    """Test Channel dataclass and helpers."""

    def test_display_name_with_name(self):
        ch = Channel(device_gid=1, channel_num="3", name="Oven")
        assert ch.display_name == "Oven"

    def test_display_name_main(self):
        ch = Channel(device_gid=1, channel_num="1,2,3", name="")
        assert ch.display_name == "Main"

    def test_display_name_balance(self):
        ch = Channel(device_gid=1, channel_num="Balance", name="")
        assert ch.display_name == "Balance"

    def test_display_name_numbered(self):
        ch = Channel(device_gid=1, channel_num="5", name="")
        assert ch.display_name == "Circuit 5"

    def test_slug_simple(self):
        ch = Channel(device_gid=1, channel_num="1", name="Oven")
        assert ch.slug == "oven"

    def test_slug_with_spaces(self):
        ch = Channel(device_gid=1, channel_num="2", name="Living Room")
        assert ch.slug == "living_room"

    def test_slug_with_special_chars(self):
        ch = Channel(device_gid=1, channel_num="3", name="A/C Compressor")
        assert ch.slug == "a_c_compressor"

    def test_slug_main_channel(self):
        ch = Channel(device_gid=1, channel_num="1,2,3", name="")
        assert ch.slug == "main"

    def test_slug_balance(self):
        ch = Channel(device_gid=1, channel_num="Balance", name="")
        assert ch.slug == "balance"

    def test_default_multiplier(self):
        ch = Channel(device_gid=1, channel_num="1", name="Test")
        assert ch.multiplier == 1.0


class TestDevice:
    """Test Device dataclass."""

    def test_slug(self):
        dev = Device(
            device_gid=123,
            model="VUE003",
            device_name="My Home",
            time_zone="America/New_York",
        )
        assert dev.slug == "my_home"

    def test_slug_special_chars(self):
        dev = Device(
            device_gid=456,
            model="VUE003",
            device_name="Jake's House (Main)",
            time_zone="UTC",
        )
        assert dev.slug == "jake_s_house__main"


class TestChannelUsage:
    """Test ChannelUsage dataclass."""

    def test_with_values(self):
        usage = ChannelUsage(
            device_gid=1,
            channel_num="1,2,3",
            name="Main",
            usage_kwh=0.5,
            watts=500.0,
            percentage=100.0,
        )
        assert usage.watts == 500.0
        assert usage.usage_kwh == 0.5

    def test_with_none_usage(self):
        usage = ChannelUsage(
            device_gid=1,
            channel_num="5",
            name="Offline",
            usage_kwh=None,
            watts=None,
            percentage=0.0,
        )
        assert usage.watts is None


class TestEmporiaAPIGetDevices:
    """Test device list parsing."""

    def _make_api(self, mock_auth):
        mock_auth.ensure_valid_token.return_value = "fake-token"
        return EmporiaAPI(mock_auth)

    @patch("emporia_api.urllib.request.urlopen")
    def test_parses_device_list(self, mock_urlopen):
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        response_data = {
            "devices": [
                {
                    "deviceGid": 12345,
                    "model": "VUE003",
                    "firmware": "1.0.0",
                    "locationProperties": {
                        "deviceName": "Home Panel",
                        "timeZone": "America/New_York",
                    },
                    "channels": [
                        {
                            "deviceGid": 12345,
                            "channelNum": "1,2,3",
                            "name": None,
                            "channelMultiplier": 1.0,
                        },
                        {
                            "deviceGid": 12345,
                            "channelNum": "1",
                            "name": "Kitchen",
                            "channelMultiplier": 1.0,
                        },
                        {
                            "deviceGid": 12345,
                            "channelNum": "2",
                            "name": "Dryer",
                            "channelMultiplier": 2.0,
                        },
                    ],
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = EmporiaAPI(mock_auth)
        devices = api.get_devices()

        assert len(devices) == 1
        dev = devices[0]
        assert dev.device_gid == 12345
        assert dev.model == "VUE003"
        assert dev.device_name == "Home Panel"
        assert dev.time_zone == "America/New_York"
        assert len(dev.channels) == 3
        assert dev.channels[0].channel_num == "1,2,3"
        assert dev.channels[0].display_name == "Main"
        assert dev.channels[1].name == "Kitchen"
        assert dev.channels[2].multiplier == 2.0

    @patch("emporia_api.urllib.request.urlopen")
    def test_empty_device_list(self, mock_urlopen):
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"devices": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = EmporiaAPI(mock_auth)
        devices = api.get_devices()
        assert devices == []


class TestEmporiaAPIGetUsage:
    """Test usage data parsing and watt conversion."""

    @patch("emporia_api.urllib.request.urlopen")
    def test_converts_kwh_to_watts(self, mock_urlopen):
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        # At 1MIN scale: watts = kwh * 60 * 1000
        # So 0.1 kWh over 1 minute = 6000W
        response_data = {
            "deviceListUsages": {
                "instant": "2024-01-01T12:00:00Z",
                "scale": "1MIN",
                "energyUnit": "KilowattHours",
                "devices": [
                    {
                        "deviceGid": 100,
                        "channelUsages": [
                            {
                                "name": "Main",
                                "usage": 0.1,
                                "channelNum": "1,2,3",
                                "percentage": 100.0,
                                "nestedDevices": [],
                            },
                            {
                                "name": "Oven",
                                "usage": 0.05,
                                "channelNum": "1",
                                "percentage": 50.0,
                                "nestedDevices": [],
                            },
                        ],
                    }
                ],
            }
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = EmporiaAPI(mock_auth)
        usages = api.get_usage([100], scale="1MIN")

        assert len(usages) == 2
        # 0.1 kWh * 60 * 1000 = 6000W
        assert usages[0].watts == 6000.0
        assert usages[0].channel_num == "1,2,3"
        # 0.05 kWh * 60 * 1000 = 3000W
        assert usages[1].watts == 3000.0

    @patch("emporia_api.urllib.request.urlopen")
    def test_handles_null_usage(self, mock_urlopen):
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        response_data = {
            "deviceListUsages": {
                "instant": "2024-01-01T12:00:00Z",
                "scale": "1MIN",
                "energyUnit": "KilowattHours",
                "devices": [
                    {
                        "deviceGid": 100,
                        "channelUsages": [
                            {
                                "name": "Offline Circuit",
                                "usage": None,
                                "channelNum": "5",
                                "percentage": 0.0,
                                "nestedDevices": [],
                            },
                        ],
                    }
                ],
            }
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = EmporiaAPI(mock_auth)
        usages = api.get_usage([100])

        assert len(usages) == 1
        assert usages[0].watts is None
        assert usages[0].usage_kwh is None

    @patch("emporia_api.urllib.request.urlopen")
    def test_handles_nested_devices(self, mock_urlopen):
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        response_data = {
            "deviceListUsages": {
                "instant": "2024-01-01T12:00:00Z",
                "scale": "1MIN",
                "energyUnit": "KilowattHours",
                "devices": [
                    {
                        "deviceGid": 100,
                        "channelUsages": [
                            {
                                "name": "Main",
                                "usage": 0.2,
                                "channelNum": "1,2,3",
                                "percentage": 100.0,
                                "nestedDevices": [
                                    {
                                        "deviceGid": 200,
                                        "channelUsages": [
                                            {
                                                "name": "Smart Plug",
                                                "usage": 0.01,
                                                "channelNum": "1,2,3",
                                                "percentage": 5.0,
                                                "nestedDevices": [],
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = EmporiaAPI(mock_auth)
        usages = api.get_usage([100])

        # Should have main + nested smart plug
        assert len(usages) == 2
        assert usages[0].device_gid == 100
        assert usages[1].device_gid == 200
        assert usages[1].name == "Smart Plug"
        assert usages[1].watts == 600.0  # 0.01 * 60 * 1000

    @patch("emporia_api.urllib.request.urlopen")
    def test_1s_scale_conversion(self, mock_urlopen):
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        response_data = {
            "deviceListUsages": {
                "instant": "2024-01-01T12:00:00Z",
                "scale": "1S",
                "energyUnit": "KilowattHours",
                "devices": [
                    {
                        "deviceGid": 100,
                        "channelUsages": [
                            {
                                "name": "Main",
                                "usage": 0.001,
                                "channelNum": "1,2,3",
                                "percentage": 100.0,
                                "nestedDevices": [],
                            },
                        ],
                    }
                ],
            }
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = EmporiaAPI(mock_auth)
        usages = api.get_usage([100], scale="1S")

        # 0.001 kWh * 3600 * 1000 = 3600W
        assert usages[0].watts == 3600.0


class TestEmporiaAPIGetDailyTotals:
    """Test daily energy total fetching."""

    @patch("emporia_api.urllib.request.urlopen")
    def test_returns_daily_kwh(self, mock_urlopen):
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        response_data = {
            "deviceListUsages": {
                "instant": "2024-01-01T12:00:00Z",
                "scale": "1D",
                "energyUnit": "KilowattHours",
                "devices": [
                    {
                        "deviceGid": 100,
                        "channelUsages": [
                            {
                                "name": "Main",
                                "usage": 25.678,
                                "channelNum": "1,2,3",
                                "percentage": 100.0,
                                "nestedDevices": [],
                            },
                            {
                                "name": "Dryer",
                                "usage": 3.456,
                                "channelNum": "2",
                                "percentage": 13.5,
                                "nestedDevices": [],
                            },
                        ],
                    }
                ],
            }
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = EmporiaAPI(mock_auth)
        totals = api.get_daily_totals([100])

        assert totals[(100, "1,2,3")] == 25.678
        assert totals[(100, "2")] == 3.456

    @patch("emporia_api.urllib.request.urlopen")
    def test_handles_null_usage(self, mock_urlopen):
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        response_data = {
            "deviceListUsages": {
                "instant": "2024-01-01T12:00:00Z",
                "scale": "1D",
                "energyUnit": "KilowattHours",
                "devices": [
                    {
                        "deviceGid": 100,
                        "channelUsages": [
                            {
                                "name": "Offline",
                                "usage": None,
                                "channelNum": "5",
                                "percentage": 0.0,
                                "nestedDevices": [],
                            },
                        ],
                    }
                ],
            }
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = EmporiaAPI(mock_auth)
        totals = api.get_daily_totals([100])

        # Null usage should not appear in totals
        assert (100, "5") not in totals


class TestEmporiaAPIRetry:
    """Test retry and error handling logic."""

    @patch("emporia_api.urllib.request.urlopen")
    @patch("emporia_api.time.sleep")
    def test_retries_on_server_error(self, mock_sleep, mock_urlopen):
        import urllib.error
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "token"

        # First call: 500 error, second call: success
        error = urllib.error.HTTPError("url", 500, "ISE", {}, MagicMock())
        error.read = MagicMock(return_value=b"error")

        success_resp = MagicMock()
        success_resp.read.return_value = json.dumps({"devices": []}).encode()
        success_resp.__enter__ = lambda s: s
        success_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [error, success_resp]

        api = EmporiaAPI(mock_auth)
        devices = api.get_devices()
        assert devices == []
        assert mock_sleep.called

    @patch("emporia_api.urllib.request.urlopen")
    def test_refreshes_token_on_401(self, mock_urlopen):
        import urllib.error
        mock_auth = MagicMock()
        mock_auth.ensure_valid_token.return_value = "new-token"

        error = urllib.error.HTTPError("url", 401, "Unauth", {}, MagicMock())
        error.read = MagicMock(return_value=b"expired")

        success_resp = MagicMock()
        success_resp.read.return_value = json.dumps({"devices": []}).encode()
        success_resp.__enter__ = lambda s: s
        success_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [error, success_resp]

        api = EmporiaAPI(mock_auth)
        devices = api.get_devices()
        assert devices == []
        # ensure_valid_token called twice (initial + after 401)
        assert mock_auth.ensure_valid_token.call_count == 2
