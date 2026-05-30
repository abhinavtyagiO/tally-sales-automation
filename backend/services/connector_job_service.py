from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any

from fastapi import HTTPException

from backend.db import database


logger = logging.getLogger(__name__)

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
    job = database.create_connector_job(
        user_id=user_id,
        company_id=int(company["id"]),
        agent_id=int(agent["id"]),
        operation=HEALTH_CHECK_OPERATION,
        payload={
            "company_name": company["company_name"],
            "tally_url": company["tally_url"],
        },
    )
    logger.info("connector.job.created operation=%s user_id=%s company_id=%s agent_id=%s job_id=%s", HEALTH_CHECK_OPERATION, user_id, company["id"], agent["id"], job["id"])
    return job


def create_list_companies_job(user_id: int) -> dict[str, Any]:
    agent = _latest_connected_agent(user_id)
    job = database.create_connector_job(
        user_id=user_id,
        company_id=None,
        agent_id=int(agent["id"]),
        operation=LIST_COMPANIES_OPERATION,
        payload={},
    )
    logger.info("connector.job.created operation=%s user_id=%s agent_id=%s job_id=%s", LIST_COMPANIES_OPERATION, user_id, agent["id"], job["id"])
    return job


def create_validate_company_job(user_id: int, company_name: str, tally_url: str) -> dict[str, Any]:
    agent = _latest_connected_agent(user_id)
    job = database.create_connector_job(
        user_id=user_id,
        company_id=None,
        agent_id=int(agent["id"]),
        operation=VALIDATE_COMPANY_OPERATION,
        payload={"company_name": company_name, "tally_url": tally_url},
    )
    logger.info("connector.job.created operation=%s user_id=%s agent_id=%s job_id=%s company_name=%s", VALIDATE_COMPANY_OPERATION, user_id, agent["id"], job["id"], company_name)
    return job


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
    logger.info(
        "connector.jobs.created operation=master_sync user_id=%s company_id=%s agent_id=%s job_ids=%s,%s",
        user_id,
        company["id"],
        agent["id"],
        ledgers_job["id"],
        stock_job["id"],
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
    if job:
        logger.info("connector.job.leased agent_id=%s job_id=%s operation=%s company_id=%s", agent["id"], job["id"], job["operation"], job.get("company_id"))
    return {"job": _public_job(job) if job else None}


def submit_connector_job_result(agent_id: int, token: str | None, job_id: int, status: str, result: dict[str, Any] | None, error_message: str | None) -> dict[str, Any]:
    agent = authenticate_connector(agent_id, token)
    result = result or {}
    if status == "success":
        job = database.complete_connector_job(job_id, int(agent["id"]), _result_for_persistence(job_id, result))
    elif status == "failed":
        job = database.fail_connector_job(job_id, int(agent["id"]), error_message or "Connector job failed", _failed_result_for_persistence(result))
    else:
        raise HTTPException(status_code=400, detail="Unsupported connector job result status")
    if not job:
        raise HTTPException(status_code=404, detail="Connector job not found")
    import_row_id = _job_import_row_id(job)
    logger.info(
        "connector.job.result agent_id=%s user_id=%s job_id=%s operation=%s status=%s company_id=%s commit_run_id=%s import_row_id=%s result_bytes=%s persisted_result_bytes=%s",
        agent["id"],
        agent.get("user_id"),
        job["id"],
        job["operation"],
        status,
        job.get("company_id"),
        job.get("commit_run_id"),
        import_row_id,
        _json_size(result),
        _json_size(job.get("result") or {}),
    )
    database.update_local_agent_activity(int(agent["id"]), None if status == "success" else error_message)
    job_for_apply = dict(job)
    job_for_apply["result"] = result
    _apply_job_result(job_for_apply)
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
            run = database.refresh_commit_run_from_rows(int(job["commit_run_id"]))
            _log_commit_run_progress(run, reason="voucher_failed")
        return
    if job["status"] == "failed" and job.get("company_id") and job["operation"] == "create_ledger":
        if job.get("commit_run_id"):
            run = database.refresh_commit_run_from_rows(int(job["commit_run_id"]))
            _log_commit_run_progress(run, reason="ledger_failed")
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
        ledgers = result.get("ledgers") or []
        logger.info("connector.master_apply operation=%s company_id=%s count=%s", job["operation"], company_id, len(ledgers))
        database.replace_ledgers(ledgers, company_id=company_id)
    elif job["operation"] == SYNC_STOCK_ITEMS_OPERATION:
        stock_items = result.get("stock_items") or []
        logger.info("connector.master_apply operation=%s company_id=%s count=%s", job["operation"], company_id, len(stock_items))
        database.replace_stock_items(stock_items, company_id=company_id)
    elif job["operation"] == "create_ledger":
        database.upsert_ledger(str(payload["name"]), str(payload["group_name"]), company_id=company_id)
        return
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
            run = database.refresh_commit_run_from_rows(int(job["commit_run_id"]))
            _log_commit_run_progress(run, reason="voucher_completed")
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


def _job_import_row_id(job: dict[str, Any]) -> Any:
    source = (((job.get("payload") or {}).get("voucher") or {}).get("Source") or {})
    return source.get("import_row_id")


def _log_commit_run_progress(run: dict[str, Any] | None, reason: str) -> None:
    if not run:
        return
    logger.info(
        "commit_run.progress reason=%s run_id=%s user_id=%s company_id=%s import_id=%s status=%s total_count=%s success_count=%s failed_count=%s",
        reason,
        run.get("id"),
        run.get("user_id"),
        run.get("company_id"),
        run.get("import_id"),
        run.get("status"),
        run.get("total_count"),
        run.get("success_count"),
        run.get("failed_count"),
    )


def _result_for_persistence(job_id: int, result: dict[str, Any]) -> dict[str, Any]:
    job = database.get_connector_job(job_id)
    operation = job.get("operation") if job else None
    if operation == SYNC_LEDGERS_OPERATION:
        return {"summary": {"ledger_count": len(result.get("ledgers") or [])}}
    if operation == SYNC_STOCK_ITEMS_OPERATION:
        return {"summary": {"stock_item_count": len(result.get("stock_items") or [])}}
    return result


def _failed_result_for_persistence(result: dict[str, Any]) -> dict[str, Any]:
    detail = result.get("detail")
    return {"detail": str(detail)[:500]} if detail else {}


def _json_size(value: dict[str, Any]) -> int:
    try:
        return len(json.dumps(value, separators=(",", ":")))
    except (TypeError, ValueError):
        return 0


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
