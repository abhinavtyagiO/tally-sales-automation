from __future__ import annotations

import logging
from typing import Any, Optional

import requests
from fastapi import HTTPException

from backend import config
from backend.db import database
from backend.services.tally_client import TallyError


logger = logging.getLogger(__name__)


def create_pairing_token(user_id: int, device_name: str, base_url: Optional[str] = None) -> dict[str, Any]:
    token = database.random_token()
    agent = database.create_pairing_token(user_id, device_name, _hash_pairing_token(token), base_url=base_url)
    logger.info("local_agent.pairing_token.created user_id=%s agent_id=%s base_url=%s", user_id, agent["id"], base_url)
    return {"pairing_token": token, "agent": agent}


def pair_agent(pairing_token: str, device_name: Optional[str] = None, base_url: Optional[str] = None) -> dict[str, Any]:
    agent = database.pair_local_agent(_hash_pairing_token(pairing_token), device_name=device_name, base_url=base_url)
    if not agent:
        logger.warning("local_agent.pair.failed reason=invalid_pairing_token device_name=%s base_url=%s", device_name, base_url)
        raise HTTPException(status_code=404, detail="Invalid pairing token")
    logger.info("local_agent.pair.success user_id=%s agent_id=%s base_url=%s", agent["user_id"], agent["id"], agent.get("base_url"))
    return agent


def heartbeat(agent_id: int, user_id: Optional[int] = None, base_url: Optional[str] = None) -> dict[str, Any]:
    agent = database.heartbeat_local_agent(agent_id, user_id=user_id, base_url=base_url)
    if not agent:
        logger.warning("local_agent.heartbeat.failed agent_id=%s user_id=%s reason=not_found", agent_id, user_id)
        raise HTTPException(status_code=404, detail="Local agent not found")
    logger.info("local_agent.heartbeat.success agent_id=%s user_id=%s base_url=%s", agent_id, agent.get("user_id"), agent.get("base_url"))
    return agent


def dispatch_tally_operation(agent: dict[str, Any], operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    base_url = (agent.get("base_url") or "").rstrip("/")
    if not base_url:
        logger.warning("local_agent.dispatch.failed agent_id=%s operation=%s reason=missing_base_url", agent.get("id"), operation)
        raise TallyError("Local agent has no base_url")
    company_name = payload.get("company_name") if isinstance(payload, dict) else None
    logger.info(
        "local_agent.dispatch.start agent_id=%s operation=%s base_url=%s company_name=%s",
        agent.get("id"),
        operation,
        base_url,
        company_name,
    )
    try:
        response = requests.post(
            f"{base_url}/tally/execute",
            json={"operation": operation, "payload": payload},
            timeout=30,
        )
        if response.status_code >= 400:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except ValueError:
                pass
            logger.warning(
                "local_agent.dispatch.failed agent_id=%s operation=%s status_code=%s detail=%s",
                agent.get("id"),
                operation,
                response.status_code,
                str(detail)[:500],
            )
            raise TallyError(_format_local_agent_error(str(detail)))
        logger.info("local_agent.dispatch.success agent_id=%s operation=%s status_code=%s", agent.get("id"), operation, response.status_code)
        return response.json()
    except requests.RequestException as exc:
        logger.warning("local_agent.dispatch.failed agent_id=%s operation=%s error=%r", agent.get("id"), operation, exc)
        raise TallyError(f"Local agent request failed: {exc}") from exc
    except ValueError as exc:
        logger.warning("local_agent.dispatch.failed agent_id=%s operation=%s reason=non_json_response", agent.get("id"), operation)
        raise TallyError("Local agent returned non-JSON response") from exc


def get_active_agent(user_id: int) -> dict[str, Any]:
    agent = database.get_active_local_agent(user_id)
    if not agent:
        logger.warning("local_agent.active_agent.missing user_id=%s", user_id)
        raise TallyError("Tally connection is not available")
    logger.info("local_agent.active_agent.found user_id=%s agent_id=%s base_url=%s", user_id, agent["id"], agent.get("base_url"))
    return agent


def get_or_create_active_agent(user_id: int) -> dict[str, Any]:
    agent = database.get_active_local_agent(user_id)
    if agent:
        logger.info("local_agent.active_agent.found user_id=%s agent_id=%s base_url=%s", user_id, agent["id"], agent.get("base_url"))
        return agent

    base_url = config.LOCAL_AGENT_URL.rstrip("/")
    if not base_url:
        logger.warning("local_agent.bootstrap.failed user_id=%s reason=missing_local_agent_url", user_id)
        raise TallyError("Tally connection is not available")

    pairing = create_pairing_token(user_id, "Local Tally connector", base_url)
    agent = pair_agent(pairing["pairing_token"], "Local Tally connector", base_url)
    logger.info("local_agent.bootstrap.success user_id=%s agent_id=%s base_url=%s", user_id, agent["id"], base_url)
    return agent


def _hash_pairing_token(token: str) -> str:
    from backend.services.auth_service import hash_token

    return hash_token(token)


def _format_local_agent_error(detail: str) -> str:
    if detail.startswith("Tally rejected ") or detail.startswith("Tally "):
        return detail
    return f"Local agent request failed: {detail}"
