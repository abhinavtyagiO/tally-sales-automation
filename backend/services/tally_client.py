from __future__ import annotations

import json
from typing import Any
import xml.etree.ElementTree as ET

import requests

from backend import config


class TallyError(RuntimeError):
    pass


class TallyClient:
    def __init__(self, base_url: str = config.TALLY_URL, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if config.TALLY_TRANSPORT == "json":
            response = requests.post(self.base_url, json=payload, timeout=self.timeout)
        else:
            response = requests.post(
                self.base_url,
                data=_dict_to_xml(payload),
                headers={"Content-Type": "text/xml"},
                timeout=self.timeout,
            )
        response.raise_for_status()
        data = _parse_response(response.text)
        self._raise_for_tally_error(data)
        return data

    @staticmethod
    def _envelope(tally_request: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "Envelope": {
                "Header": {"TallyRequest": tally_request},
                "Body": body,
            }
        }

    @staticmethod
    def _raise_for_tally_error(data: dict[str, Any]) -> None:
        status = _find_first(data, "STATUS")
        errors = _find_first(data, "ERRORS")
        line_error = _find_first(data, "LINEERROR")
        if str(status).lower() in {"0", "failed", "failure", "error"}:
            raise TallyError(f"Tally request failed: {data}")
        if errors not in (None, "", 0, "0"):
            raise TallyError(f"Tally returned errors: {data}")
        if line_error:
            raise TallyError(f"Tally line error: {line_error}")

    def export_data(self, report_name: str) -> dict[str, Any]:
        payload = self._envelope(
            "Export Data",
            {
                "ExportData": {
                    "ReportName": report_name,
                    "Format": "JSON",
                }
            },
        )
        return self._post(payload)

    def export_collection(self, collection_id: str, company_name: str) -> dict[str, Any]:
        payload = {
            "Envelope": {
                "Header": {
                    "Version": "1",
                    "TallyRequest": "Export",
                    "Type": "Collection",
                    "ID": collection_id,
                },
                "Body": {
                    "Desc": {
                        "StaticVariables": {
                            "SVExportFormat": "XML",
                            "SVCurrentCompany": company_name,
                        }
                    }
                },
            }
        }
        return self._post(payload)

    def import_data(self, entity_name: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = self._envelope(
            "Import Data",
            {
                "ImportData": {
                    "Entity": entity_name,
                    "Data": data,
                }
            },
        )
        return self._post(payload)

    def get_all_ledgers(self, company_name: str | None = None) -> list[dict[str, Any]]:
        data = self.export_collection("Ledger", company_name) if company_name else self.export_data("Ledgers")
        ledgers = _extract_collection(data, "Ledger")
        return [
            {
                "name": _get_ci(item, "Name"),
                "group": _get_ci(item, "Parent") or _get_ci(item, "Group"),
            }
            for item in ledgers
            if _get_ci(item, "Name")
        ]

    def get_all_stock_items(self, company_name: str | None = None) -> list[str]:
        data = self.export_collection("StockItem", company_name) if company_name else self.export_data("Stock Items")
        items = _extract_collection(data, "StockItem")
        return [str(_get_ci(item, "Name")) for item in items if _get_ci(item, "Name")]

    def get_company_name(self) -> str | None:
        data = self.export_data("Company")
        company = _find_first(data, "CompanyName") or _find_first(data, "Name")
        return str(company) if company else None

    def create_ledger(self, name: str, group_name: str, company_name: str | None = None) -> dict[str, Any]:
        data = {
            "Ledger": {
                "Name": name,
                "Parent": group_name,
            }
        }
        if company_name:
            data["StaticVariables"] = {"SVCurrentCompany": company_name}
        return self.import_data(
            "Ledger",
            data,
        )

    def create_sales_voucher(self, voucher: dict[str, Any], company_name: str | None = None) -> dict[str, Any]:
        clean_voucher = {key: value for key, value in voucher.items() if key != "Source"}
        data = {"Voucher": clean_voucher}
        if company_name:
            data["StaticVariables"] = {"SVCurrentCompany": company_name}
        return self.import_data("Voucher", data)


def _find_first(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key.lower() == key.lower():
                return current_value
            found = _find_first(current_value, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_first(item, key)
            if found is not None:
                return found
    return None


def _extract_collection(data: dict[str, Any], entity_name: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key.lower() == entity_name.lower():
                    if isinstance(nested, list):
                        matches.extend(item for item in nested if isinstance(item, dict))
                    elif isinstance(nested, dict):
                        matches.append(nested)
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return matches


def _get_ci(value: dict[str, Any], key: str) -> Any:
    for current_key, current_value in value.items():
        if current_key.lower() == key.lower():
            return current_value
    return None


def _parse_response(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise TallyError(f"Tally returned unsupported response: {text[:500]}") from exc
    return _xml_element_to_dict(root)


def _xml_element_to_dict(element: ET.Element) -> dict[str, Any] | str:
    children = list(element)
    if not children:
        return (element.text or "").strip()

    result: dict[str, Any] = {}
    for child in children:
        child_value = _xml_element_to_dict(child)
        if child.tag in result:
            current = result[child.tag]
            if not isinstance(current, list):
                result[child.tag] = [current]
            result[child.tag].append(child_value)
        else:
            result[child.tag] = child_value
    return {element.tag: result}


def _dict_to_xml(payload: dict[str, Any]) -> str:
    if len(payload) != 1:
        raise TallyError("Tally XML payload must have one root element")
    root_name, root_value = next(iter(payload.items()))
    root = ET.Element(str(root_name).upper())
    _append_xml_value(root, root_value)
    return ET.tostring(root, encoding="unicode")


def _append_xml_value(parent: ET.Element, value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            child = ET.SubElement(parent, str(key).upper())
            _append_xml_value(child, nested)
    elif isinstance(value, list):
        singular = parent.tag[:-1] if parent.tag.endswith("S") else "ITEM"
        for item in value:
            child = ET.SubElement(parent, singular)
            _append_xml_value(child, item)
    else:
        parent.text = "" if value is None else str(value)
