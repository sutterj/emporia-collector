"""
AWS Cognito SRP (Secure Remote Password) authentication.

Implements USER_SRP_AUTH flow using only Python stdlib.
No boto3, no pycognito, no external crypto libraries.

The SRP math and helper functions are modeled directly on
NabuCasa/pycognito's aws_srp.py to ensure byte-for-byte
compatibility with Cognito's expectations.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


# Cognito SRP-3072 parameters
# https://github.com/aws/amazon-cognito-identity-js/blob/master/src/AuthenticationHelper.js#L22
N_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64"
    "ECFB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7"
    "ABF5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6B"
    "F12FFA06D98A0864D87602733EC86A64521F2B18177B200C"
    "BBE117577A615D6C770988C0BAD946E208E24FA074E5AB31"
    "43DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF"
)
G_HEX = "2"
N = int(N_HEX, 16)
G = 2

INFO_BITS = bytearray("Caldera Derived Key", "utf-8")

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Emporia-specific Cognito constants
CLIENT_ID = "4qte47jbstod8apnfic0bunmrq"
USER_POOL_ID = "us-east-2_ghlOXVLi1"
REGION = "us-east-2"
COGNITO_URL = f"https://cognito-idp.{REGION}.amazonaws.com/"
POOL_NAME = USER_POOL_ID.split("_", 1)[1]


# ── Helper functions (matching pycognito's implementations exactly) ──────────


def _hash_sha256(buf: bytes) -> str:
    """SHA256 hash, returned as zero-padded 64-char hex string."""
    # codeql [py/weak-sensitive-data-hashing] Suppress: SHA256 is required by the SRP-6a protocol (AWS Cognito). This is a cryptographic handshake, not password storage.
    value = hashlib.sha256(buf).hexdigest()
    return (64 - len(value)) * "0" + value


def _hex_hash(hex_string: str) -> str:
    """SHA256 of hex-encoded data, returned as padded hex string."""
    return _hash_sha256(bytearray.fromhex(hex_string))


def _pad_hex(long_int) -> str:
    """
    Convert integer (or hex string) to even-length hex, prepending "00"
    if the first nibble >= 8 (to prevent sign-extension in SRP math).
    """
    if not isinstance(long_int, str):
        hash_str = f"{long_int:x}"
    else:
        hash_str = long_int
    if len(hash_str) % 2 == 1:
        hash_str = f"0{hash_str}"
    elif hash_str[0] in "89ABCDEFabcdef":
        hash_str = f"00{hash_str}"
    return hash_str


def _compute_hkdf(ikm: bytearray, salt: bytearray) -> bytes:
    """HKDF extract-and-expand (single 16-byte block) for Cognito."""
    prk = hmac.new(bytes(salt), bytes(ikm), hashlib.sha256).digest()
    info_bits_update = INFO_BITS + bytearray(chr(1), "utf-8")
    hmac_hash = hmac.new(prk, bytes(info_bits_update), hashlib.sha256).digest()
    return hmac_hash[:16]


def _calculate_u(big_a: int, big_b: int) -> int:
    """u = H(pad(A) || pad(B))"""
    u_hex_hash = _hex_hash(_pad_hex(big_a) + _pad_hex(big_b))
    return int(u_hex_hash, 16)


def _generate_srp_a() -> tuple[int, int]:
    """Generate random private 'a' and public 'A = g^a mod N'."""
    while True:
        random_hex = binascii.hexlify(os.urandom(128))
        a = int(random_hex, 16)
        big_a = pow(G, a, N)
        if big_a % N != 0:
            return a, big_a


def _get_password_authentication_key(
    pool_name: str,
    username: str,
    password: str,
    big_a: int,
    big_b: int,
    small_a: int,
    salt_hex: str,
) -> bytes:
    """Compute the HKDF key used for signing the auth challenge response."""
    u_value = _calculate_u(big_a, big_b)
    if u_value == 0:
        raise ValueError("SRP safety check: u == 0")

    username_password = f"{pool_name}{username}:{password}"
    username_password_hash = _hash_sha256(username_password.encode("utf-8"))

    x_value = int(_hex_hash(_pad_hex(salt_hex) + username_password_hash), 16)
    g_mod_pow_xn = pow(G, x_value, N)
    # k = H(N || g) per SRP spec
    k_hex_hash = _hex_hash(
        _pad_hex(N) + _pad_hex(G)
    )
    k = int(k_hex_hash, 16)

    int_value2 = big_b - k * g_mod_pow_xn
    s_value = pow(int_value2, small_a + u_value * x_value, N)

    hkdf = _compute_hkdf(
        bytearray.fromhex(_pad_hex(s_value)),
        bytearray.fromhex(_pad_hex(u_value)),
    )
    return hkdf


def _format_timestamp(dt: datetime) -> str:
    """
    Format timestamp exactly as Cognito expects.
    Example: 'Wed Feb 9 21:18:50 UTC 2021'
    """
    return (
        f"{WEEKDAY_NAMES[dt.weekday()]} {MONTH_NAMES[dt.month - 1]} "
        f"{dt.day:d} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} UTC {dt.year:d}"
    )


def _cognito_request(target: str, payload: dict) -> dict:
    """Make a request to the Cognito IDP endpoint."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        COGNITO_URL,
        data=data,
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": f"AWSCognitoIdentityProviderService.{target}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Cognito {target} failed ({e.code}): {body}"
        ) from e


class CognitoAuth:
    """Handles AWS Cognito SRP authentication for Emporia."""

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self.id_token: str | None = None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._token_expiry: float = 0

    def authenticate(self) -> None:
        """Perform full SRP authentication flow."""
        small_a, big_a = _generate_srp_a()

        # Step 1: InitiateAuth with SRP_A
        init_resp = _cognito_request("InitiateAuth", {
            "AuthFlow": "USER_SRP_AUTH",
            "ClientId": CLIENT_ID,
            "AuthParameters": {
                "USERNAME": self._username,
                "SRP_A": format(big_a, "x"),
            },
        })

        if init_resp.get("ChallengeName") != "PASSWORD_VERIFIER":
            raise RuntimeError(
                f"Unexpected challenge: {init_resp.get('ChallengeName')}"
            )

        params = init_resp["ChallengeParameters"]
        internal_username = params.get("USERNAME", self._username)
        user_id_for_srp = params["USER_ID_FOR_SRP"]
        salt_hex = params["SALT"]
        srp_b_hex = params["SRP_B"]
        secret_block_b64 = params["SECRET_BLOCK"]

        big_b = int(srp_b_hex, 16)
        if big_b % N == 0:
            raise ValueError("SRP safety check: B % N == 0")

        # Step 2: Compute HKDF key and signature
        now = datetime.now(timezone.utc)
        timestamp = _format_timestamp(now)

        hkdf_key = _get_password_authentication_key(
            POOL_NAME, user_id_for_srp, self._password,
            big_a, big_b, small_a, salt_hex,
        )

        secret_block_bytes = base64.standard_b64decode(secret_block_b64)
        msg = (
            bytearray(POOL_NAME, "utf-8")
            + bytearray(user_id_for_srp, "utf-8")
            + bytearray(secret_block_bytes)
            + bytearray(timestamp, "utf-8")
        )
        hmac_obj = hmac.new(hkdf_key, bytes(msg), digestmod=hashlib.sha256)
        signature = base64.standard_b64encode(hmac_obj.digest()).decode("utf-8")

        # Step 3: Respond to challenge
        challenge_resp = _cognito_request("RespondToAuthChallenge", {
            "ClientId": CLIENT_ID,
            "ChallengeName": "PASSWORD_VERIFIER",
            "ChallengeResponses": {
                "USERNAME": internal_username,
                "TIMESTAMP": timestamp,
                "PASSWORD_CLAIM_SECRET_BLOCK": secret_block_b64,
                "PASSWORD_CLAIM_SIGNATURE": signature,
            },
        })

        auth_result = challenge_resp.get("AuthenticationResult")
        if not auth_result:
            raise RuntimeError(
                f"Auth failed: {challenge_resp}"
            )

        self.id_token = auth_result["IdToken"]
        self.access_token = auth_result["AccessToken"]
        self.refresh_token = auth_result["RefreshToken"]
        self._token_expiry = time.time() + auth_result.get("ExpiresIn", 3600) - 300

    def refresh_tokens(self) -> None:
        """Refresh tokens using the refresh token."""
        resp = _cognito_request("InitiateAuth", {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": CLIENT_ID,
            "AuthParameters": {
                "REFRESH_TOKEN": self.refresh_token,
            },
        })

        auth_result = resp.get("AuthenticationResult")
        if not auth_result:
            raise RuntimeError(f"Token refresh failed: {resp}")

        self.id_token = auth_result["IdToken"]
        self.access_token = auth_result["AccessToken"]
        if "RefreshToken" in auth_result:
            self.refresh_token = auth_result["RefreshToken"]
        self._token_expiry = time.time() + auth_result.get("ExpiresIn", 3600) - 300

    def ensure_valid_token(self) -> str:
        """Return a valid id_token, refreshing if needed."""
        if self.id_token is None:
            self.authenticate()
        elif time.time() >= self._token_expiry:
            try:
                self.refresh_tokens()
            except Exception:
                self.authenticate()
        return self.id_token

    @property
    def is_authenticated(self) -> bool:
        return self.id_token is not None
