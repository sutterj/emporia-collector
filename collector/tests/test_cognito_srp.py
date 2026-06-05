"""
Tests for cognito_srp module.

Validates SRP helper functions against known values from pycognito's
test suite and AWS Cognito's documented behavior.
"""

import base64
import hashlib
import hmac
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognito_srp import (
    N, G, N_HEX, CLIENT_ID, USER_POOL_ID, POOL_NAME,
    _pad_hex, _hash_sha256, _hex_hash, _compute_hkdf,
    _calculate_u, _generate_srp_a, _format_timestamp,
    _get_password_authentication_key, _cognito_request,
    CognitoAuth, INFO_BITS,
)
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import json


class TestPadHex:
    """Test _pad_hex matches pycognito's pad_hex behavior."""

    def test_even_length_no_high_nibble(self):
        # 0x1a -> "1a" (even length, first nibble < 8)
        assert _pad_hex(0x1a) == "1a"

    def test_odd_length_padded(self):
        # 0xf -> "0f" (odd length gets zero-padded)
        assert _pad_hex(0xf) == "0f"

    def test_high_nibble_gets_leading_zeros(self):
        # 0x8a -> "008a" (first nibble >= 8 gets "00" prefix)
        assert _pad_hex(0x8a) == "008a"

    def test_high_nibble_a(self):
        # 0xab -> "00ab"
        assert _pad_hex(0xab) == "00ab"

    def test_zero(self):
        assert _pad_hex(0) == "00"

    def test_one(self):
        assert _pad_hex(1) == "01"

    def test_large_number(self):
        result = _pad_hex(0x7fffffffffffff)
        assert result == "7fffffffffffff"
        assert len(result) % 2 == 0

    def test_large_number_high_nibble(self):
        result = _pad_hex(0x8000000000000000)
        assert result.startswith("00")
        assert len(result) % 2 == 0

    def test_string_input_even(self):
        assert _pad_hex("1a2b") == "1a2b"

    def test_string_input_odd(self):
        assert _pad_hex("abc") == "0abc"

    def test_string_input_high_nibble(self):
        assert _pad_hex("9abc") == "009abc"


class TestHashSha256:
    """Test _hash_sha256 returns zero-padded 64-char hex."""

    def test_known_value(self):
        result = _hash_sha256(b"hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert result == expected
        assert len(result) == 64

    def test_empty_input(self):
        result = _hash_sha256(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected

    def test_always_64_chars(self):
        # Even if hash starts with zeros, should be padded
        for i in range(100):
            result = _hash_sha256(f"test{i}".encode())
            assert len(result) == 64


class TestHexHash:
    """Test _hex_hash (SHA256 of hex-decoded input)."""

    def test_known_value(self):
        # hex "68656c6c6f" = "hello"
        result = _hex_hash("68656c6c6f")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert result == expected

    def test_empty_hex(self):
        result = _hex_hash("")
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected


class TestComputeHkdf:
    """Test HKDF implementation matches pycognito's compute_hkdf."""

    def test_output_length(self):
        ikm = bytearray(b"\x01" * 32)
        salt = bytearray(b"\x02" * 32)
        result = _compute_hkdf(ikm, salt)
        assert len(result) == 16

    def test_deterministic(self):
        ikm = bytearray(b"input key material")
        salt = bytearray(b"salt value here!")
        result1 = _compute_hkdf(ikm, salt)
        result2 = _compute_hkdf(ikm, salt)
        assert result1 == result2

    def test_different_inputs_different_outputs(self):
        salt = bytearray(b"same salt")
        result1 = _compute_hkdf(bytearray(b"ikm1"), salt)
        result2 = _compute_hkdf(bytearray(b"ikm2"), salt)
        assert result1 != result2

    def test_matches_manual_computation(self):
        ikm = bytearray(b"test ikm")
        salt = bytearray(b"test salt")
        # Manual HKDF extract
        prk = hmac.new(bytes(salt), bytes(ikm), hashlib.sha256).digest()
        # Manual HKDF expand
        info_bits = INFO_BITS + bytearray(chr(1), "utf-8")
        expected = hmac.new(prk, bytes(info_bits), hashlib.sha256).digest()[:16]
        assert _compute_hkdf(ikm, salt) == expected


class TestCalculateU:
    """Test _calculate_u (u = H(pad(A) || pad(B)))."""

    def test_nonzero_for_typical_values(self):
        # Use relatively small values for testing
        big_a = pow(G, 42, N)
        big_b = pow(G, 99, N)
        u = _calculate_u(big_a, big_b)
        assert u != 0
        assert isinstance(u, int)

    def test_deterministic(self):
        big_a = pow(G, 123, N)
        big_b = pow(G, 456, N)
        assert _calculate_u(big_a, big_b) == _calculate_u(big_a, big_b)

    def test_order_matters(self):
        big_a = pow(G, 10, N)
        big_b = pow(G, 20, N)
        assert _calculate_u(big_a, big_b) != _calculate_u(big_b, big_a)


class TestGenerateSrpA:
    """Test SRP key pair generation."""

    def test_returns_tuple(self):
        a, big_a = _generate_srp_a()
        assert isinstance(a, int)
        assert isinstance(big_a, int)

    def test_big_a_is_g_pow_a_mod_n(self):
        a, big_a = _generate_srp_a()
        assert big_a == pow(G, a, N)

    def test_big_a_not_zero_mod_n(self):
        # Safety check: A % N != 0
        for _ in range(10):
            _, big_a = _generate_srp_a()
            assert big_a % N != 0

    def test_randomness(self):
        # Two calls should produce different values
        a1, _ = _generate_srp_a()
        a2, _ = _generate_srp_a()
        assert a1 != a2


class TestFormatTimestamp:
    """Test timestamp formatting matches Cognito expectations."""

    def test_format_known_date(self):
        # Wednesday, February 9, 2022 at 21:18:50 UTC
        dt = datetime(2022, 2, 9, 21, 18, 50, tzinfo=timezone.utc)
        result = _format_timestamp(dt)
        assert result == "Wed Feb 9 21:18:50 UTC 2022"

    def test_no_leading_zero_on_day(self):
        dt = datetime(2023, 1, 5, 8, 5, 3, tzinfo=timezone.utc)
        result = _format_timestamp(dt)
        assert result == "Thu Jan 5 08:05:03 UTC 2023"

    def test_double_digit_day(self):
        dt = datetime(2023, 12, 25, 14, 30, 0, tzinfo=timezone.utc)
        result = _format_timestamp(dt)
        assert result == "Mon Dec 25 14:30:00 UTC 2023"

    def test_all_weekdays(self):
        # 2023-01-02 is Monday, check the whole week
        expected_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, day_name in enumerate(expected_days):
            dt = datetime(2023, 1, 2 + i, 12, 0, 0, tzinfo=timezone.utc)
            result = _format_timestamp(dt)
            assert result.startswith(day_name), f"Day {2+i} should be {day_name}"


class TestGetPasswordAuthenticationKey:
    """Test the full password-to-HKDF-key derivation."""

    def test_deterministic_with_fixed_inputs(self):
        # Use fixed values to verify deterministic behavior
        big_a = pow(G, 12345, N)
        big_b = pow(G, 67890, N)
        small_a = 12345
        salt_hex = "abcdef1234567890"

        key1 = _get_password_authentication_key(
            "testPool", "user@test.com", "password123",
            big_a, big_b, small_a, salt_hex,
        )
        key2 = _get_password_authentication_key(
            "testPool", "user@test.com", "password123",
            big_a, big_b, small_a, salt_hex,
        )
        assert key1 == key2
        assert len(key1) == 16

    def test_different_password_different_key(self):
        big_a = pow(G, 111, N)
        big_b = pow(G, 222, N)
        small_a = 111
        salt_hex = "aabbccdd"

        key1 = _get_password_authentication_key(
            "pool", "user", "pass1", big_a, big_b, small_a, salt_hex,
        )
        key2 = _get_password_authentication_key(
            "pool", "user", "pass2", big_a, big_b, small_a, salt_hex,
        )
        assert key1 != key2

    def test_raises_on_u_zero(self):
        # This is extremely unlikely with real values, but we can test
        # the safety check by mocking _calculate_u
        with patch("cognito_srp._calculate_u", return_value=0):
            import pytest
            with pytest.raises(ValueError, match="u == 0"):
                _get_password_authentication_key(
                    "pool", "user", "pass",
                    pow(G, 1, N), pow(G, 2, N), 1, "aa",
                )


class TestCognitoConstants:
    """Verify Emporia-specific constants are correct."""

    def test_client_id(self):
        assert CLIENT_ID == "4qte47jbstod8apnfic0bunmrq"

    def test_user_pool_id(self):
        assert USER_POOL_ID == "us-east-2_ghlOXVLi1"

    def test_pool_name_extracted(self):
        assert POOL_NAME == "ghlOXVLi1"

    def test_n_is_3072_bit(self):
        assert N.bit_length() == 3072

    def test_g_is_2(self):
        assert G == 2


class TestCognitoRequest:
    """Test the HTTP request helper."""

    @patch("cognito_srp.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"result": "ok"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _cognito_request("InitiateAuth", {"key": "value"})
        assert result == {"result": "ok"}

        # Verify correct headers
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.get_header("Content-type") == "application/x-amz-json-1.1"
        assert req.get_header("X-amz-target") == (
            "AWSCognitoIdentityProviderService.InitiateAuth"
        )

    @patch("cognito_srp.urllib.request.urlopen")
    def test_http_error_raises(self, mock_urlopen):
        import urllib.error
        import pytest

        error = urllib.error.HTTPError(
            "url", 400, "Bad Request", {}, MagicMock()
        )
        error.read = MagicMock(return_value=b"error body")
        mock_urlopen.side_effect = error

        with pytest.raises(RuntimeError, match="Cognito InitiateAuth failed"):
            _cognito_request("InitiateAuth", {})


class TestCognitoAuth:
    """Test the CognitoAuth class."""

    def test_init_not_authenticated(self):
        auth = CognitoAuth("user@test.com", "password")
        assert not auth.is_authenticated
        assert auth.id_token is None

    @patch("cognito_srp._cognito_request")
    def test_authenticate_success(self, mock_request):
        # Mock InitiateAuth response
        mock_request.side_effect = [
            {
                "ChallengeName": "PASSWORD_VERIFIER",
                "ChallengeParameters": {
                    "USERNAME": "user@test.com",
                    "USER_ID_FOR_SRP": "user-uuid",
                    "SALT": "abcdef1234567890",
                    "SRP_B": format(pow(G, 999, N), "x"),
                    "SECRET_BLOCK": base64.b64encode(b"secret").decode(),
                },
            },
            {
                "AuthenticationResult": {
                    "IdToken": "id-token-value",
                    "AccessToken": "access-token-value",
                    "RefreshToken": "refresh-token-value",
                    "ExpiresIn": 3600,
                },
            },
        ]

        auth = CognitoAuth("user@test.com", "password")
        auth.authenticate()

        assert auth.is_authenticated
        assert auth.id_token == "id-token-value"
        assert auth.access_token == "access-token-value"
        assert auth.refresh_token == "refresh-token-value"

    @patch("cognito_srp._cognito_request")
    def test_authenticate_unexpected_challenge(self, mock_request):
        import pytest

        mock_request.return_value = {
            "ChallengeName": "NEW_PASSWORD_REQUIRED",
            "ChallengeParameters": {},
        }

        auth = CognitoAuth("user@test.com", "password")
        with pytest.raises(RuntimeError, match="Unexpected challenge"):
            auth.authenticate()

    @patch("cognito_srp._cognito_request")
    def test_refresh_tokens(self, mock_request):
        mock_request.return_value = {
            "AuthenticationResult": {
                "IdToken": "new-id-token",
                "AccessToken": "new-access-token",
                "ExpiresIn": 3600,
            },
        }

        auth = CognitoAuth("user@test.com", "password")
        auth.id_token = "old-id"
        auth.access_token = "old-access"
        auth.refresh_token = "my-refresh-token"
        auth._token_expiry = 0  # Force expired

        auth.refresh_tokens()

        assert auth.id_token == "new-id-token"
        assert auth.access_token == "new-access-token"
        # Refresh token unchanged (not returned in response)
        assert auth.refresh_token == "my-refresh-token"

    @patch("cognito_srp._cognito_request")
    def test_ensure_valid_token_triggers_auth(self, mock_request):
        mock_request.side_effect = [
            {
                "ChallengeName": "PASSWORD_VERIFIER",
                "ChallengeParameters": {
                    "USERNAME": "u",
                    "USER_ID_FOR_SRP": "u",
                    "SALT": "aa",
                    "SRP_B": format(pow(G, 50, N), "x"),
                    "SECRET_BLOCK": base64.b64encode(b"s").decode(),
                },
            },
            {
                "AuthenticationResult": {
                    "IdToken": "fresh-token",
                    "AccessToken": "acc",
                    "RefreshToken": "ref",
                    "ExpiresIn": 3600,
                },
            },
        ]

        auth = CognitoAuth("u", "p")
        token = auth.ensure_valid_token()
        assert token == "fresh-token"

    def test_ensure_valid_token_returns_cached(self):
        import time
        auth = CognitoAuth("u", "p")
        auth.id_token = "cached-token"
        auth._token_expiry = time.time() + 9999

        token = auth.ensure_valid_token()
        assert token == "cached-token"
