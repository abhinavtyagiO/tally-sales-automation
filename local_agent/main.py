from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend import config
from backend.services.tally_client import TallyClient, TallyError


app = FastAPI(title="Tally Sales Automation Local Agent", version="0.1.0")


class ExecuteRequest(BaseModel):
    operation: str
    payload: dict[str, Any]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tally/execute")
def execute(request: ExecuteRequest) -> dict[str, Any]:
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
            data = client.export_collection(collection_id, company_name)
            if collection_id.lower() == "ledger":
                return {"ledgers": client.get_all_ledgers(company_name), "raw": data}
            if collection_id.lower() == "stockitem":
                return {"stock_items": client.get_all_stock_items(company_name), "raw": data}
            return {"raw": data}
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
