from __future__ import annotations

import logging
from typing import Any

from backend import config
from backend.services import local_agent_service
from backend.services.connector_job_service import create_list_companies_job, get_tally_company_discovery_status
from backend.services.connector_setup_service import get_helper_detection_status
from backend.services.tally_client import TallyClient, TallyError


logger = logging.getLogger(__name__)


def get_tally_status(user_id: int) -> dict[str, Any]:
    if config.CONNECTOR_MODE == "polling":
        helper = get_helper_detection_status(user_id)
        if helper["status"] == "connected":
            return {"status": "connected", "detail": None, "message": "AccountPilot Helper is connected"}
        return {"status": "disconnected", "detail": "connector_unavailable", "message": helper["message"]}
    try:
        TallyClient().ping()
    except TallyError as exc:
        detail = _classify_error(str(exc))
        logger.warning("tally.status.failed user_id=%s detail=%s error=%r", user_id, detail, exc)
        return {
            "status": "disconnected",
            "detail": detail,
            "message": "Can't connect to Tally right now. Please try again or contact support.",
        }
    return {"status": "connected", "detail": None, "message": "Connected to Tally"}


def list_tally_companies(user_id: int) -> dict[str, Any]:
    if config.CONNECTOR_MODE == "polling":
        status = get_tally_company_discovery_status(user_id)
        if status["status"] == "not_requested":
            try:
                create_list_companies_job(user_id)
            except Exception as exc:
                logger.warning("tally.companies.polling_enqueue_failed user_id=%s error=%r", user_id, exc)
            status = get_tally_company_discovery_status(user_id)
        return {
            "available": status["available"],
            "companies": status["companies"],
            "detail": status.get("detail"),
            "message": status.get("message"),
        }
    try:
        companies = TallyClient().get_companies()
    except TallyError as exc:
        detail = _classify_error(str(exc))
        logger.warning("tally.companies.failed user_id=%s detail=%s error=%r", user_id, detail, exc)
        return {
            "available": False,
            "companies": [],
            "detail": detail,
            "message": "Company list is unavailable. You can type the Tally company name.",
        }
    companies = sorted({str(name).strip() for name in companies if str(name).strip()}, key=str.lower)
    logger.info("tally.companies.success user_id=%s count=%s", user_id, len(companies))
    return {"available": bool(companies), "companies": companies, "detail": None, "message": None}


def ensure_tally_reachable(user_id: int) -> dict[str, Any]:
    if config.CONNECTOR_MODE == "polling":
        helper = get_helper_detection_status(user_id)
        if helper["status"] == "connected" and helper.get("agent"):
            return helper["agent"]
        raise TallyError("AccountPilot Helper is not connected")
    TallyClient().ping()
    logger.info("tally.reachable user_id=%s mode=direct", user_id)
    return {"id": None, "direct_tally": True, "base_url": config.TALLY_URL}


def _classify_error(message: str) -> str:
    lowered = message.lower()
    if "tally request failed" in lowered or "bad gateway" in lowered:
        return "tally_unreachable"
    if "not available" in lowered or "no base_url" in lowered or "connection refused" in lowered:
        return "connector_unavailable"
    return "unknown"
