from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from backend.db import database


HEALTH_CHECK_OPERATION = "health_check"
LIST_COMPANIES_OPERATION = "list_companies"
VALIDATE_COMPANY_OPERATION = "validate_company"
SYNC_LEDGERS_OPERATION = "sync_ledgers"
SYNC_STOCK_ITEMS_OPERATION = "sync_stock_items"
LEASE_SECONDS = 60


def create_tally_health_job(user_id: int, company: dict[str, Any]) -> dict[str, Any]:
    agent_id = company.get("local_agent_id")
    if not agent_id:
        raise HTTPException(status_code=503, detail="AccountPilot Helper is not connected")
    agent = database.get_local_agent(int(agent_id), user_id=user_id)
    if not agent or agent.get("revoked_at"):
        raise HTTPException(status_code=503, detail="AccountPilot Helper is not connected")
    return database.create_connector_job(
        user_id=user_id,
        company_id=int(company["id"]),
        agent_id=int(agent["id"]),
        operation=HEALTH_CHECK_OPERATION,
        payload={
            "company_name": company["company_name"],
            "tally_url": company["tally_url"],
        },
    )


def create_list_companies_job(user_id: int) -> dict[str, Any]:
    agent = _latest_connected_agent(user_id)
    return database.create_connector_job(
        user_id=user_id,
        company_id=None,
        agent_id=int(agent["id"]),
        operation=LIST_COMPANIES_OPERATION,
        payload={},
    )


def create_validate_company_job(user_id: int, company_name: str, tally_url: str) -> dict[str, Any]:
    agent = _latest_connected_agent(user_id)
    return database.create_connector_job(
        user_id=user_id,
        company_id=None,
        agent_id=int(agent["id"]),
        operation=VALIDATE_COMPANY_OPERATION,
        payload={"company_name": company_name, "tally_url": tally_url},
    )


def create_master_sync_jobs(user_id: int, company: dict[str, Any]) -> dict[str, Any]:
    agent = _company_agent(user_id, company)
    database.set_company_sync(int(company["id"]), "queued", company.get("last_sync_at"))
    ledgers_job = database.create_connector_job(
        user_id=user_id,
        company_id=int(company["id"]),
        agent_id=int(agent["id"]),
        operation=SYNC_LEDGERS_OPERATION,
        payload={
            "collection_id": "Ledger",
            "company_name": company["company_name"],
            "tally_url": company["tally_url"],
        },
    )
    stock_job = database.create_connector_job(
        user_id=user_id,
        company_id=int(company["id"]),
        agent_id=int(agent["id"]),
        operation=SYNC_STOCK_ITEMS_OPERATION,
        payload={
            "collection_id": "StockItem",
            "company_name": company["company_name"],
            "tally_url": company["tally_url"],
        },
    )
    return {"jobs": [ledgers_job, stock_job], "status": get_master_sync_status(int(company["id"]))}


def authenticate_connector(agent_id: int, token: str | None) -> dict[str, Any]:
    agent = database.get_local_agent(agent_id)
    if not agent or agent.get("revoked_at") or agent.get("pairing_status") != "paired":
        raise HTTPException(status_code=401, detail="Invalid connector credentials")
    expected = agent.get("auth_token")
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="Invalid connector credentials")
    if not expected and token:
        raise HTTPException(status_code=401, detail="Invalid connector credentials")
    return agent


def poll_connector_job(agent_id: int, token: str | None) -> dict[str, Any]:
    agent = authenticate_connector(agent_id, token)
    database.heartbeat_local_agent(int(agent["id"]), user_id=int(agent["user_id"]))
    lease_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat()
    job = database.lease_next_connector_job(int(agent["id"]), lease_expires_at)
    return {"job": _public_job(job) if job else None}


def submit_connector_job_result(agent_id: int, token: str | None, job_id: int, status: str, result: dict[str, Any] | None, error_message: str | None) -> dict[str, Any]:
    agent = authenticate_connector(agent_id, token)
    if status == "success":
        job = database.complete_connector_job(job_id, int(agent["id"]), result or {})
    elif status == "failed":
        job = database.fail_connector_job(job_id, int(agent["id"]), error_message or "Connector job failed", result or {})
    else:
        raise HTTPException(status_code=400, detail="Unsupported connector job result status")
    if not job:
        raise HTTPException(status_code=404, detail="Connector job not found")
    database.update_local_agent_activity(int(agent["id"]), None if status == "success" else error_message)
    _apply_job_result(job)
    return {"job": _public_job(job)}


def get_company_tally_health_status(company_id: int) -> dict[str, Any]:
    job = database.get_latest_connector_job(company_id, HEALTH_CHECK_OPERATION)
    if not job:
        return {
            "status": "disconnected",
            "detail": "connector_unavailable",
            "message": "AccountPilot Helper has not checked Tally yet.",
            "job": None,
        }
    status = job["status"]
    if status in {"queued", "leased"}:
        return {
            "status": "checking",
            "detail": None,
            "message": "Checking Tally connection...",
            "job": _public_job(job),
        }
    if status == "completed":
        return {
            "status": "connected",
            "detail": None,
            "message": "Connected to Tally",
            "job": _public_job(job),
        }
    return {
        "status": "disconnected",
        "detail": "tally_unreachable",
        "message": "Can't connect to Tally right now. Open Tally and try again.",
        "job": _public_job(job),
    }


def get_tally_company_discovery_status(user_id: int) -> dict[str, Any]:
    agent = database.get_latest_local_agent(user_id)
    if not agent or agent.get("pairing_status") != "paired":
        return {
            "available": False,
            "companies": [],
            "status": "helper_required",
            "detail": "connector_unavailable",
            "message": "Install AccountPilot Helper to load companies from Tally.",
            "job": None,
        }
    job = _latest_user_job(user_id, LIST_COMPANIES_OPERATION)
    if not job:
        return {
            "available": False,
            "companies": [],
            "status": "not_requested",
            "detail": None,
            "message": "Company list is unavailable. You can type the Tally company name.",
            "job": None,
        }
    if job["status"] in {"queued", "leased"}:
        return {
            "available": False,
            "companies": [],
            "status": "checking",
            "detail": None,
            "message": "Loading Tally companies...",
            "job": _public_job(job),
        }
    if job["status"] == "completed":
        companies = sorted({str(name).strip() for name in (job.get("result") or {}).get("companies", []) if str(name).strip()}, key=str.lower)
        return {
            "available": bool(companies),
            "companies": companies,
            "status": "available" if companies else "empty",
            "detail": None,
            "message": None if companies else "No Tally companies were returned. You can type the company name.",
            "job": _public_job(job),
        }
    return {
        "available": False,
        "companies": [],
        "status": "failed",
        "detail": "tally_unreachable",
        "message": "Company list is unavailable. You can type the Tally company name.",
        "job": _public_job(job),
    }


def get_validate_company_status(user_id: int, job_id: int) -> dict[str, Any]:
    job = database.get_connector_job(job_id)
    if not job or int(job["user_id"]) != user_id or job["operation"] != VALIDATE_COMPANY_OPERATION:
        raise HTTPException(status_code=404, detail="Company validation job not found")
    if job["status"] in {"queued", "leased"}:
        return {"status": "checking", "valid": False, "message": "Checking Tally company...", "job": _public_job(job)}
    if job["status"] == "completed":
        ledgers = (job.get("result") or {}).get("ledgers") or []
        valid = bool(ledgers)
        return {
            "status": "valid" if valid else "invalid",
            "valid": valid,
            "message": None if valid else "Company not found in Tally or no ledgers were returned.",
            "job": _public_job(job),
        }
    return {
        "status": "failed",
        "valid": False,
        "message": job.get("error_message") or "Company validation failed.",
        "job": _public_job(job),
    }


def get_master_sync_status(company_id: int) -> dict[str, Any]:
    ledgers_job = database.get_latest_connector_job(company_id, SYNC_LEDGERS_OPERATION)
    stock_job = database.get_latest_connector_job(company_id, SYNC_STOCK_ITEMS_OPERATION)
    jobs = [job for job in (ledgers_job, stock_job) if job]
    if not jobs:
        return {"status": "not_requested", "message": "Master sync has not been requested.", "jobs": []}
    if any(job["status"] == "failed" for job in jobs):
        return {"status": "failed", "message": "Tally master sync failed.", "jobs": [_public_job(job) for job in jobs]}
    if len(jobs) == 2 and all(job["status"] == "completed" for job in jobs):
        return {"status": "completed", "message": "Tally masters synced.", "jobs": [_public_job(job) for job in jobs]}
    return {"status": "syncing", "message": "Syncing Tally masters...", "jobs": [_public_job(job) for job in jobs]}


def _apply_job_result(job: dict[str, Any]) -> None:
    if job["status"] == "failed" and job.get("company_id") and job["operation"] == "create_sales_voucher":
        payload = job.get("payload") or {}
        voucher = payload.get("voucher") or {}
        source = voucher.get("Source") or {}
        import_row_id = source.get("import_row_id")
        if import_row_id:
            database.log_voucher(voucher, {"error": job.get("error_message")}, "failed", source=source)
            database.update_import_row_commit(int(import_row_id), "failed", job.get("error_message") or "Connector job failed")
        if job.get("commit_run_id"):
            database.refresh_commit_run_from_rows(int(job["commit_run_id"]))
        return
    if job["status"] == "failed" and job.get("company_id") and job["operation"] in {SYNC_LEDGERS_OPERATION, SYNC_STOCK_ITEMS_OPERATION}:
        database.set_company_sync(int(job["company_id"]), "failed", None)
        return
    if job["status"] != "completed" or not job.get("company_id"):
        return
    company_id = int(job["company_id"])
    result = job.get("result") or {}
    payload = job.get("payload") or {}
    if job["operation"] == SYNC_LEDGERS_OPERATION:
        database.replace_ledgers(result.get("ledgers") or [], company_id=company_id)
    elif job["operation"] == SYNC_STOCK_ITEMS_OPERATION:
        database.replace_stock_items(result.get("stock_items") or [], company_id=company_id)
    elif job["operation"] == "create_sales_voucher":
        voucher = payload.get("voucher") or {}
        source = voucher.get("Source") or {}
        fingerprint = source.get("source_fingerprint")
        import_row_id = source.get("import_row_id")
        if fingerprint and not database.successful_fingerprint_exists(str(fingerprint), company_id=company_id):
            database.log_voucher(voucher, result, "success", source=source)
        if import_row_id:
            database.update_import_row_commit(int(import_row_id), "success", None, result)
        if job.get("commit_run_id"):
            database.refresh_commit_run_from_rows(int(job["commit_run_id"]))
        return
    else:
        return
    status = get_master_sync_status(company_id)
    if status["status"] == "completed":
        database.set_company_sync(company_id, "success", database.utc_now())
    else:
        database.set_company_sync(company_id, "syncing", None)


def _company_agent(user_id: int, company: dict[str, Any]) -> dict[str, Any]:
    agent_id = company.get("local_agent_id")
    if not agent_id:
        raise HTTPException(status_code=503, detail="AccountPilot Helper is not connected")
    agent = database.get_local_agent(int(agent_id), user_id=user_id)
    if not agent or agent.get("revoked_at") or agent.get("pairing_status") != "paired":
        raise HTTPException(status_code=503, detail="AccountPilot Helper is not connected")
    return agent


def _latest_connected_agent(user_id: int) -> dict[str, Any]:
    agent = database.get_latest_local_agent(user_id)
    if not agent or agent.get("pairing_status") != "paired":
        raise HTTPException(status_code=503, detail="AccountPilot Helper is not connected")
    return agent


def _latest_user_job(user_id: int, operation: str) -> dict[str, Any] | None:
    return database.get_latest_connector_job_for_user(user_id, operation)


def _public_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {
        "id": job["id"],
        "company_id": job.get("company_id"),
        "commit_run_id": job.get("commit_run_id"),
        "operation": job["operation"],
        "payload": job.get("payload") or {},
        "status": job["status"],
        "attempt_count": job["attempt_count"],
        "lease_expires_at": job.get("lease_expires_at"),
        "result": job.get("result") or {},
        "error_message": job.get("error_message"),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "completed_at": job.get("completed_at"),
    }
