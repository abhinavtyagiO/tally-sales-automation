from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any

from backend import config
from backend.db import database
from backend.services import local_agent_service
from backend.services.tally_client import TallyClient


logger = logging.getLogger(__name__)


def sync_from_tally(client: TallyClient | None = None, company: dict[str, Any] | None = None, agent: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    tally = client or TallyClient()
    if company and agent:
        logger.info(
            "tally.sync.start user_id=%s company_id=%s company_name=%s agent_id=%s mode=%s",
            company.get("user_id"),
            company.get("id"),
            company.get("company_name"),
            agent.get("id"),
            "direct" if agent.get("direct_tally") else "local_agent",
        )
        if agent.get("direct_tally"):
            company_tally = TallyClient(company.get("tally_url") or config.TALLY_URL)
            ledgers = company_tally.get_all_ledgers(company["company_name"])
            stock_items = company_tally.get_all_stock_items(company["company_name"])
        else:
            ledgers_response = local_agent_service.dispatch_tally_operation(
                agent,
                "export_collection",
                {"collection_id": "Ledger", "company_name": company["company_name"], "tally_url": company["tally_url"]},
            )
            stock_response = local_agent_service.dispatch_tally_operation(
                agent,
                "export_collection",
                {"collection_id": "StockItem", "company_name": company["company_name"], "tally_url": company["tally_url"]},
            )
            ledgers = _extract_agent_ledgers(ledgers_response)
            stock_items = _extract_agent_stock_items(stock_response)
        company_name = company["company_name"]
        company_id = company["id"]
    else:
        logger.info("tally.sync.start user_id=None company_id=None company_name=None agent_id=None mode=legacy")
        ledgers = tally.get_all_ledgers()
        stock_items = tally.get_all_stock_items()
        company_name = tally.get_company_name()
        company_id = database.ensure_legacy_company()["id"]

    database.replace_ledgers(ledgers, company_id=company_id)
    database.replace_stock_items(stock_items, company_id=company_id)
    if company_name:
        database.set_metadata("company", company_name)
    synced_at = datetime.now(timezone.utc).isoformat()
    database.set_metadata("last_sync_status", "success")
    database.set_metadata("last_sync_at", synced_at)
    database.set_company_sync(company_id, "success", synced_at)
    logger.info(
        "tally.sync.completed user_id=%s company_id=%s company_name=%s ledgers_count=%s stock_items_count=%s duration_ms=%s",
        company.get("user_id") if company else None,
        company_id,
        company_name,
        len(ledgers),
        len(stock_items),
        int((time.perf_counter() - started) * 1000),
    )

    return {
        "company": company_name,
        "ledgers_count": len(ledgers),
        "stock_items_count": len(stock_items),
        "last_sync_at": synced_at,
        "last_sync_status": "success",
    }


def get_cache_snapshot() -> dict[str, Any]:
    company = database.ensure_legacy_company()
    return get_company_cache_snapshot(company["id"])


def get_company_cache_snapshot(company_id: int) -> dict[str, Any]:
    company = database.get_company(company_id)
    cache_status = get_cache_status(company_id)
    return {
        "company": company["company_name"] if company else database.get_metadata("company"),
        "company_id": company_id,
        "last_sync_at": company.get("last_sync_at") if company else database.get_metadata("last_sync_at"),
        "last_sync_status": company.get("last_sync_status") if company else database.get_metadata("last_sync_status"),
        "cache_status": cache_status,
        "ledgers": database.list_ledgers(company_id),
        "stock_items": database.list_stock_items(company_id),
    }


def has_master_cache() -> bool:
    status = get_cache_status()
    return bool(status["ready"] and not status["stale"])


def get_cache_status(company_id: int | None = None) -> dict[str, Any]:
    return _cache_status(company_id)


def get_company_cache_status(company_id: int) -> dict[str, Any]:
    return _cache_status(company_id)


def _cache_status(company_id: int | None = None) -> dict[str, Any]:
    last_sync_at = database.get_metadata("last_sync_at")
    if company_id is not None:
        company = database.get_company(company_id)
        last_sync_at = company.get("last_sync_at") if company else None
    has_ledgers = bool(database.list_ledgers(company_id))
    has_stock_items = bool(database.list_stock_items(company_id))
    stale = True
    if last_sync_at:
        try:
            synced_at = datetime.fromisoformat(last_sync_at)
            if synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=timezone.utc)
            stale = datetime.now(timezone.utc) - synced_at > timedelta(hours=config.MASTER_CACHE_MAX_AGE_HOURS)
        except ValueError:
            stale = True
    return {
        "ready": bool(last_sync_at and has_ledgers and has_stock_items),
        "stale": stale,
        "has_ledgers": has_ledgers,
        "has_stock_items": has_stock_items,
        "max_age_hours": config.MASTER_CACHE_MAX_AGE_HOURS,
    }


def has_company_master_cache(company: dict[str, Any]) -> bool:
    return bool(company.get("last_sync_at") and database.list_ledgers(company["id"]) and database.list_stock_items(company["id"]))


def _extract_agent_ledgers(response: dict[str, Any]) -> list[dict[str, Any]]:
    if "ledgers" in response:
        return response["ledgers"]
    from backend.services.tally_client import _extract_collection, _get_ci

    return [
        {"name": _get_ci(item, "Name"), "group": _get_ci(item, "Parent") or _get_ci(item, "Group")}
        for item in _extract_collection(response, "Ledger")
        if _get_ci(item, "Name")
    ]


def _extract_agent_stock_items(response: dict[str, Any]) -> list[dict[str, Any] | str]:
    if "stock_items" in response:
        return response["stock_items"]
    from backend.services.tally_client import _extract_collection, _usable_stock_item_details

    return _usable_stock_item_details(_extract_collection(response, "StockItem"))
