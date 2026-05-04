from __future__ import annotations

from typing import Any, Optional

import requests
from fastapi import HTTPException

from backend.db import database
from backend.services.tally_client import TallyError


def create_pairing_token(user_id: int, device_name: str, base_url: Optional[str] = None) -> dict[str, Any]:
    token = database.random_token()
    agent = database.create_pairing_token(user_id, device_name, _hash_pairing_token(token), base_url=base_url)
    return {"pairing_token": token, "agent": agent}


def pair_agent(pairing_token: str, device_name: Optional[str] = None, base_url: Optional[str] = None) -> dict[str, Any]:
    agent = database.pair_local_agent(_hash_pairing_token(pairing_token), device_name=device_name, base_url=base_url)
    if not agent:
        raise HTTPException(status_code=404, detail="Invalid pairing token")
    return agent


def heartbeat(agent_id: int, user_id: Optional[int] = None, base_url: Optional[str] = None) -> dict[str, Any]:
    agent = database.heartbeat_local_agent(agent_id, user_id=user_id, base_url=base_url)
    if not agent:
        raise HTTPException(status_code=404, detail="Local agent not found")
    return agent


def dispatch_tally_operation(agent: dict[str, Any], operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    base_url = (agent.get("base_url") or "").rstrip("/")
    if not base_url:
        raise TallyError("Local agent has no base_url")
    try:
        response = requests.post(
            f"{base_url}/tally/execute",
            json={"operation": operation, "payload": payload},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise TallyError(f"Local agent request failed: {exc}") from exc
    except ValueError as exc:
        raise TallyError("Local agent returned non-JSON response") from exc


def _hash_pairing_token(token: str) -> str:
    from backend.services.auth_service import hash_token

    return hash_token(token)
