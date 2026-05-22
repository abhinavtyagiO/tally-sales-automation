from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from connector.main import ConnectorSettings, PollingConnector, load_config, register_with_setup_token


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeTransport:
    def __init__(self, poll_payload: dict) -> None:
        self.poll_payload = poll_payload
        self.posts: list[dict] = []

    def post(self, url: str, **kwargs):
        self.posts.append({"url": url, **kwargs})
        if url.endswith("/connector/poll"):
            return FakeResponse(self.poll_payload)
        return FakeResponse({"status": "ok"})


class FakeRegistrationTransport:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    def post(self, url: str, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return FakeResponse({"agent": {"id": 42, "device_name": "AccountPilot Helper"}, "agent_auth_token": "registered-token"})


class FakeConnector(PollingConnector):
    def __init__(self, settings: ConnectorSettings, transport: FakeTransport, dispatch_result=None, dispatch_error: Exception | None = None) -> None:
        super().__init__(settings, transport)
        self.dispatch_result = dispatch_result or {"status": "connected"}
        self.dispatch_error = dispatch_error

    def dispatch(self, job: dict) -> dict:
        if self.dispatch_error:
            raise self.dispatch_error
        return self.dispatch_result


class ConnectorRuntimeTests(unittest.TestCase):
    def settings(self) -> ConnectorSettings:
        return ConnectorSettings(
            backend_url="https://api.example.test",
            agent_id=42,
            agent_token="secret",
            tally_url="http://127.0.0.1:9000",
        )

    def test_run_once_polls_dispatches_and_submits_success(self) -> None:
        transport = FakeTransport({"job": {"id": 7, "operation": "health_check", "payload": {}}})
        connector = FakeConnector(self.settings(), transport)

        self.assertTrue(connector.run_once())

        self.assertEqual(transport.posts[0]["url"], "https://api.example.test/connector/poll")
        self.assertEqual(transport.posts[0]["headers"]["X-AccountPilot-Agent-Token"], "secret")
        self.assertEqual(transport.posts[1]["url"], "https://api.example.test/connector/jobs/7/result")
        self.assertEqual(transport.posts[1]["json"]["status"], "success")

    def test_run_once_submits_failure_when_dispatch_fails(self) -> None:
        transport = FakeTransport({"job": {"id": 9, "operation": "health_check", "payload": {}}})
        connector = FakeConnector(self.settings(), transport, dispatch_error=RuntimeError("Tally closed"))

        self.assertTrue(connector.run_once())

        self.assertEqual(transport.posts[1]["json"]["status"], "failed")
        self.assertEqual(transport.posts[1]["json"]["error_message"], "Tally closed")

    def test_run_once_is_idle_when_no_job_available(self) -> None:
        transport = FakeTransport({"job": None})
        connector = FakeConnector(self.settings(), transport)

        self.assertFalse(connector.run_once())
        self.assertEqual(len(transport.posts), 1)

    def test_register_with_setup_token_persists_connector_config(self) -> None:
        transport = FakeRegistrationTransport()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            stored = register_with_setup_token(
                backend_url="https://api.example.test/",
                setup_token="setup-secret",
                tally_url="http://127.0.0.1:9000",
                transport=transport,
                config_path=config_path,
            )

            self.assertEqual(transport.posts[0]["url"], "https://api.example.test/connector/register")
            self.assertEqual(transport.posts[0]["json"]["setup_token"], "setup-secret")
            self.assertEqual(stored["agent_id"], 42)
            self.assertEqual(stored["agent_token"], "registered-token")
            self.assertEqual(load_config(config_path)["backend_url"], "https://api.example.test")


if __name__ == "__main__":
    unittest.main()
