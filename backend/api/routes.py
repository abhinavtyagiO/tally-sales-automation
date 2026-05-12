from __future__ import annotations

from datetime import date
import logging
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from backend import config
from backend.db import database
from backend.services import auth_service, local_agent_service
from backend.services.company_service import company_has_online_agent, require_company
from backend.services.excel_parser import ExcelParseError, parse_excel
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
    user = auth_service.create_login_session(request.id_token, response)
    return {"user": user}


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
    return {
        "companies": companies,
        "active_company_id": _active_company_id(companies),
    }


@router.post("/companies")
def create_company(request: CompanyRequest, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company_name = request.company_name.strip()
    logger.info("company.create.start user_id=%s company_name=%s", user["id"], company_name)
    if not company_name:
        raise HTTPException(status_code=400, detail="Company name is required")
    if any(company["company_name"].lower() == company_name.lower() for company in database.list_companies(user["id"])):
        raise HTTPException(status_code=409, detail="This company is already added")

    agent = _active_tally_agent(user["id"])
    _validate_company_in_tally(agent, company_name, request.tally_url)

    try:
        data = _model_to_dict(request)
        data["company_name"] = company_name
        data["tally_url"] = request.tally_url
        data["local_agent_id"] = agent["id"]
        company = database.create_company(user["id"], data)
        selected = database.select_company(company["id"], user["id"])
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


@router.post("/companies/{company_id}/sync")
def company_sync(company_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    agent = company_has_online_agent(company)
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


@router.post("/companies/{company_id}/imports/upload")
async def upload_company_excel(
    company_id: int,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    agent = _active_tally_agent(user["id"])
    try:
        logger.info("import.upload.sync_start user_id=%s company_id=%s filename=%s", user["id"], company_id, file.filename)
        sync_result = sync_from_tally(company=company, agent=agent)
    except TallyError as exc:
        logger.warning("import.upload.sync_failed user_id=%s company_id=%s filename=%s error=%r", user["id"], company_id, file.filename, exc)
        raise _friendly_tally_exception(exc) from exc
    company = database.get_company(company_id, user_id=user["id"])
    rows = await _parse_upload(file)
    import_record = database.create_import(user["id"], company_id, file.filename, rows)
    try:
        processed = _process_import_rows(company, import_record["id"], user)
    except VoucherBuildError as exc:
        logger.warning("import.upload.validation_failed user_id=%s company_id=%s import_id=%s error=%r", user["id"], company_id, import_record["id"], exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("import.upload.success user_id=%s company_id=%s import_id=%s rows=%s", user["id"], company_id, import_record["id"], len(rows))
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
    company = require_company(user["id"], company_id)
    agent = company_has_online_agent(company)
    try:
        ensure_tally_reachable(user["id"])
    except TallyError as exc:
        logger.warning("import.commit.tally_unreachable user_id=%s company_id=%s import_id=%s error=%r", user["id"], company_id, import_id, exc)
        raise _friendly_tally_exception(exc) from exc
    if not database.get_import(import_id, user["id"], company_id):
        raise HTTPException(status_code=404, detail="Import not found")
    rows = [
        row
        for row in database.list_import_rows(import_id, company_id)
        if row["validation_status"] == "valid"
        and row["commit_status"] != "success"
        and (not request.import_row_ids or row["id"] in request.import_row_ids)
    ]
    _ensure_company_commit_ledgers(company, agent, rows)
    result = build_vouchers([_row_to_sale(row) for row in rows], ensure_ledgers=False, company=company, user_id=user["id"])
    results: list[dict[str, Any]] = []
    logger.info("import.commit.start user_id=%s company_id=%s import_id=%s row_count=%s", user["id"], company_id, import_id, len(rows))
    for voucher in result.vouchers:
        import_row_id = voucher["Source"]["import_row_id"]
        try:
            validate_voucher(voucher)
            response = local_agent_service.dispatch_tally_operation(
                agent,
                "create_sales_voucher",
                {"voucher": voucher, "company_name": company["company_name"], "tally_url": company["tally_url"]},
            )
            database.log_voucher(voucher, response, "success", source=voucher.get("Source"))
            database.update_import_row_commit(import_row_id, "success", None, response)
            results.append({"import_row_id": import_row_id, "status": "success", "response": response})
            logger.info("import.commit.row_success user_id=%s company_id=%s import_id=%s row_id=%s", user["id"], company_id, import_id, import_row_id)
        except (TallyError, VoucherBuildError, ValueError) as exc:
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


async def _parse_upload(file: UploadFile) -> list[dict[str, Any]]:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx or .xls files are supported")
    content = await file.read()
    try:
        return parse_excel(content)
    except ExcelParseError as exc:
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


def _process_import_rows(company: dict[str, Any], import_id: int, user: dict[str, Any]) -> dict[str, Any]:
    rows = database.list_import_rows(import_id, company["id"])
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
    database.update_import_counts(import_id)
    return {
        "import": database.get_import(import_id, user["id"], company["id"]),
        "rows": database.list_import_rows(import_id, company["id"]),
    }


def _ensure_company_commit_ledgers(company: dict[str, Any], agent: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for ledger in required_ledgers_for_rows([_row_to_sale(row) for row in rows], company):
        ledger_name = ledger["ledger_name"]
        group_name = ledger["group_name"]
        if database.get_ledger_by_name(ledger_name, company_id=company["id"]):
            continue
        logger.info("import.commit.create_missing_ledger company_id=%s ledger_name=%s group_name=%s", company["id"], ledger_name, group_name)
        local_agent_service.dispatch_tally_operation(
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
        result = local_agent_service.dispatch_tally_operation(
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
