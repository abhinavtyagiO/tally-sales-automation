from __future__ import annotations

from fastapi import HTTPException

from backend import config
from backend.db import database


def require_company(user_id: int, company_id: int) -> dict:
    company = database.get_company(company_id, user_id=user_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def company_has_online_agent(company: dict) -> dict:
    if config.CONNECTOR_MODE != "polling":
        return {"id": None, "direct_tally": True, "base_url": company.get("tally_url") or config.TALLY_URL}
    agent_id = company.get("local_agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="Company has no paired local agent")
    agent = database.get_local_agent(int(agent_id), user_id=int(company["user_id"]))
    if not agent or agent.get("revoked_at") or agent.get("pairing_status") != "paired":
        raise HTTPException(status_code=400, detail="Company local agent is not paired")
    if not agent.get("last_seen_at"):
        raise HTTPException(status_code=400, detail="Local agent is offline")
    return agent
