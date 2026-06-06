from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from backend import config
from backend.services.tally_client import TallyClient, TallyError, _extract_collection, _ledger_details, _stock_group_details, _usable_stock_item_details


app = FastAPI(title="Tally Sales Automation Local Agent", version="0.1.0")


class ExecuteRequest(BaseModel):
    operation: str
    payload: dict[str, Any]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tally/execute")
def execute(request: ExecuteRequest, x_accountpilot_agent_token: Optional[str] = Header(default=None)) -> dict[str, Any]:
    if config.LOCAL_AGENT_TOKEN and x_accountpilot_agent_token != config.LOCAL_AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid local connector token")
    tally_url = request.payload.get("tally_url") or config.TALLY_URL
    company_name = request.payload.get("company_name")
    client = TallyClient(base_url=tally_url)
    try:
        if request.operation == "health_check":
            client.ping()
            return {"status": "connected"}
        if request.operation == "list_companies":
            return {"companies": client.get_companies()}
        if request.operation == "export_collection":
            collection_id = request.payload["collection_id"]
            if collection_id.lower() == "ledger":
                data = client.export_collection(collection_id, company_name)
                ledgers = [_ledger_details(item) for item in _extract_collection(data, "Ledger")]
                ledgers = [ledger for ledger in ledgers if ledger.get("name")]
                return {"ledgers": ledgers, "summary": {"ledger_count": len(ledgers)}}
            if collection_id.lower() == "stockitem":
                data = client.export_stock_items(company_name)
                stock_items = _usable_stock_item_details(_extract_collection(data, "StockItem"))
                return {"stock_items": stock_items, "summary": {"stock_item_count": len(stock_items)}}
            if collection_id.lower() == "stockgroup":
                data = client.export_stock_groups(company_name)
                stock_groups = [_stock_group_details(item) for item in _extract_collection(data, "StockGroup")]
                stock_groups = [item for item in stock_groups if item.get("name")]
                return {"stock_groups": stock_groups, "summary": {"stock_group_count": len(stock_groups)}}
            data = client.export_collection(collection_id, company_name)
            return {"raw": data}
        if request.operation == "sync_stock_items_for_group":
            group_name = str(request.payload.get("group_name") or "").strip()
            if not group_name:
                raise TallyError("Stock group name is required")
            data = client.export_stock_items_for_group(company_name, group_name)
            stock_items = _usable_stock_item_details(_extract_collection(data, "StockItem"))
            return {"stock_items": stock_items, "summary": {"stock_item_count": len(stock_items), "group_name": group_name}}
        if request.operation == "create_sales_voucher":
            return client.create_sales_voucher(request.payload["voucher"], company_name=company_name)
        if request.operation == "create_ledger":
            return client.create_ledger(
                request.payload["name"],
                request.payload["group_name"],
                company_name=company_name,
            )
    except (KeyError, TallyError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=f"Unsupported operation: {request.operation}")
