"""The sender script builds correctly signed requests (no server needed)."""

from __future__ import annotations

import argparse
import json

import httpx
import pytest
import respx
from scripts import send_test_webhook as script

from webhook_relay.security.signature import HmacSha256Verifier


def make_args(**overrides: object) -> argparse.Namespace:
    base = {
        "provider": "voice",
        "url": "http://relay.example.com/",
        "payload": None,
        "secret": None,
        "event_id": None,
        "random_event_id": False,
        "skew": 0,
        "tamper": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_build_request_signs_body_with_default_secret() -> None:
    url, body, headers = script.build_request(make_args())
    assert url == "http://relay.example.com/webhooks/voice/post-call"
    HmacSha256Verifier("demo-voice-secret").verify(body, headers)
    assert json.loads(body)["event_id"] == "evt_voice_0001"


def test_build_request_overrides_event_id_and_secret() -> None:
    _, body, headers = script.build_request(
        make_args(provider="chat", event_id="evt_custom", secret="my-secret")
    )
    HmacSha256Verifier("my-secret").verify(body, headers)
    assert json.loads(body)["event_id"] == "evt_custom"


def test_random_event_id_changes_payload() -> None:
    _, body_a, _ = script.build_request(make_args(random_event_id=True))
    _, body_b, _ = script.build_request(make_args(random_event_id=True))
    assert json.loads(body_a)["event_id"] != json.loads(body_b)["event_id"]


def test_tamper_breaks_signature() -> None:
    _, body, headers = script.build_request(make_args(tamper=True))
    with pytest.raises(Exception, match="mismatch"):
        HmacSha256Verifier("demo-voice-secret").verify(body, headers)


def test_env_secret_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_WEBHOOK_SECRET", "from-env")
    _, body, headers = script.build_request(make_args())
    HmacSha256Verifier("from-env").verify(body, headers)


@respx.mock
def test_main_reports_status(capsys: pytest.CaptureFixture[str]) -> None:
    route = respx.post("http://relay.example.com/webhooks/voice/post-call").respond(
        202, json={"status": "accepted"}
    )
    code = script.main(["--url", "http://relay.example.com", "--provider", "voice"])
    assert code == 0
    assert route.called
    out = capsys.readouterr().out
    assert "HTTP 202" in out
    assert '"status": "accepted"' in out


@respx.mock
def test_main_returns_2_on_rejection(capsys: pytest.CaptureFixture[str]) -> None:
    respx.post("http://relay.example.com/webhooks/chat/message").respond(401, text="nope")
    code = script.main(["--url", "http://relay.example.com", "--provider", "chat"])
    assert code == 2
    assert "nope" in capsys.readouterr().out


@respx.mock
def test_main_returns_1_on_connection_error(capsys: pytest.CaptureFixture[str]) -> None:
    respx.post("http://relay.example.com/webhooks/voice/post-call").mock(
        side_effect=httpx.ConnectError("refused")
    )
    assert script.main(["--url", "http://relay.example.com"]) == 1
    assert "request failed" in capsys.readouterr().err
