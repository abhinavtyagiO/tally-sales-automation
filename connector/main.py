from __future__ import annotations

import argparse
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from backend import config
from backend.services.tally_client import TallyClient, TallyError, _extract_collection, _stock_item_details


logger = logging.getLogger("accountpilot.connector")


class BackendTransport(Protocol):
    def post(self, url: str, **kwargs: Any) -> requests.Response:
        ...


@dataclass
class ConnectorSettings:
    backend_url: str
    agent_id: int
    agent_token: str
    tally_url: str = config.TALLY_URL
    poll_interval_seconds: float = 2.0
    max_backoff_seconds: float = 60.0


class PollingConnector:
    def __init__(self, settings: ConnectorSettings, transport: BackendTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or requests
        self._backoff_seconds = settings.poll_interval_seconds

    def run_forever(self) -> None:
        while True:
            try:
                ran_job = self.run_once()
                self._backoff_seconds = self.settings.poll_interval_seconds
                if not ran_job:
                    time.sleep(self.settings.poll_interval_seconds)
            except Exception as exc:
                logger.warning("connector.loop_failed error=%r", exc)
                time.sleep(self._backoff_seconds)
                self._backoff_seconds = min(self._backoff_seconds * 2, self.settings.max_backoff_seconds)

    def run_once(self) -> bool:
        job = self.poll()
        if not job:
            return False
        try:
            result = self.dispatch(job)
            self.submit_result(job["id"], "success", result)
        except Exception as exc:
            logger.warning("connector.job_failed job_id=%s operation=%s error=%r", job.get("id"), job.get("operation"), exc)
            self.submit_result(job["id"], "failed", {"detail": str(exc)}, str(exc))
        return True

    def poll(self) -> dict[str, Any] | None:
        response = self.transport.post(
            self._url("/connector/poll"),
            json={"agent_id": self.settings.agent_id},
            headers=self._headers(),
            timeout=35,
        )
        response.raise_for_status()
        return (response.json() or {}).get("job")

    def submit_result(self, job_id: int, status: str, result: dict[str, Any], error_message: str | None = None) -> None:
        response = self.transport.post(
            self._url(f"/connector/jobs/{job_id}/result"),
            json={
                "agent_id": self.settings.agent_id,
                "status": status,
                "result": result,
                "error_message": error_message,
            },
            headers=self._headers(),
            timeout=35,
        )
        response.raise_for_status()

    def dispatch(self, job: dict[str, Any]) -> dict[str, Any]:
        operation = job["operation"]
        payload = job.get("payload") or {}
        tally_url = payload.get("tally_url") or self.settings.tally_url
        company_name = payload.get("company_name")
        client = TallyClient(base_url=tally_url)
        if operation == "health_check":
            client.ping()
            return {"status": "connected"}
        if operation == "list_companies":
            return {"companies": client.get_companies()}
        if operation == "validate_company":
            data = client.export_collection("Ledger", company_name)
            return {"ledgers": client.get_all_ledgers(company_name), "raw": data}
        if operation == "sync_ledgers":
            data = client.export_collection("Ledger", company_name)
            return {"ledgers": client.get_all_ledgers(company_name), "raw": data}
        if operation == "sync_stock_items":
            data = client.export_stock_items(company_name)
            return {"stock_items": [_stock_item_details(item) for item in _extract_collection(data, "StockItem")], "raw": data}
        if operation == "create_sales_voucher":
            return client.create_sales_voucher(payload["voucher"], company_name=company_name)
        if operation == "create_ledger":
            return client.create_ledger(payload["name"], payload["group_name"], company_name=company_name)
        raise TallyError(f"Unsupported operation: {operation}")

    def _headers(self) -> dict[str, str]:
        return {"X-AccountPilot-Agent-Token": self.settings.agent_token}

    def _url(self, path: str) -> str:
        return f"{self.settings.backend_url.rstrip('/')}{path}"


def settings_from_env() -> ConnectorSettings:
    return ConnectorSettings(
        backend_url=os.environ["ACCOUNTPILOT_BACKEND_URL"],
        agent_id=int(os.environ["ACCOUNTPILOT_AGENT_ID"]),
        agent_token=os.environ["ACCOUNTPILOT_AGENT_TOKEN"],
        tally_url=os.getenv("TALLY_URL", config.TALLY_URL),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AccountPilot polling connector")
    parser.add_argument("--once", action="store_true", help="Poll and execute at most one job")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    connector = PollingConnector(settings_from_env())
    if args.once:
        connector.run_once()
    else:
        connector.run_forever()


if __name__ == "__main__":
    main()
