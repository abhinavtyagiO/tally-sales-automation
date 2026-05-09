from __future__ import annotations

import logging
from typing import Any

from backend.services import local_agent_service
from backend.services.tally_client import TallyError


logger = logging.getLogger(__name__)


def get_tally_status(user_id: int) -> dict[str, Any]:
    try:
        agent = local_agent_service.get_or_create_active_agent(user_id)
        local_agent_service.dispatch_tally_operation(agent, "health_check", {})
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
    try:
        agent = local_agent_service.get_or_create_active_agent(user_id)
        response = local_agent_service.dispatch_tally_operation(agent, "list_companies", {})
    except TallyError as exc:
        detail = _classify_error(str(exc))
        logger.warning("tally.companies.failed user_id=%s detail=%s error=%r", user_id, detail, exc)
        return {
            "available": False,
            "companies": [],
            "detail": detail,
            "message": "Company list is unavailable. You can type the Tally company name.",
        }
    companies = sorted({str(name).strip() for name in response.get("companies", []) if str(name).strip()}, key=str.lower)
    logger.info("tally.companies.success user_id=%s count=%s", user_id, len(companies))
    return {"available": bool(companies), "companies": companies, "detail": None, "message": None}


def ensure_tally_reachable(user_id: int) -> dict[str, Any]:
    agent = local_agent_service.get_or_create_active_agent(user_id)
    local_agent_service.dispatch_tally_operation(agent, "health_check", {})
    logger.info("tally.reachable user_id=%s agent_id=%s", user_id, agent.get("id"))
    return agent


def _classify_error(message: str) -> str:
    lowered = message.lower()
    if "tally request failed" in lowered or "bad gateway" in lowered:
        return "tally_unreachable"
    if "not available" in lowered or "no base_url" in lowered or "connection refused" in lowered:
        return "connector_unavailable"
    return "unknown"
