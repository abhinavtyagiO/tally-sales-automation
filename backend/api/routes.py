from __future__ import annotations

from datetime import date
import logging
import secrets
import sqlite3
import time
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from backend import config
from backend.db import database
from backend.services import auth_service, local_agent_service
from backend.services.company_service import company_has_online_agent, require_company
from backend.services.connector_job_service import (
    create_list_companies_job,
    create_master_sync_jobs,
    create_stock_group_retry_job,
    create_tally_health_job,
    create_validate_company_job,
    get_company_tally_health_status,
    get_master_sync_status,
    get_tally_company_discovery_status,
    get_validate_company_status,
    poll_connector_job,
    submit_connector_job_result,
)
from backend.services.connector_setup_service import create_setup_session, get_helper_detection_status, get_helper_diagnostics, register_helper
from backend.services.excel_parser import ExcelParseError, parse_excel
from backend.services.gst_invoice import (
    IMPORT_TYPE_GST,
    IMPORT_TYPE_RETAIL,
    GstInvoiceError,
    build_gst_invoices,
    normalize_import_type,
    required_gst_ledgers_for_rows,
    validate_gstin,
)
from backend.services.sync_service import get_cache_snapshot, get_company_cache_snapshot, sync_from_tally
from backend.services.tally_client import TallyClient, TallyError
from backend.services.tally_status_service import ensure_tally_reachable, get_tally_status, list_tally_companies
from backend.services.voucher_builder import VoucherBuildError, build_vouchers, required_ledgers_for_rows, validate_voucher


router = APIRouter()
logger = logging.getLogger(__name__)


class AuthRequest(BaseModel):
    id_token: str


class PaymentLedgerConfig(BaseModel):
    ledger_name: str
    group_name: str = config.DEFAULT_PAYMENT_LEDGER_GROUP


class CompanyRequest(BaseModel):
    company_name: str
    tally_url: str = config.TALLY_URL
    supplier_gstin: Optional[str] = None
    supplier_state: Optional[str] = None
    gst_registration_name: str = config.GST_REGISTRATION_NAME
    gst_registration_type: str = config.GST_REGISTRATION_TYPE
    gst_sales_ledger_name: str = config.GST_SALES_LEDGER_NAME
    cgst_ledger_name: str = config.CGST_LEDGER_NAME
    sgst_ledger_name: str = config.SGST_LEDGER_NAME
    igst_ledger_name: str = config.IGST_LEDGER_NAME
    gst_buyer_ledger_group: str = config.GST_BUYER_LEDGER_GROUP
    sales_ledger_name: str = config.SALES_LEDGER_NAME
    sales_ledger_group_name: str = config.SALES_LEDGER_GROUP
    cash_ledger_name: str = config.CASH_LEDGER_NAME
    cash_ledger_group_name: str = config.CASH_LEDGER_GROUP
    upi_fallback_ledger_name: str = config.UPI_FALLBACK_LEDGER
    upi_fallback_group_name: str = config.UPI_FALLBACK_GROUP
    payment_default_group_name: str = config.DEFAULT_PAYMENT_LEDGER_GROUP
    payment_ledger_mappings: dict[str, PaymentLedgerConfig] = Field(default_factory=dict)
    local_agent_id: Optional[int] = None


class CompanyUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    tally_url: Optional[str] = None
    supplier_gstin: Optional[str] = None
    supplier_state: Optional[str] = None
    gst_registration_name: Optional[str] = None
    gst_registration_type: Optional[str] = None
    gst_sales_ledger_name: Optional[str] = None
    cgst_ledger_name: Optional[str] = None
    sgst_ledger_name: Optional[str] = None
    igst_ledger_name: Optional[str] = None
    gst_buyer_ledger_group: Optional[str] = None
    sales_ledger_name: Optional[str] = None
    sales_ledger_group_name: Optional[str] = None
    cash_ledger_name: Optional[str] = None
    cash_ledger_group_name: Optional[str] = None
    upi_fallback_ledger_name: Optional[str] = None
    upi_fallback_group_name: Optional[str] = None
    payment_default_group_name: Optional[str] = None
    payment_ledger_mappings: Optional[dict[str, PaymentLedgerConfig]] = None
    local_agent_id: Optional[int] = None


class PairingTokenRequest(BaseModel):
    device_name: str = "Local Agent"
    base_url: Optional[str] = None


class PairAgentRequest(BaseModel):
    pairing_token: str
    device_name: Optional[str] = None
    base_url: Optional[str] = None


class HeartbeatRequest(BaseModel):
    agent_id: int
    base_url: Optional[str] = None


class ConnectorPollRequest(BaseModel):
    agent_id: int


class ConnectorJobResultRequest(BaseModel):
    agent_id: int
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


class ConnectorRegisterRequest(BaseModel):
    setup_token: str
    device_name: Optional[str] = None


class ConnectorValidateCompanyRequest(BaseModel):
    company_name: str
    tally_url: str = config.TALLY_URL


class SupportDeleteUserDataRequest(BaseModel):
    email: str
    confirm_email: str


class SaleRow(BaseModel):
    product_name: str
    price: float = Field(gt=0)
    payment_mode: str
    voucher_date: Optional[date] = None
    source_row_id: Optional[str] = None


class ProcessRequest(BaseModel):
    rows: list[SaleRow] = []
    voucher_date: Optional[date] = None
    import_id: Optional[str] = None


class CommitRequest(BaseModel):
    rows: list[SaleRow] = []
    voucher_date: Optional[date] = None
    import_id: Optional[str] = None
    import_row_ids: Optional[list[int]] = None


@router.post("/auth/google")
def google_login(request: AuthRequest, response: Response) -> dict[str, Any]:
    logger.info("auth.login.request_received")
    return auth_service.create_login_session(request.id_token, response)


@router.get("/auth/me")
def auth_me(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    return {"user": user}


@router.post("/auth/logout")
def auth_logout(
    request: Request,
    response: Response,
    _: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, str]:
    auth_service.logout(request, response)
    return {"status": "ok"}


@router.get("/companies")
def list_companies(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    companies = database.list_companies(user["id"])
    logger.info("company.list.completed user_id=%s count=%s active_company_id=%s", user["id"], len(companies), _active_company_id(companies))
    return {
        "companies": companies,
        "active_company_id": _active_company_id(companies),
    }


@router.post("/companies")
def create_company(request: CompanyRequest, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company_name = request.company_name.strip()
    supplier_gstin = (request.supplier_gstin or "").strip().upper()
    supplier_state = (request.supplier_state or "").strip()
    logger.info("company.create.start user_id=%s company_name=%s", user["id"], company_name)
    if not company_name:
        raise HTTPException(status_code=400, detail="Company name is required")
    if not supplier_gstin:
        raise HTTPException(status_code=400, detail="Company GSTIN is required")
    if not validate_gstin(supplier_gstin):
        raise HTTPException(status_code=400, detail="Company GSTIN must be a valid GSTIN")
    if not supplier_state:
        raise HTTPException(status_code=400, detail="Company GST state is required")
    if any(company["company_name"].lower() == company_name.lower() for company in database.list_companies(user["id"])):
        raise HTTPException(status_code=409, detail="This company is already added")

    try:
        agent = _active_tally_agent(user["id"])
        data = _model_to_dict(request)
        data["company_name"] = company_name
        data["tally_url"] = request.tally_url
        data["supplier_gstin"] = supplier_gstin
        data["supplier_state"] = supplier_state
        data["local_agent_id"] = agent["id"]
        if config.CONNECTOR_MODE != "polling":
            _validate_company_in_tally(agent, company_name, request.tally_url)
        company = database.create_company(user["id"], data)
        selected = database.select_company(company["id"], user["id"])
        if config.CONNECTOR_MODE == "polling":
            sync_result = create_master_sync_jobs(user["id"], selected)
            logger.info(
                "company.create.polling_sync_queued user_id=%s company_id=%s agent_id=%s job_count=%s",
                user["id"],
                company["id"],
                agent["id"],
                len(sync_result.get("jobs") or []),
            )
        else:
            try:
                sync_result = sync_from_tally(company=selected, agent=agent)
            except TallyError:
                database.delete_company(company["id"], user["id"])
                raise
        company = database.get_company(company["id"], user_id=user["id"])
        logger.info("company.create.success user_id=%s company_id=%s company_name=%s", user["id"], company["id"], company_name)
    except sqlite3.IntegrityError as exc:
        logger.warning("company.create.failed user_id=%s company_name=%s reason=duplicate", user["id"], company_name)
        raise HTTPException(status_code=409, detail="This company is already added") from exc
    except TallyError as exc:
        logger.warning("company.create.failed user_id=%s company_name=%s error=%r", user["id"], company_name, exc)
        raise _friendly_tally_exception(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("company.create.failed user_id=%s company_name=%s", user["id"], company_name)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"company": company, "sync": sync_result}


@router.get("/tally/status")
def tally_status(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    return get_tally_status(user["id"])


@router.get("/tally/companies")
def tally_companies(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    return list_tally_companies(user["id"])


@router.get("/companies/{company_id}")
def get_company(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    return {"company": require_company(user["id"], company_id)}


@router.patch("/companies/{company_id}")
def update_company(
    company_id: int,
    request: CompanyUpdateRequest,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    require_company(user["id"], company_id)
    company = database.update_company(company_id, user["id"], _model_to_dict(request))
    return {"company": company}


@router.post("/companies/{company_id}/select")
def select_company(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = database.select_company(company_id, user["id"])
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"company": company}


@router.post("/companies/{company_id}/agents/pairing-token")
def create_agent_pairing_token(
    company_id: int,
    request: PairingTokenRequest,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    require_company(user["id"], company_id)
    result = local_agent_service.create_pairing_token(user["id"], request.device_name, request.base_url)
    database.update_company(company_id, user["id"], {"local_agent_id": result["agent"]["id"]})
    return result


@router.post("/agents/pairing-token")
def create_user_agent_pairing_token(
    request: PairingTokenRequest,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    return local_agent_service.create_pairing_token(user["id"], request.device_name, request.base_url)


@router.post("/agents/pair")
def pair_agent(request: PairAgentRequest) -> dict[str, Any]:
    agent = local_agent_service.pair_agent(request.pairing_token, request.device_name, request.base_url)
    return {"agent": agent}


@router.post("/agents/heartbeat")
def heartbeat_agent(request: HeartbeatRequest) -> dict[str, Any]:
    agent = local_agent_service.heartbeat(request.agent_id, base_url=request.base_url)
    return {"agent": agent}


@router.post("/connector/poll")
def connector_poll(
    request: ConnectorPollRequest,
    x_accountpilot_agent_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    return poll_connector_job(request.agent_id, x_accountpilot_agent_token)


@router.post("/connector/setup-session")
def connector_setup_session(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    logger.info("connector.setup_session.requested user_id=%s", user["id"])
    return create_setup_session(user["id"])


@router.get("/connector/status")
def helper_detection_status(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    return get_helper_detection_status(user["id"])


@router.get("/connector/diagnostics")
def helper_diagnostics(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    return get_helper_diagnostics(user["id"])


@router.post("/connector/tally-companies/check")
def create_tally_companies_check(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    job = create_list_companies_job(user["id"])
    return {"job": job, "companies": get_tally_company_discovery_status(user["id"])}


@router.get("/connector/tally-companies")
def connector_tally_companies(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    return get_tally_company_discovery_status(user["id"])


@router.post("/connector/company-validation")
def create_connector_company_validation(
    request: ConnectorValidateCompanyRequest,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    company_name = request.company_name.strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="Company name is required")
    job = create_validate_company_job(user["id"], company_name, request.tally_url)
    return {"job": job, "validation": get_validate_company_status(user["id"], job["id"])}


@router.get("/connector/company-validation/{job_id}")
def connector_company_validation(job_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    return get_validate_company_status(user["id"], job_id)


@router.post("/connector/register")
def connector_register(request: ConnectorRegisterRequest) -> dict[str, Any]:
    logger.info("connector.register.request_received device_name=%s", request.device_name)
    return register_helper(request.setup_token, request.device_name)


@router.post("/connector/jobs/{job_id}/result")
def connector_job_result(
    job_id: int,
    request: ConnectorJobResultRequest,
    x_accountpilot_agent_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    return submit_connector_job_result(
        request.agent_id,
        x_accountpilot_agent_token,
        job_id,
        request.status,
        request.result,
        request.error_message,
    )


@router.post("/support/delete-user-data")
def support_delete_user_data(
    request: SupportDeleteUserDataRequest,
    x_accountpilot_support_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    _require_support_admin_token(x_accountpilot_support_token)
    email = request.email.strip().lower()
    confirm_email = request.confirm_email.strip().lower()
    if not email or email != confirm_email:
        raise HTTPException(status_code=400, detail="Email confirmation does not match")
    result = database.delete_user_data_by_email(email)
    logger.warning(
        "support.delete_user_data.completed email=%s deleted=%s user_ids=%s counts=%s",
        email,
        result["deleted"],
        result.get("user_ids"),
        result.get("counts"),
    )
    return result


@router.post("/support/delete-my-data")
def support_delete_my_data(user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    result = database.delete_user_data(int(user["id"]))
    logger.warning(
        "support.delete_my_data.completed user_id=%s email=%s deleted=%s counts=%s",
        user["id"],
        user.get("email"),
        result["deleted"],
        result.get("counts"),
    )
    return result


@router.post("/companies/{company_id}/agents/{agent_id}/revoke")
def revoke_agent(
    company_id: int,
    agent_id: int,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    require_company(user["id"], company_id)
    if not database.revoke_local_agent(agent_id, user["id"]):
        raise HTTPException(status_code=404, detail="Local agent not found")
    return {"status": "revoked"}


@router.post("/companies/{company_id}/connector/health-check")
def create_connector_health_check(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    job = create_tally_health_job(user["id"], company)
    return {"job": job, "status": get_company_tally_health_status(company_id)}


@router.get("/companies/{company_id}/connector/status")
def connector_status(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    require_company(user["id"], company_id)
    return get_company_tally_health_status(company_id)


@router.post("/companies/{company_id}/connector/sync")
def create_connector_master_sync(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    return create_master_sync_jobs(user["id"], company)


@router.get("/companies/{company_id}/connector/sync")
def connector_master_sync_status(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    require_company(user["id"], company_id)
    return get_master_sync_status(company_id)


@router.post("/companies/{company_id}/sync")
def company_sync(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    agent = company_has_online_agent(company)
    if config.CONNECTOR_MODE == "polling":
        sync_result = create_master_sync_jobs(user["id"], company)
        logger.info(
            "company.sync.polling_sync_queued user_id=%s company_id=%s agent_id=%s job_count=%s",
            user["id"],
            company_id,
            agent["id"],
            len(sync_result.get("jobs") or []),
        )
        return sync_result
    try:
        return sync_from_tally(company=company, agent=agent)
    except TallyError as exc:
        database.set_company_sync(company_id, "failed", company.get("last_sync_at"))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/companies/{company_id}/cache")
def company_cache(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    require_company(user["id"], company_id)
    return get_company_cache_snapshot(company_id)


@router.get("/companies/{company_id}/stock-items")
def company_stock_items(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    items = database.list_stock_items(company_id)
    groups = sorted({item["group_name"] for item in items if item.get("group_name")}, key=str.lower)
    categories = sorted({item["category"] for item in items if item.get("category")}, key=str.lower)
    low_stock_count = sum(1 for item in items if _stock_quantity(item.get("closing_balance")) is not None and _stock_quantity(item.get("closing_balance")) <= 5)
    return {
        "company_id": company_id,
        "company": company["company_name"],
        "last_sync_at": company.get("last_sync_at"),
        "last_sync_status": company.get("last_sync_status"),
        "count": len(items),
        "groups": groups,
        "categories": categories,
        "low_stock_count": low_stock_count,
        "items": items,
    }


@router.get("/companies/{company_id}/stock-groups")
def company_stock_groups(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    groups = database.list_stock_groups(company_id)
    total_items = sum(int(group.get("item_count") or 0) for group in groups)
    failed_count = sum(1 for group in groups if group.get("sync_status") == "failed")
    pending_count = sum(1 for group in groups if group.get("sync_status") in {"pending", "queued", "syncing"})
    return {
        "company_id": company_id,
        "company": company["company_name"],
        "last_sync_at": company.get("last_sync_at"),
        "last_sync_status": company.get("last_sync_status"),
        "count": len(groups),
        "total_items": total_items,
        "failed_count": failed_count,
        "pending_count": pending_count,
        "stock_item_sync_ready": pending_count == 0,
        "groups": groups,
    }


@router.get("/companies/{company_id}/stock-groups/{stock_group_id}/stock-items")
def company_stock_group_items(company_id: int, stock_group_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    group = database.get_stock_group(stock_group_id, company_id)
    if not group:
        raise HTTPException(status_code=404, detail="Stock group not found")
    items = database.list_stock_items_for_group(company_id, stock_group_id)
    low_stock_count = sum(1 for item in items if _stock_quantity(item.get("closing_balance")) is not None and _stock_quantity(item.get("closing_balance")) <= 5)
    return {
        "company_id": company_id,
        "company": company["company_name"],
        "group": group,
        "count": len(items),
        "low_stock_count": low_stock_count,
        "items": items,
    }


@router.get("/companies/{company_id}/stock-group-items")
def company_stock_group_items_by_name(company_id: int, group_name: str = Query(..., min_length=1), user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    group = database.get_stock_group_by_name(group_name, company_id)
    if not group:
        raise HTTPException(status_code=404, detail="Stock group not found")
    items = database.list_stock_items_for_group(company_id, int(group["id"]))
    low_stock_count = sum(1 for item in items if _stock_quantity(item.get("closing_balance")) is not None and _stock_quantity(item.get("closing_balance")) <= 5)
    return {
        "company_id": company_id,
        "company": company["company_name"],
        "group": group,
        "count": len(items),
        "low_stock_count": low_stock_count,
        "items": items,
    }


@router.post("/companies/{company_id}/stock-groups/{stock_group_id}/retry")
def retry_company_stock_group(company_id: int, stock_group_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    job = create_stock_group_retry_job(user["id"], company, stock_group_id)
    return {"job": job, "group": database.get_stock_group(stock_group_id, company_id)}


@router.post("/companies/{company_id}/imports/upload")
async def upload_company_excel(
    company_id: int,
    file: UploadFile = File(...),
    import_type: str = Form(IMPORT_TYPE_RETAIL),
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    started = time.perf_counter()
    company = require_company(user["id"], company_id)
    normalized_import_type = _normalize_import_type_or_400(import_type)
    logger.info(
        "import.upload.start user_id=%s company_id=%s filename=%s import_type=%s connector_mode=%s",
        user["id"],
        company_id,
        file.filename,
        normalized_import_type,
        config.CONNECTOR_MODE,
    )
    if config.CONNECTOR_MODE == "polling":
        company_has_online_agent(company)
        sync_result = get_master_sync_status(company_id)
        if sync_result["status"] == "not_requested" and company.get("last_sync_status") == "success":
            sync_result = {"status": "completed", "message": "Tally masters synced from cache.", "jobs": []}
        elif sync_result["status"] == "not_requested":
            sync_result = create_master_sync_jobs(user["id"], company)
        sync_status = sync_result.get("status")
        sync_state = sync_status.get("status") if isinstance(sync_status, dict) else sync_status
        if sync_state != "completed":
            logger.warning(
                "import.upload.blocked_pending_sync user_id=%s company_id=%s filename=%s sync_status=%s",
                user["id"],
                company_id,
                file.filename,
                sync_state,
            )
            raise HTTPException(status_code=409, detail="Tally master sync is still running. Please try again in a few seconds.")
        if database.list_stock_groups(company_id) and not database.stock_item_sync_is_terminal(company_id):
            logger.warning(
                "import.upload.blocked_pending_stock_items user_id=%s company_id=%s filename=%s",
                user["id"],
                company_id,
                file.filename,
            )
            raise HTTPException(status_code=409, detail="Stock items are still syncing in the background. Upload will unlock once all stock groups finish.")
    else:
        agent = _active_tally_agent(user["id"])
        try:
            logger.info("import.upload.sync_start user_id=%s company_id=%s filename=%s", user["id"], company_id, file.filename)
            sync_result = sync_from_tally(company=company, agent=agent)
        except TallyError as exc:
            logger.warning("import.upload.sync_failed user_id=%s company_id=%s filename=%s error=%r", user["id"], company_id, file.filename, exc)
            raise _friendly_tally_exception(exc) from exc
        company = database.get_company(company_id, user_id=user["id"])
    rows = await _parse_upload(file, normalized_import_type)
    logger.info("import.upload.parsed user_id=%s company_id=%s filename=%s rows=%s", user["id"], company_id, file.filename, len(rows))
    import_record = database.create_import(user["id"], company_id, file.filename, rows, import_type=normalized_import_type)
    try:
        processed = _process_import_rows(company, import_record["id"], user)
    except (VoucherBuildError, GstInvoiceError) as exc:
        logger.warning("import.upload.validation_failed user_id=%s company_id=%s import_id=%s error=%r", user["id"], company_id, import_record["id"], exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "import.upload.completed user_id=%s company_id=%s import_id=%s filename=%s import_type=%s rows=%s duration_ms=%s",
        user["id"],
        company_id,
        import_record["id"],
        file.filename,
        normalized_import_type,
        len(rows),
        duration_ms,
    )
    return {
        "import": processed["import"],
        "count": len(rows),
        "sync": sync_result,
        "rows": processed["rows"],
    }


@router.post("/companies/{company_id}/imports/{import_id}/process")
def process_import(company_id: int, import_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    if not database.get_import(import_id, user["id"], company_id):
        raise HTTPException(status_code=404, detail="Import not found")
    return _process_import_rows(company, import_id, user)


@router.post("/companies/{company_id}/imports/{import_id}/commit")
def commit_import(
    company_id: int,
    import_id: int,
    request: CommitRequest,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    if config.CONNECTOR_MODE == "polling":
        logger.warning("import.commit.blocked_in_polling_mode user_id=%s company_id=%s import_id=%s", user["id"], company_id, import_id)
        raise HTTPException(status_code=409, detail="Use the commit run endpoint when AccountPilot Helper is connected.")
    company = require_company(user["id"], company_id)
    agent = company_has_online_agent(company)
    try:
        ensure_tally_reachable(user["id"])
    except TallyError as exc:
        logger.warning("import.commit.tally_unreachable user_id=%s company_id=%s import_id=%s error=%r", user["id"], company_id, import_id, exc)
        raise _friendly_tally_exception(exc) from exc
    import_record = database.get_import(import_id, user["id"], company_id)
    if not import_record:
        raise HTTPException(status_code=404, detail="Import not found")
    rows = [
        row
        for row in database.list_import_rows(import_id, company_id)
        if row["validation_status"] == "valid"
        and row["commit_status"] != "success"
        and (not request.import_row_ids or row["id"] in request.import_row_ids)
    ]
    is_gst = normalize_import_type(import_record.get("import_type")) == IMPORT_TYPE_GST
    if is_gst:
        _ensure_company_gst_commit_ledgers(company, agent, rows)
        result = build_gst_invoices([_row_to_gst(row) for row in rows], company=company, user_id=user["id"])
    else:
        _ensure_company_commit_ledgers(company, agent, rows)
        result = build_vouchers([_row_to_sale(row) for row in rows], ensure_ledgers=False, company=company, user_id=user["id"])
    results: list[dict[str, Any]] = []
    logger.info("import.commit.start user_id=%s company_id=%s import_id=%s row_count=%s", user["id"], company_id, import_id, len(rows))
    for voucher in result.vouchers:
        import_row_id = voucher["Source"]["import_row_id"]
        try:
            if not is_gst:
                validate_voucher(voucher)
            response = _dispatch_tally_operation(
                agent,
                "create_sales_voucher",
                {"voucher": voucher, "company_name": company["company_name"], "tally_url": company["tally_url"]},
            )
            database.log_voucher(voucher, response, "success", source=voucher.get("Source"))
            database.update_import_row_commit(import_row_id, "success", None, response)
            results.append({"import_row_id": import_row_id, "status": "success", "response": response})
            logger.info("import.commit.row_success user_id=%s company_id=%s import_id=%s row_id=%s", user["id"], company_id, import_id, import_row_id)
        except (TallyError, VoucherBuildError, GstInvoiceError, ValueError) as exc:
            database.log_voucher(voucher, {"error": str(exc)}, "failed", source=voucher.get("Source"))
            database.update_import_row_commit(import_row_id, "failed", str(exc))
            results.append({"import_row_id": import_row_id, "status": "failed", "error": str(exc)})
            logger.warning("import.commit.row_failed user_id=%s company_id=%s import_id=%s row_id=%s error=%r", user["id"], company_id, import_id, import_row_id, exc)
    for error in result.errors:
        row = rows[error["row"]]
        database.update_import_row_commit(row["id"], "failed", error["error"])
        results.append({"import_row_id": row["id"], "status": "failed", "error": error["error"]})
    if rows:
        database.mark_import_completed(import_id)
    logger.info(
        "import.commit.completed user_id=%s company_id=%s import_id=%s success_count=%s failed_count=%s",
        user["id"],
        company_id,
        import_id,
        sum(1 for item in results if item["status"] == "success"),
        sum(1 for item in results if item["status"] == "failed"),
    )
    return {
        "results": results,
        "rows": database.list_import_rows(import_id, company_id),
        "success_count": sum(1 for item in results if item["status"] == "success"),
        "failed_count": sum(1 for item in results if item["status"] == "failed"),
    }


@router.post("/companies/{company_id}/imports/{import_id}/commit-runs")
def start_commit_run(
    company_id: int,
    import_id: int,
    request: CommitRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    logger.info(
        "commit_run.requested user_id=%s company_id=%s import_id=%s requested_row_ids=%s connector_mode=%s",
        user["id"],
        company_id,
        import_id,
        len(request.import_row_ids or []),
        config.CONNECTOR_MODE,
    )
    require_company(user["id"], company_id)
    import_record = database.get_import(import_id, user["id"], company_id)
    if not import_record:
        raise HTTPException(status_code=404, detail="Import not found")
    active_run = database.get_active_commit_run(user["id"], company_id, import_id)
    if active_run:
        logger.info(
            "commit_run.reused_active user_id=%s company_id=%s import_id=%s run_id=%s status=%s",
            user["id"],
            company_id,
            import_id,
            active_run["id"],
            active_run["status"],
        )
        return {"commit_run": _public_commit_run(active_run)}
    total_count = sum(
        1
        for row in database.list_import_rows(import_id, company_id)
        if row["validation_status"] == "valid"
        and row["commit_status"] != "success"
        and (not request.import_row_ids or row["id"] in request.import_row_ids)
    )
    run = database.create_commit_run(user["id"], company_id, import_id, total_count=total_count)
    logger.info(
        "commit_run.created user_id=%s company_id=%s import_id=%s run_id=%s total_count=%s",
        user["id"],
        company_id,
        import_id,
        run["id"],
        total_count,
    )
    if config.CONNECTOR_MODE == "polling":
        _enqueue_polling_commit_run(run["id"], company_id, import_id, request, user)
        run = database.get_commit_run(run["id"], user["id"], company_id)
        return {"commit_run": _public_commit_run(run)}
    if background_tasks is None:
        _complete_commit_run(run["id"], company_id, import_id, request, user)
        run = database.get_commit_run(run["id"], user["id"], company_id)
    else:
        background_tasks.add_task(_complete_commit_run, run["id"], company_id, import_id, request, dict(user))
    return {"commit_run": _public_commit_run(run)}


@router.get("/companies/{company_id}/imports/{import_id}/commit-runs/{run_id}")
def get_commit_run(
    company_id: int,
    import_id: int,
    run_id: int,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    require_company(user["id"], company_id)
    run = database.get_commit_run(run_id, user["id"], company_id)
    if not run or int(run["import_id"]) != import_id:
        raise HTTPException(status_code=404, detail="Commit run not found")
    return {"commit_run": _public_commit_run(run)}


@router.get("/companies/{company_id}/imports")
def list_company_imports(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    require_company(user["id"], company_id)
    return {"imports": database.list_imports(user["id"], company_id)}


@router.get("/companies/{company_id}/imports/{import_id}")
def get_company_import(company_id: int, import_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    require_company(user["id"], company_id)
    import_record = database.get_import(import_id, user["id"], company_id)
    if not import_record:
        raise HTTPException(status_code=404, detail="Import not found")
    return {"import": import_record, "rows": database.list_import_rows(import_id, company_id)}


# Legacy prototype endpoints.
@router.post("/upload-excel")
async def upload_excel(file: UploadFile = File(...)) -> dict[str, Any]:
    _require_legacy_endpoint_enabled()
    rows = await _parse_upload(file)
    return {"rows": rows, "count": len(rows)}


@router.post("/process")
def process_rows(request: ProcessRequest) -> dict[str, Any]:
    _require_legacy_endpoint_enabled()
    try:
        result = build_vouchers(_normalize_rows(request.rows, request.voucher_date, request.import_id), ensure_ledgers=False)
    except VoucherBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "vouchers": result.vouchers,
        "errors": result.errors,
        "ready_count": len(result.vouchers),
        "skipped_count": len(result.errors),
    }


@router.post("/commit")
def commit(request: CommitRequest) -> dict[str, Any]:
    _require_legacy_endpoint_enabled()
    try:
        result = build_vouchers(_normalize_rows(request.rows, request.voucher_date, request.import_id), ensure_ledgers=True)
    except VoucherBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    vouchers = result.vouchers
    build_errors = result.errors

    if not vouchers and build_errors:
        return {"results": [], "build_errors": build_errors, "success_count": 0, "failed_count": 0}
    if not vouchers:
        raise HTTPException(status_code=400, detail="No vouchers to commit")

    tally = TallyClient()
    results: list[dict[str, Any]] = []
    for voucher in vouchers:
        try:
            validate_voucher(voucher)
            response = tally.create_sales_voucher(voucher)
            database.log_voucher(voucher, response, "success", source=voucher.get("Source"))
            results.append({"status": "success", "response": response, "voucher": voucher})
        except (TallyError, VoucherBuildError, ValueError) as exc:
            database.log_voucher(voucher, {"error": str(exc)}, "failed", source=voucher.get("Source"))
            results.append({"status": "failed", "error": str(exc), "voucher": voucher})

    return {
        "results": results,
        "build_errors": build_errors,
        "success_count": sum(1 for item in results if item["status"] == "success"),
        "failed_count": sum(1 for item in results if item["status"] == "failed"),
    }


@router.post("/sync")
def sync() -> dict[str, Any]:
    _require_legacy_endpoint_enabled()
    try:
        return sync_from_tally()
    except TallyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/cache")
def cache() -> dict[str, Any]:
    _require_legacy_endpoint_enabled()
    return get_cache_snapshot()


async def _parse_upload(file: UploadFile, import_type: str = IMPORT_TYPE_RETAIL) -> list[dict[str, Any]]:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx or .xls files are supported")
    content = await file.read()
    try:
        return parse_excel(content, import_type=import_type)
    except ExcelParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _normalize_import_type_or_400(import_type: str | None) -> str:
    try:
        return normalize_import_type(import_type)
    except GstInvoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _normalize_rows(rows: list[SaleRow], voucher_date: Optional[date], import_id: Optional[str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        payload = _model_to_dict(row)
        selected_date = payload.get("voucher_date") or voucher_date
        if selected_date is not None:
            payload["voucher_date"] = selected_date.isoformat()
        if import_id:
            payload["import_id"] = import_id
        payload.setdefault("source_row_id", str(index + 1))
        normalized.append(payload)
    return normalized


def _row_to_sale(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_name": row["product_name"],
        "price": row["price"],
        "payment_mode": row["payment_mode"],
        "voucher_date": row["voucher_date"],
        "source_row_id": row["source_row_id"],
        "import_id": row["import_id"],
        "import_row_id": row["id"],
    }


def _row_to_gst(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_name": row["product_name"],
        "price": row["price"],
        "quantity": row["quantity"],
        "rate": row["rate"] if row.get("rate") is not None else row["price"],
        "payment_mode": row["payment_mode"],
        "voucher_date": row["voucher_date"],
        "buyer_name": row.get("buyer_name"),
        "buyer_gstin": row.get("buyer_gstin"),
        "buyer_state": row.get("buyer_state"),
        "buyer_address": row.get("buyer_address"),
        "place_of_supply": row.get("place_of_supply"),
        "source_row_id": row["source_row_id"],
        "import_id": row["import_id"],
        "import_row_id": row["id"],
    }


def _process_import_rows(company: dict[str, Any], import_id: int, user: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    import_record = database.get_import(import_id, user["id"], company["id"])
    if not import_record:
        raise HTTPException(status_code=404, detail="Import not found")
    rows = database.list_import_rows(import_id, company["id"])
    import_type = normalize_import_type(import_record.get("import_type"))
    logger.info("import.process.start user_id=%s company_id=%s import_id=%s import_type=%s rows=%s", user["id"], company["id"], import_id, import_type, len(rows))
    if import_type == IMPORT_TYPE_GST:
        result = build_gst_invoices([_row_to_gst(row) for row in rows], company=company, user_id=user["id"])
    else:
        result = build_vouchers([_row_to_sale(row) for row in rows], ensure_ledgers=False, company=company, user_id=user["id"])
    vouchers_by_row = {voucher["Source"]["import_row_id"]: voucher for voucher in result.vouchers}
    errors_by_row = {
        rows[item["row"]]["id"]: item["error"]
        for item in result.errors
        if item.get("row") is not None and item["row"] < len(rows)
    }
    for row in rows:
        voucher = vouchers_by_row.get(row["id"])
        error = errors_by_row.get(row["id"])
        database.update_import_row_validation(row["id"], "valid" if voucher else "invalid", error, voucher)
        if voucher and import_type == IMPORT_TYPE_GST:
            database.update_import_row_gst_totals(row["id"], voucher)
    database.update_import_counts(import_id)
    logger.info(
        "import.process.completed user_id=%s company_id=%s import_id=%s import_type=%s rows=%s valid_rows=%s invalid_rows=%s duration_ms=%s",
        user["id"],
        company["id"],
        import_id,
        import_type,
        len(rows),
        len(vouchers_by_row),
        len(errors_by_row),
        int((time.perf_counter() - started) * 1000),
    )
    return {
        "import": database.get_import(import_id, user["id"], company["id"]),
        "rows": database.list_import_rows(import_id, company["id"]),
    }


def _complete_commit_run(run_id: int, company_id: int, import_id: int, request: CommitRequest, user: dict[str, Any]) -> None:
    started = time.perf_counter()
    logger.info("commit_run.direct_processing.start run_id=%s user_id=%s company_id=%s import_id=%s", run_id, user["id"], company_id, import_id)
    database.update_commit_run_status(run_id, "processing")
    try:
        summary = commit_import(company_id, import_id, request, user=user)
        run = database.complete_commit_run(run_id, summary)
        logger.info(
            "commit_run.direct_processing.completed run_id=%s user_id=%s company_id=%s import_id=%s status=%s success_count=%s failed_count=%s duration_ms=%s",
            run_id,
            user["id"],
            company_id,
            import_id,
            run.get("status") if run else None,
            run.get("success_count") if run else None,
            run.get("failed_count") if run else None,
            int((time.perf_counter() - started) * 1000),
        )
    except HTTPException as exc:
        database.fail_commit_run(run_id, str(exc.detail))
        logger.warning("commit_run.direct_processing.failed run_id=%s user_id=%s company_id=%s import_id=%s error=%s", run_id, user["id"], company_id, import_id, exc.detail)
    except Exception as exc:
        logger.exception("commit_run.failed run_id=%s company_id=%s import_id=%s", run_id, company_id, import_id)
        database.fail_commit_run(run_id, str(exc))


def _enqueue_polling_commit_run(run_id: int, company_id: int, import_id: int, request: CommitRequest, user: dict[str, Any]) -> None:
    started = time.perf_counter()
    logger.info("commit_run.polling_enqueue.start run_id=%s user_id=%s company_id=%s import_id=%s", run_id, user["id"], company_id, import_id)
    company = require_company(user["id"], company_id)
    agent_id = company.get("local_agent_id")
    if not agent_id:
        database.fail_commit_run(run_id, "AccountPilot Helper is not connected")
        logger.warning("commit_run.polling_enqueue.failed run_id=%s user_id=%s company_id=%s reason=missing_agent", run_id, user["id"], company_id)
        return
    agent = database.get_local_agent(int(agent_id), user_id=user["id"])
    if not agent or agent.get("pairing_status") != "paired":
        database.fail_commit_run(run_id, "AccountPilot Helper is not connected")
        logger.warning("commit_run.polling_enqueue.failed run_id=%s user_id=%s company_id=%s agent_id=%s reason=agent_not_paired", run_id, user["id"], company_id, agent_id)
        return
    import_record = database.get_import(import_id, user["id"], company_id)
    if not import_record:
        database.fail_commit_run(run_id, "Import not found")
        logger.warning("commit_run.polling_enqueue.failed run_id=%s user_id=%s company_id=%s import_id=%s reason=import_not_found", run_id, user["id"], company_id, import_id)
        return
    rows = [
        row
        for row in database.list_import_rows(import_id, company_id)
        if row["validation_status"] == "valid"
        and row["commit_status"] != "success"
        and (not request.import_row_ids or row["id"] in request.import_row_ids)
    ]
    database.update_commit_run_status(run_id, "processing", total_count=len(rows))
    try:
        is_gst = normalize_import_type(import_record.get("import_type")) == IMPORT_TYPE_GST
        if is_gst:
            result = build_gst_invoices([_row_to_gst(row) for row in rows], company=company, user_id=user["id"])
            required_ledgers = required_gst_ledgers_for_rows([_row_to_gst(row) for row in rows], company)
        else:
            result = build_vouchers([_row_to_sale(row) for row in rows], ensure_ledgers=False, company=company, user_id=user["id"])
            required_ledgers = required_ledgers_for_rows([_row_to_sale(row) for row in rows], company)
        missing_ledger_job_ids = _enqueue_missing_ledger_jobs(
            user_id=user["id"],
            company=company,
            agent_id=int(agent["id"]),
            required_ledgers=required_ledgers,
            commit_run_id=run_id,
        )
        voucher_job_count = 0
        skipped_count = 0
        rows_by_id = {int(row["id"]): row for row in rows}
        for voucher in result.vouchers:
            if not is_gst:
                validate_voucher(voucher)
            source = voucher.get("Source") or {}
            fingerprint = source.get("source_fingerprint")
            import_row_id = source.get("import_row_id")
            if fingerprint and database.successful_fingerprint_exists(str(fingerprint), company_id=company_id):
                if import_row_id:
                    database.update_import_row_commit(int(import_row_id), "success", None, {"status": "already_committed"})
                skipped_count += 1
                logger.info(
                    "commit_run.voucher_skipped_already_committed run_id=%s company_id=%s import_id=%s import_row_id=%s",
                    run_id,
                    company_id,
                    import_id,
                    import_row_id,
                )
                continue
            voucher_required_ledgers = _required_ledgers_for_voucher_row(
                rows_by_id.get(int(import_row_id)) if import_row_id else None,
                company,
                is_gst=is_gst,
            )
            job = database.create_connector_job(
                user_id=user["id"],
                company_id=company_id,
                agent_id=int(agent["id"]),
                operation="create_sales_voucher",
                payload={
                    "voucher": voucher,
                    "company_name": company["company_name"],
                    "tally_url": company["tally_url"],
                    "idempotency_key": fingerprint,
                },
                commit_run_id=run_id,
                depends_on_job_ids=_ledger_dependency_ids(voucher_required_ledgers, missing_ledger_job_ids),
            )
            voucher_job_count += 1
            logger.info(
                "commit_run.voucher_job_queued run_id=%s user_id=%s company_id=%s import_id=%s import_row_id=%s job_id=%s depends_on_job_ids=%s",
                run_id,
                user["id"],
                company_id,
                import_id,
                import_row_id,
                job["id"],
                job.get("depends_on_job_ids"),
            )
        for error in result.errors:
            row = rows[error["row"]]
            database.update_import_row_commit(row["id"], "failed", error["error"])
            logger.warning("commit_run.row_build_failed run_id=%s company_id=%s import_id=%s row_id=%s error=%s", run_id, company_id, import_id, row["id"], error["error"])
        run = database.refresh_commit_run_from_rows(run_id)
        logger.info(
            "commit_run.polling_enqueue.completed run_id=%s user_id=%s company_id=%s import_id=%s import_type=%s total_rows=%s ledger_jobs=%s voucher_jobs=%s skipped_count=%s build_errors=%s status=%s duration_ms=%s",
            run_id,
            user["id"],
            company_id,
            import_id,
            import_record.get("import_type"),
            len(rows),
            len(missing_ledger_job_ids),
            voucher_job_count,
            skipped_count,
            len(result.errors),
            run.get("status") if run else None,
            int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        logger.exception("commit_run.enqueue_failed run_id=%s company_id=%s import_id=%s", run_id, company_id, import_id)
        database.fail_commit_run(run_id, str(exc))


def _enqueue_missing_ledger_jobs(
    user_id: int,
    company: dict[str, Any],
    agent_id: int,
    required_ledgers: list[dict[str, str]],
    commit_run_id: int,
) -> dict[str, int]:
    created_job_ids: dict[str, int] = {}
    for ledger in required_ledgers:
        ledger_name = ledger["ledger_name"].strip()
        group_name = ledger["group_name"].strip()
        if not ledger_name or database.get_ledger_by_name(ledger_name, company_id=company["id"]):
            continue
        job = database.create_connector_job(
            user_id=user_id,
            company_id=int(company["id"]),
            agent_id=agent_id,
            operation="create_ledger",
            payload={
                "name": ledger_name,
                "group_name": group_name,
                "company_name": company["company_name"],
                "tally_url": company["tally_url"],
            },
            commit_run_id=commit_run_id,
        )
        created_job_ids[_ledger_key(ledger_name)] = int(job["id"])
        logger.info(
            "commit_run.create_missing_ledger_queued run_id=%s company_id=%s ledger_name=%s group_name=%s job_id=%s",
            commit_run_id,
            company["id"],
            ledger_name,
            group_name,
            job["id"],
        )
    return created_job_ids


def _required_ledgers_for_voucher_row(row: dict[str, Any] | None, company: dict[str, Any], is_gst: bool) -> list[dict[str, str]]:
    if not row:
        return []
    if is_gst:
        return required_gst_ledgers_for_rows([_row_to_gst(row)], company)
    return required_ledgers_for_rows([_row_to_sale(row)], company)


def _ledger_dependency_ids(required_ledgers: list[dict[str, str]], missing_ledger_job_ids: dict[str, int]) -> list[int]:
    dependency_ids: list[int] = []
    for ledger in required_ledgers:
        job_id = missing_ledger_job_ids.get(_ledger_key(ledger.get("ledger_name")))
        if job_id and job_id not in dependency_ids:
            dependency_ids.append(job_id)
    return dependency_ids


def _ledger_key(name: Any) -> str:
    return str(name or "").strip().lower()


def _public_commit_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    result = run.get("result") or {}
    return {
        "id": run["id"],
        "company_id": run["company_id"],
        "import_id": run["import_id"],
        "status": run["status"],
        "total_count": run["total_count"],
        "success_count": run["success_count"],
        "failed_count": run["failed_count"],
        "error_message": run.get("error_message"),
        "result": result,
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
        "completed_at": run.get("completed_at"),
    }


def _ensure_company_commit_ledgers(company: dict[str, Any], agent: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for ledger in required_ledgers_for_rows([_row_to_sale(row) for row in rows], company):
        ledger_name = ledger["ledger_name"]
        group_name = ledger["group_name"]
        if database.get_ledger_by_name(ledger_name, company_id=company["id"]):
            continue
        logger.info("import.commit.create_missing_ledger company_id=%s ledger_name=%s group_name=%s", company["id"], ledger_name, group_name)
        _dispatch_tally_operation(
            agent,
            "create_ledger",
            {
                "name": ledger_name,
                "group_name": group_name,
                "company_name": company["company_name"],
                "tally_url": company["tally_url"],
            },
        )
        database.upsert_ledger(ledger_name, group_name, company_id=company["id"])


def _ensure_company_gst_commit_ledgers(company: dict[str, Any], agent: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for ledger in required_gst_ledgers_for_rows([_row_to_gst(row) for row in rows], company):
        ledger_name = ledger["ledger_name"]
        group_name = ledger["group_name"]
        if database.get_ledger_by_name(ledger_name, company_id=company["id"]):
            continue
        logger.info("import.commit.create_missing_gst_ledger company_id=%s ledger_name=%s group_name=%s", company["id"], ledger_name, group_name)
        _dispatch_tally_operation(
            agent,
            "create_ledger",
            {
                "name": ledger_name,
                "group_name": group_name,
                "company_name": company["company_name"],
                "tally_url": company["tally_url"],
            },
        )
        database.upsert_ledger(ledger_name, group_name, company_id=company["id"])


def _active_company_id(companies: list[dict[str, Any]]) -> int | None:
    selected = next((company for company in companies if company.get("last_selected_at")), None)
    selected = selected or (companies[0] if companies else None)
    return selected["id"] if selected else None


def _dispatch_tally_operation(agent: dict[str, Any], operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not agent.get("direct_tally"):
        return local_agent_service.dispatch_tally_operation(agent, operation, payload)

    tally = TallyClient(str(payload.get("tally_url") or agent.get("base_url") or config.TALLY_URL))
    company_name = payload.get("company_name")
    if operation == "health_check":
        tally.ping()
        return {"status": "connected"}
    if operation == "list_companies":
        return {"companies": tally.get_companies()}
    if operation == "export_collection":
        collection_id = str(payload["collection_id"])
        current_company = str(company_name) if company_name else None
        if collection_id.lower() == "ledger":
            return {"ledgers": tally.get_all_ledgers(current_company)}
        if collection_id.lower() == "stockitem":
            return {"stock_items": tally.get_all_stock_items(current_company)}
        return tally.export_collection(collection_id, current_company or "")
    if operation == "create_ledger":
        return tally.create_ledger(str(payload["name"]), str(payload["group_name"]), company_name=str(company_name) if company_name else None)
    if operation == "create_sales_voucher":
        return tally.create_sales_voucher(payload["voucher"], company_name=str(company_name) if company_name else None)
    raise TallyError(f"Unsupported direct Tally operation: {operation}")


def _active_tally_agent(user_id: int) -> dict[str, Any]:
    try:
        return ensure_tally_reachable(user_id)
    except TallyError as exc:
        logger.warning("tally.active_agent.failed user_id=%s error=%r", user_id, exc)
        raise _friendly_tally_exception(exc) from exc


def _friendly_tally_exception(exc: TallyError) -> HTTPException:
    message = str(exc)
    lowered = message.lower()
    if "not available" in lowered or "no base_url" in lowered or "connection refused" in lowered:
        return HTTPException(
            status_code=503,
            detail="Can't connect to Tally right now. Please try again or contact support.",
        )
    if "tally request failed" in lowered or "bad gateway" in lowered:
        return HTTPException(
            status_code=503,
            detail="Can't connect to Tally right now. Please try again or contact support.",
        )
    return HTTPException(status_code=502, detail="Tally action failed. Please try again or contact support.")


def _require_support_admin_token(token: str | None) -> None:
    expected = config.SUPPORT_ADMIN_TOKEN
    if not expected:
        raise HTTPException(status_code=404, detail="Support cleanup is not configured")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid support token")


def _stock_quantity(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).split()[0].replace(",", ""))
    except (TypeError, ValueError, IndexError):
        return None


def _ensure_local_agent(user_id: int, base_url: str) -> dict[str, Any]:
    try:
        pairing = local_agent_service.create_pairing_token(user_id, "Local Tally machine", base_url)
        return local_agent_service.pair_agent(pairing["pairing_token"], "Local Tally machine", base_url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Local agent setup failed: {exc}") from exc


def _validate_company_in_tally(agent: dict[str, Any], company_name: str, tally_url: str) -> None:
    try:
        result = _dispatch_tally_operation(
            agent,
            "export_collection",
            {"collection_id": "Ledger", "company_name": company_name, "tally_url": tally_url},
        )
    except TallyError as exc:
        message = str(exc)
        logger.warning("company.validate_in_tally.failed company_name=%s tally_url=%s error=%r", company_name, tally_url, exc)
        if "Tally request failed" in message or "Bad Gateway" in message:
            raise HTTPException(status_code=503, detail="Tally is unreachable. Make sure Tally is open and listening on the configured URL.") from exc
        if "Failed to establish a new connection" in message or "Connection refused" in message:
            raise HTTPException(status_code=503, detail="Local agent is unreachable") from exc
        raise HTTPException(status_code=502, detail=message) from exc

    ledgers = result.get("ledgers") or []
    if not ledgers:
        logger.warning("company.validate_in_tally.not_found company_name=%s tally_url=%s", company_name, tally_url)
        raise HTTPException(status_code=404, detail="Company not found in Tally or no ledgers were returned")
    logger.info("company.validate_in_tally.success company_name=%s ledger_count=%s", company_name, len(ledgers))


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)


def _require_legacy_endpoint_enabled() -> None:
    if not config.LEGACY_ENDPOINTS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
