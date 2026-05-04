from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from backend.db import database
from backend.services import auth_service, local_agent_service
from backend.services.company_service import company_has_online_agent, require_company
from backend.services.excel_parser import ExcelParseError, parse_excel
from backend.services.sync_service import get_cache_snapshot, get_company_cache_snapshot, sync_from_tally
from backend.services.tally_client import TallyClient, TallyError
from backend.services.voucher_builder import VoucherBuildError, build_vouchers, validate_voucher


router = APIRouter()


class AuthRequest(BaseModel):
    id_token: str


class CompanyRequest(BaseModel):
    company_name: str
    tally_url: str = "http://localhost:9000"
    sales_ledger_name: str = "Sales"
    cash_ledger_name: str = "Cash"
    upi_fallback_ledger_name: str = "UPI Sales"
    upi_fallback_group_name: str = "Sundry Debtors"
    local_agent_id: Optional[int] = None


class CompanyUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    tally_url: Optional[str] = None
    sales_ledger_name: Optional[str] = None
    cash_ledger_name: Optional[str] = None
    upi_fallback_ledger_name: Optional[str] = None
    upi_fallback_group_name: Optional[str] = None
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
    return {"companies": database.list_companies(user["id"])}


@router.post("/companies")
def create_company(request: CompanyRequest, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    try:
        company = database.create_company(user["id"], _model_to_dict(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"company": company}


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


@router.post("/companies/{company_id}/imports/upload")
async def upload_company_excel(
    company_id: int,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    require_company(user["id"], company_id)
    rows = await _parse_upload(file)
    import_record = database.create_import(user["id"], company_id, file.filename, rows)
    return {
        "import": import_record,
        "rows": database.list_import_rows(import_record["id"], company_id),
        "count": len(rows),
    }


@router.post("/companies/{company_id}/imports/{import_id}/process")
def process_import(company_id: int, import_id: int, user: dict[str, Any] = Depends(auth_service.get_current_user)) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    if not database.get_import(import_id, user["id"], company_id):
        raise HTTPException(status_code=404, detail="Import not found")
    rows = database.list_import_rows(import_id, company_id)
    result = build_vouchers([_row_to_sale(row) for row in rows], ensure_ledgers=False, company=company, user_id=user["id"])
    vouchers_by_row = {voucher["Source"]["import_row_id"]: voucher for voucher in result.vouchers}
    errors_by_row = {rows[item["row"]]["id"]: item["error"] for item in result.errors if item.get("row") is not None and item["row"] < len(rows)}
    for row in rows:
        voucher = vouchers_by_row.get(row["id"])
        error = errors_by_row.get(row["id"])
        database.update_import_row_validation(row["id"], "valid" if voucher else "invalid", error, voucher)
    database.update_import_counts(import_id)
    return {
        "import": database.get_import(import_id, user["id"], company_id),
        "rows": database.list_import_rows(import_id, company_id),
    }


@router.post("/companies/{company_id}/imports/{import_id}/commit")
def commit_import(
    company_id: int,
    import_id: int,
    request: CommitRequest,
    user: dict[str, Any] = Depends(auth_service.get_current_user),
) -> dict[str, Any]:
    company = require_company(user["id"], company_id)
    agent = company_has_online_agent(company)
    if not database.get_import(import_id, user["id"], company_id):
        raise HTTPException(status_code=404, detail="Import not found")
    rows = [
        row
        for row in database.list_import_rows(import_id, company_id)
        if row["validation_status"] == "valid"
        and row["commit_status"] != "success"
        and (not request.import_row_ids or row["id"] in request.import_row_ids)
    ]
    result = build_vouchers([_row_to_sale(row) for row in rows], ensure_ledgers=True, company=company, user_id=user["id"])
    results: list[dict[str, Any]] = []
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
        except (TallyError, VoucherBuildError, ValueError) as exc:
            database.log_voucher(voucher, {"error": str(exc)}, "failed", source=voucher.get("Source"))
            database.update_import_row_commit(import_row_id, "failed", str(exc))
            results.append({"import_row_id": import_row_id, "status": "failed", "error": str(exc)})
    for error in result.errors:
        row = rows[error["row"]]
        database.update_import_row_commit(row["id"], "failed", error["error"])
        results.append({"import_row_id": row["id"], "status": "failed", "error": error["error"]})
    if rows:
        database.mark_import_completed(import_id)
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
    rows = await _parse_upload(file)
    return {"rows": rows, "count": len(rows)}


@router.post("/process")
def process_rows(request: ProcessRequest) -> dict[str, Any]:
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
    try:
        return sync_from_tally()
    except TallyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/cache")
def cache() -> dict[str, Any]:
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


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)
