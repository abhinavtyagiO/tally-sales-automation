from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

from backend import config
from backend.services.tally_client import TallyClient, TallyError, _extract_collection, _ledger_details, _stock_group_details, _stock_item_details


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
                job_count = self.run_until_idle()
                self._backoff_seconds = self.settings.poll_interval_seconds
                if job_count:
                    logger.info("connector.batch_drained job_count=%s", job_count)
                time.sleep(self.settings.poll_interval_seconds)
            except Exception as exc:
                logger.warning("connector.loop_failed error=%r", exc)
                time.sleep(self._backoff_seconds)
                self._backoff_seconds = min(self._backoff_seconds * 2, self.settings.max_backoff_seconds)

    def run_until_idle(self) -> int:
        job_count = 0
        while self.run_once():
            job_count += 1
        return job_count

    def run_once(self) -> bool:
        job = self.poll()
        if not job:
            return False
        started = time.perf_counter()
        logger.info(
            "connector.job.start agent_id=%s job_id=%s operation=%s company_id=%s commit_run_id=%s",
            self.settings.agent_id,
            job.get("id"),
            job.get("operation"),
            job.get("company_id"),
            job.get("commit_run_id"),
        )
        try:
            result = self.dispatch(job)
            self.submit_result(job["id"], "success", result)
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "connector.job.completed agent_id=%s job_id=%s operation=%s status=success duration_ms=%s result_summary=%s",
                self.settings.agent_id,
                job.get("id"),
                job.get("operation"),
                duration_ms,
                _result_summary(result),
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("connector.job_failed job_id=%s operation=%s error=%r", job.get("id"), job.get("operation"), exc)
            self.submit_result(job["id"], "failed", {"detail": str(exc)}, str(exc))
            logger.warning(
                "connector.job.completed agent_id=%s job_id=%s operation=%s status=failed duration_ms=%s error=%r",
                self.settings.agent_id,
                job.get("id"),
                job.get("operation"),
                duration_ms,
                exc,
            )
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
            ledgers = [_ledger_details(item) for item in _extract_collection(data, "Ledger")]
            ledgers = [ledger for ledger in ledgers if ledger.get("name")]
            logger.info("connector.master_export operation=%s company_name=%s count=%s", operation, company_name, len(ledgers))
            return {"ledgers": ledgers, "summary": {"ledger_count": len(ledgers)}}
        if operation == "sync_ledgers":
            data = client.export_collection("Ledger", company_name)
            ledgers = [_ledger_details(item) for item in _extract_collection(data, "Ledger")]
            ledgers = [ledger for ledger in ledgers if ledger.get("name")]
            logger.info("connector.master_export operation=%s company_name=%s count=%s", operation, company_name, len(ledgers))
            return {"ledgers": ledgers, "summary": {"ledger_count": len(ledgers)}}
        if operation == "sync_stock_items":
            data = client.export_stock_items(company_name)
            stock_items = [_stock_item_details(item) for item in _extract_collection(data, "StockItem")]
            stock_items = [item for item in stock_items if item.get("name")]
            logger.info("connector.master_export operation=%s company_name=%s count=%s", operation, company_name, len(stock_items))
            return {"stock_items": stock_items, "summary": {"stock_item_count": len(stock_items)}}
        if operation == "sync_stock_groups":
            data = client.export_stock_groups(company_name)
            stock_groups = [_stock_group_details(item) for item in _extract_collection(data, "StockGroup")]
            stock_groups = [item for item in stock_groups if item.get("name")]
            logger.info("connector.master_export operation=%s company_name=%s count=%s", operation, company_name, len(stock_groups))
            return {"stock_groups": stock_groups, "summary": {"stock_group_count": len(stock_groups)}}
        if operation == "sync_stock_items_for_group":
            group_name = str(payload.get("group_name") or "").strip()
            if not group_name:
                raise TallyError("Stock group name is required")
            data = client.export_stock_items_for_group(company_name, group_name)
            stock_items = [_stock_item_details(item) for item in _extract_collection(data, "StockItem")]
            stock_items = [item for item in stock_items if item.get("name")]
            logger.info("connector.master_export operation=%s company_name=%s group_name=%s count=%s", operation, company_name, group_name, len(stock_items))
            return {"stock_items": stock_items, "summary": {"stock_item_count": len(stock_items), "group_name": group_name}}
        if operation == "create_sales_voucher":
            return client.create_sales_voucher(payload["voucher"], company_name=company_name)
        if operation == "create_ledger":
            return client.create_ledger(payload["name"], payload["group_name"], company_name=company_name)
        raise TallyError(f"Unsupported operation: {operation}")

    def _headers(self) -> dict[str, str]:
        return {"X-AccountPilot-Agent-Token": self.settings.agent_token}

    def _url(self, path: str) -> str:
        return f"{self.settings.backend_url.rstrip('/')}{path}"


def default_config_path() -> Path:
    configured = os.getenv("ACCOUNTPILOT_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AccountPilot Helper" / "config.json"
    return Path.home() / ".accountpilot-helper" / "config.json"


def default_log_path() -> Path:
    configured = os.getenv("ACCOUNTPILOT_LOG_PATH")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AccountPilot Helper" / "logs" / "helper.log"
    return Path.home() / ".accountpilot-helper" / "logs" / "helper.log"


def configure_logging() -> None:
    log_path = default_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary = result.get("summary")
    if isinstance(summary, dict):
        return summary
    if "companies" in result:
        return {"company_count": len(result.get("companies") or [])}
    if "ledgers" in result:
        return {"ledger_count": len(result.get("ledgers") or [])}
    if "stock_items" in result:
        return {"stock_item_count": len(result.get("stock_items") or [])}
    if "stock_groups" in result:
        return {"stock_group_count": len(result.get("stock_groups") or [])}
    if "status" in result:
        return {"status": result.get("status")}
    return {"keys": sorted(result.keys())}


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or default_config_path()
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def save_config(data: dict[str, Any], path: Path | None = None) -> None:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def register_with_setup_token(
    backend_url: str,
    setup_token: str,
    tally_url: str | None = None,
    device_name: str = "AccountPilot Helper",
    transport: BackendTransport | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    client = transport or requests
    response = client.post(
        f"{backend_url.rstrip('/')}/connector/register",
        json={"setup_token": setup_token, "device_name": device_name},
        timeout=35,
    )
    response.raise_for_status()
    payload = response.json()
    agent = payload["agent"]
    stored = {
        "backend_url": backend_url.rstrip("/"),
        "agent_id": int(agent["id"]),
        "agent_token": payload["agent_auth_token"],
        "tally_url": tally_url or config.TALLY_URL,
        "device_name": device_name,
    }
    save_config(stored, config_path)
    return stored


def settings_from_env() -> ConnectorSettings:
    saved = load_config()
    return ConnectorSettings(
        backend_url=os.getenv("ACCOUNTPILOT_BACKEND_URL") or saved["backend_url"],
        agent_id=int(os.getenv("ACCOUNTPILOT_AGENT_ID") or saved["agent_id"]),
        agent_token=os.getenv("ACCOUNTPILOT_AGENT_TOKEN") or saved["agent_token"],
        tally_url=os.getenv("TALLY_URL") or saved.get("tally_url", config.TALLY_URL),
    )


def configure_from_setup_args(args: argparse.Namespace) -> dict[str, Any] | None:
    setup_token = args.setup_token or os.getenv("ACCOUNTPILOT_SETUP_TOKEN")
    backend_url = args.backend_url or os.getenv("ACCOUNTPILOT_BACKEND_URL")
    if not setup_token:
        return None
    if not backend_url:
        raise RuntimeError("ACCOUNTPILOT_BACKEND_URL is required when setup token is provided")
    return register_with_setup_token(
        backend_url=backend_url,
        setup_token=setup_token,
        tally_url=args.tally_url or os.getenv("TALLY_URL") or config.TALLY_URL,
        device_name=args.device_name,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AccountPilot polling connector")
    parser.add_argument("--once", action="store_true", help="Poll and execute at most one job")
    parser.add_argument("--backend-url", default="", help="AccountPilot backend URL used during first-run setup")
    parser.add_argument("--setup-token", default="", help="One-time setup token from AccountPilot onboarding")
    parser.add_argument("--tally-url", default="", help="Local Tally URL to persist during setup")
    parser.add_argument("--device-name", default="AccountPilot Helper", help="Device name shown in AccountPilot")
    parser.add_argument("--configure-only", action="store_true", help="Register and save credentials without polling")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging()
    configured = configure_from_setup_args(args)
    if configured:
        logger.info("connector.configured agent_id=%s", configured["agent_id"])
    if args.configure_only:
        return
    connector = PollingConnector(settings_from_env())
    if args.once:
        connector.run_once()
    else:
        connector.run_forever()


if __name__ == "__main__":
    main()
