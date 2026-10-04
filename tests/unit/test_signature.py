"""HMAC signature verifier."""

from __future__ import annotations

import pytest

from webhook_relay.errors import SignatureError
from webhook_relay.security.signature import (
    HmacSha256Verifier,
    build_signature_header,
    compute_signature,
    parse_signature_header,
)

SECRET = "super-secret"
BODY = b'{"event_id": "evt_1", "amount": 10}'
NOW = 1_800_000_000


@pytest.fixture
def verifier() -> HmacSha256Verifier:
    return HmacSha256Verifier(SECRET, tolerance_seconds=300)


def test_valid_signature_passes(verifier: HmacSha256Verifier) -> None:
    headers = {"X-Signature": build_signature_header(SECRET, BODY, timestamp=NOW)}
    verifier.verify(BODY, headers, now=NOW + 10)


def test_header_lookup_is_case_insensitive(verifier: HmacSha256Verifier) -> None:
    headers = {"x-signature": build_signature_header(SECRET, BODY, timestamp=NOW)}
    verifier.verify(BODY, headers, now=NOW)


def test_wrong_secret_is_rejected(verifier: HmacSha256Verifier) -> None:
    headers = {"X-Signature": build_signature_header("other-secret", BODY, timestamp=NOW)}
    with pytest.raises(SignatureError, match="mismatch"):
        verifier.verify(BODY, headers, now=NOW)


def test_tampered_body_is_rejected(verifier: HmacSha256Verifier) -> None:
    headers = {"X-Signature": build_signature_header(SECRET, BODY, timestamp=NOW)}
    with pytest.raises(SignatureError, match="mismatch"):
        verifier.verify(BODY.replace(b"10", b"99"), headers, now=NOW)


@pytest.mark.parametrize("skew", [301, -301, 3600])
def test_timestamp_outside_tolerance_is_rejected(verifier: HmacSha256Verifier, skew: int) -> None:
    headers = {"X-Signature": build_signature_header(SECRET, BODY, timestamp=NOW)}
    with pytest.raises(SignatureError, match="tolerance"):
        verifier.verify(BODY, headers, now=NOW + skew)


def test_timestamp_at_tolerance_boundary_passes(verifier: HmacSha256Verifier) -> None:
    headers = {"X-Signature": build_signature_header(SECRET, BODY, timestamp=NOW)}
    verifier.verify(BODY, headers, now=NOW + 300)


def test_replaying_old_signature_with_new_timestamp_fails(verifier: HmacSha256Verifier) -> None:
    old_sig = compute_signature(SECRET, NOW - 10_000, BODY)
    headers = {"X-Signature": f"t={NOW},v1={old_sig}"}
    with pytest.raises(SignatureError, match="mismatch"):
        verifier.verify(BODY, headers, now=NOW)


def test_missing_header_is_rejected(verifier: HmacSha256Verifier) -> None:
    with pytest.raises(SignatureError, match="missing"):
        verifier.verify(BODY, {}, now=NOW)


@pytest.mark.parametrize(
    "value",
    ["", "garbage", "t=abc,v1=00", "v1=00", f"t={NOW}", f"t={NOW},v2=00"],
)
def test_malformed_header_is_rejected(verifier: HmacSha256Verifier, value: str) -> None:
    with pytest.raises(SignatureError):
        verifier.verify(BODY, {"X-Signature": value}, now=NOW)


def test_multiple_signatures_support_secret_rotation(verifier: HmacSha256Verifier) -> None:
    good = compute_signature(SECRET, NOW, BODY)
    stale = compute_signature("retired-secret", NOW, BODY)
    headers = {"X-Signature": f"t={NOW},v1={stale},v1={good}"}
    verifier.verify(BODY, headers, now=NOW)


def test_parse_signature_header() -> None:
    parsed = parse_signature_header(f"t={NOW}, v1=ABCDEF, v1=123456")
    assert parsed.timestamp == NOW
    assert parsed.signatures == ("abcdef", "123456")


def test_signature_uses_real_time_when_now_not_given(verifier: HmacSha256Verifier) -> None:
    headers = {"X-Signature": build_signature_header(SECRET, BODY)}
    verifier.verify(BODY, headers)


def test_empty_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        HmacSha256Verifier("")


def test_compute_signature_is_deterministic_hex() -> None:
    sig = compute_signature(SECRET, NOW, BODY)
    assert sig == compute_signature(SECRET, NOW, BODY)
    assert len(sig) == 64
    int(sig, 16)
