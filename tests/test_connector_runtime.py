from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


class FakeQueueTransport:
    def __init__(self, jobs: list[dict]) -> None:
        self.jobs = list(jobs)
        self.posts: list[dict] = []

    def post(self, url: str, **kwargs):
        self.posts.append({"url": url, **kwargs})
        if url.endswith("/connector/poll"):
            job = self.jobs.pop(0) if self.jobs else None
            return FakeResponse({"job": job})
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

    def test_run_until_idle_drains_available_jobs_before_returning(self) -> None:
        transport = FakeQueueTransport(
            [
                {"id": 1, "operation": "health_check", "payload": {}},
                {"id": 2, "operation": "health_check", "payload": {}},
                {"id": 3, "operation": "health_check", "payload": {}},
            ]
        )
        connector = FakeConnector(self.settings(), transport)

        self.assertEqual(connector.run_until_idle(), 3)

        poll_requests = [post for post in transport.posts if post["url"].endswith("/connector/poll")]
        result_requests = [post for post in transport.posts if "/connector/jobs/" in post["url"]]
        self.assertEqual(len(poll_requests), 4)
        self.assertEqual(len(result_requests), 3)
        self.assertEqual([post["json"]["status"] for post in result_requests], ["success", "success", "success"])

    def test_stock_sync_dispatch_does_not_include_raw_tally_payload(self) -> None:
        connector = PollingConnector(self.settings(), FakeTransport({"job": None}))
        tally_response = {
            "ENVELOPE": {
                "BODY": {
                    "DATA": {
                        "COLLECTION": {
                            "STOCKITEM": {
                                "NAME": "2.75-18 NGP",
                                "PARENT": "Tyres",
                            }
                        }
                    }
                }
            }
        }

        with patch("connector.main.TallyClient") as client_class:
            client_class.return_value.export_stock_items.return_value = tally_response
            result = connector.dispatch(
                {
                    "id": 1,
                    "operation": "sync_stock_items",
                    "payload": {"company_name": "Bhrama Enterprises", "tally_url": "http://127.0.0.1:9000"},
                }
            )

        self.assertNotIn("raw", result)
        self.assertEqual(result["summary"], {"stock_item_count": 1})
        self.assertEqual(result["stock_items"][0]["name"], "2.75-18 NGP")
        self.assertNotIn("raw", result["stock_items"][0])

    def test_stock_group_sync_dispatch_returns_compact_group_details(self) -> None:
        connector = PollingConnector(self.settings(), FakeTransport({"job": None}))
        tally_response = {
            "ENVELOPE": {
                "BODY": {
                    "DATA": {
                        "COLLECTION": {
                            "STOCKGROUP": {
                                "NAME": "Tyres",
                                "PARENT": "Primary",
                            }
                        }
                    }
                }
            }
        }

        with patch("connector.main.TallyClient") as client_class:
            client_class.return_value.export_stock_groups.return_value = tally_response
            result = connector.dispatch(
                {
                    "id": 1,
                    "operation": "sync_stock_groups",
                    "payload": {"company_name": "Bhrama Enterprises", "tally_url": "http://127.0.0.1:9000"},
                }
            )

        self.assertEqual(result["summary"], {"stock_group_count": 1})
        self.assertEqual(result["stock_groups"], [{"name": "Tyres", "parent_name": "Primary"}])

    def test_stock_items_for_group_dispatch_uses_group_specific_export(self) -> None:
        connector = PollingConnector(self.settings(), FakeTransport({"job": None}))
        tally_response = {
            "ENVELOPE": {
                "BODY": {
                    "DATA": {
                        "COLLECTION": {
                            "STOCKITEM": {
                                "NAME": "2.75-18 NGP",
                                "PARENT": "Tyres",
                            }
                        }
                    }
                }
            }
        }

        with patch("connector.main.TallyClient") as client_class:
            client_class.return_value.export_stock_items_for_group.return_value = tally_response
            result = connector.dispatch(
                {
                    "id": 1,
                    "operation": "sync_stock_items_for_group",
                    "payload": {"company_name": "Bhrama Enterprises", "group_name": "Tyres", "tally_url": "http://127.0.0.1:9000"},
                }
            )

        client_class.return_value.export_stock_items_for_group.assert_called_once_with("Bhrama Enterprises", "Tyres")
        self.assertEqual(result["summary"], {"stock_item_count": 1, "group_name": "Tyres"})
        self.assertEqual(result["stock_items"][0]["name"], "2.75-18 NGP")

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
