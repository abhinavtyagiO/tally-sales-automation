from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from fastapi import HTTPException

from backend.db import database
from backend.services.auth_service import hash_token


SETUP_TOKEN_TTL_MINUTES = 15
STALE_AFTER_MINUTES = 5
logger = logging.getLogger(__name__)


def create_setup_session(user_id: int) -> dict[str, Any]:
    setup_token = database.random_token()
    agent_auth_token = database.random_token()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=SETUP_TOKEN_TTL_MINUTES)).isoformat()
    agent = database.create_pairing_token(
        user_id,
        "AccountPilot Helper",
        hash_token(setup_token),
        auth_token=agent_auth_token,
        setup_expires_at=expires_at,
    )
    logger.info("connector.setup_session.created user_id=%s agent_id=%s expires_at=%s", user_id, agent["id"], expires_at)
    return {
        "setup_token": setup_token,
        "expires_at": expires_at,
        "agent": _public_agent(agent),
    }


def register_helper(setup_token: str, device_name: str | None = None) -> dict[str, Any]:
    agent = database.pair_local_agent(hash_token(setup_token), device_name=device_name or "AccountPilot Helper")
    if not agent:
        logger.warning("connector.register.failed reason=invalid_or_expired_setup_session")
        raise HTTPException(status_code=404, detail="Invalid or expired setup session")
    token = agent.get("auth_token")
    if not token:
        logger.warning("connector.register.failed user_id=%s agent_id=%s reason=missing_agent_auth_token", agent.get("user_id"), agent.get("id"))
        raise HTTPException(status_code=400, detail="Connector credentials are unavailable")
    logger.info("connector.register.success user_id=%s agent_id=%s device_name=%s", agent.get("user_id"), agent.get("id"), agent.get("device_name"))
    return {"agent": _public_agent(agent), "agent_auth_token": token}


def get_helper_detection_status(user_id: int) -> dict[str, Any]:
    agent = database.get_latest_local_agent(user_id)
    if not agent:
        logger.info("connector.status user_id=%s status=helper_required agent_id=None", user_id)
        return {"status": "helper_required", "message": "Install AccountPilot Helper to connect with Tally.", "agent": None}
    if agent.get("pairing_status") != "paired":
        logger.info("connector.status user_id=%s status=waiting_for_helper agent_id=%s", user_id, agent.get("id"))
        return {"status": "waiting_for_helper", "message": "Waiting for AccountPilot Helper to finish setup.", "agent": _public_agent(agent)}
    if _is_stale(agent.get("last_seen_at")):
        logger.info("connector.status user_id=%s status=stale agent_id=%s last_seen_at=%s", user_id, agent.get("id"), agent.get("last_seen_at"))
        return {"status": "stale", "message": "AccountPilot Helper has not checked in recently.", "agent": _public_agent(agent)}
    logger.info("connector.status user_id=%s status=connected agent_id=%s last_seen_at=%s", user_id, agent.get("id"), agent.get("last_seen_at"))
    return {"status": "connected", "message": "AccountPilot Helper is connected.", "agent": _public_agent(agent)}


def get_helper_diagnostics(user_id: int) -> dict[str, Any]:
    agent = database.get_latest_local_agent(user_id)
    if not agent:
        return {
            "status": "helper_required",
            "message": "AccountPilot Helper is not installed or has not connected yet.",
            "agent": None,
            "recent_jobs": [],
        }
    detection = get_helper_detection_status(user_id)
    recent_jobs = database.list_recent_connector_jobs_for_agent(int(agent["id"]), limit=10)
    return {
        "status": detection["status"],
        "message": detection["message"],
        "agent": _public_agent(agent),
        "last_heartbeat_at": agent.get("last_seen_at"),
        "last_activity_at": agent.get("last_activity_at"),
        "last_error": agent.get("last_error"),
        "recent_jobs": [_public_job(job) for job in recent_jobs],
    }


def _is_stale(value: str | None) -> bool:
    if not value:
        return True
    try:
        last_seen = datetime.fromisoformat(value)
    except ValueError:
        return True
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_seen > timedelta(minutes=STALE_AFTER_MINUTES)


def _public_agent(agent: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in agent.items() if key != "auth_token"}


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "company_id": job.get("company_id"),
        "commit_run_id": job.get("commit_run_id"),
        "operation": job["operation"],
        "status": job["status"],
        "attempt_count": job["attempt_count"],
        "error_message": job.get("error_message"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job.get("completed_at"),
    }
