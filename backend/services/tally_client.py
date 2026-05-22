from __future__ import annotations

import json
import re
from typing import Any
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import requests

from backend import config


class TallyError(RuntimeError):
    pass


class TallyClient:
    def __init__(self, base_url: str = config.TALLY_URL, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
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
        except requests.RequestException as exc:
            raise TallyError(f"Tally request failed: {exc}") from exc
        data = _parse_response(response.text)
        self._raise_for_tally_error(data)
        return data

    def _post_xml(self, xml: str) -> dict[str, Any]:
        try:
            response = requests.post(
                self.base_url,
                data=xml,
                headers={"Content-Type": "text/xml"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TallyError(f"Tally request failed: {exc}") from exc
        data = _parse_response(response.text)
        self._raise_for_tally_error(data)
        return data

    def ping(self) -> bool:
        try:
            response = requests.get(self.base_url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise TallyError(f"Tally request failed: {exc}") from exc
        return "TallyPrime Server is Running" in response.text or response.status_code == 200

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
        exceptions = _find_first(data, "EXCEPTIONS")
        line_error = _find_first(data, "LINEERROR")
        if line_error:
            raise TallyError(_friendly_tally_line_error(str(line_error)))
        if str(status).lower() in {"0", "failed", "failure", "error"}:
            raise TallyError(f"Tally request failed: {data}")
        if errors not in (None, "", 0, "0"):
            raise TallyError(f"Tally returned errors: {data}")
        if exceptions not in (None, "", 0, "0"):
            raise TallyError(f"Tally returned exceptions: {data}")

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
                "name": _text_value(_get_ci(item, "Name") or _find_first(item, "Name")),
                "group": _text_value(_get_ci(item, "Parent") or _get_ci(item, "Group")),
            }
            for item in ledgers
            if _text_value(_get_ci(item, "Name") or _find_first(item, "Name"))
        ]

    def get_all_stock_items(self, company_name: str | None = None) -> list[dict[str, Any]]:
        data = self.export_stock_items(company_name) if company_name else self.export_data("Stock Items")
        items = _extract_collection(data, "StockItem")
        return [
            _stock_item_details(item)
            for item in items
            if _text_value(_get_ci(item, "Name") or _find_first(item, "Name"))
        ]

    def export_stock_items(self, company_name: str | None = None) -> dict[str, Any]:
        return self._post_xml(_stock_items_collection_xml(company_name))

    def get_company_name(self) -> str | None:
        data = self.export_data("Company")
        company = _find_first(data, "CompanyName") or _find_first(data, "Name")
        return str(company) if company else None

    def get_companies(self) -> list[str]:
        try:
            data = self._post_xml(_companies_collection_xml())
        except TallyError:
            return []
        companies = _extract_collection(data, "Company")
        names = [
            _text_value(_get_ci(item, "Name") or _get_ci(item, "CompanyName"))
            for item in companies
            if _text_value(_get_ci(item, "Name") or _get_ci(item, "CompanyName"))
        ]
        if names:
            return sorted(set(names), key=str.lower)
        company = self.get_company_name()
        return [company] if company else []

    def create_ledger(self, name: str, group_name: str, company_name: str | None = None) -> dict[str, Any]:
        return self._post_xml(_ledger_master_xml(name, group_name, company_name))

    def create_sales_voucher(self, voucher: dict[str, Any], company_name: str | None = None) -> dict[str, Any]:
        if voucher.get("VoucherKind") == "gst_tax_invoice":
            return self._post_xml(_gst_sales_voucher_xml(voucher, company_name))
        return self._post_xml(_sales_voucher_xml(voucher, company_name))


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


def _find_first_text(value: Any, key: str) -> str | None:
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key.lower() == key.lower():
                text = _text_value(current_value)
                if text:
                    return text
            found = _find_first_text(current_value, key)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_first_text(item, key)
            if found:
                return found
    return None


def _extract_collection(data: dict[str, Any], entity_name: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key.lower() == entity_name.lower():
                    if isinstance(nested, list):
                        matches.extend(_unwrap_entity(item, entity_name) for item in nested if isinstance(item, dict))
                    elif isinstance(nested, dict):
                        matches.append(_unwrap_entity(nested, entity_name))
                    continue
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return matches


def _unwrap_entity(value: dict[str, Any], entity_name: str) -> dict[str, Any]:
    nested = _get_ci(value, entity_name)
    return nested if isinstance(nested, dict) else value


def _get_ci(value: dict[str, Any], key: str) -> Any:
    for current_key, current_value in value.items():
        if current_key.lower() == key.lower():
            return current_value
    return None


def _text_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        nested = _get_ci(value, "Value") or _get_ci(value, "Name")
        return _text_value(nested)
    if isinstance(value, list):
        for item in value:
            text = _text_value(item)
            if text:
                return text
        return None
    return str(value)


def _stock_item_details(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _text_value(_get_ci(item, "Name") or _find_first(item, "Name")),
        "group_name": _text_value(_get_ci(item, "Parent") or _get_ci(item, "Group")),
        "category": _text_value(_get_ci(item, "Category") or _get_ci(item, "StockCategory")),
        "base_unit": _text_value(_get_ci(item, "BaseUnits") or _get_ci(item, "BaseUnit")),
        "additional_unit": _text_value(_get_ci(item, "AdditionalUnits") or _get_ci(item, "AdditionalUnit")),
        "opening_balance": _text_value(_get_ci(item, "OpeningBalance")),
        "closing_balance": _text_value(_get_ci(item, "ClosingBalance")),
        "opening_value": _text_value(_get_ci(item, "OpeningValue")),
        "closing_value": _text_value(_get_ci(item, "ClosingValue")),
        "opening_rate": _text_value(_get_ci(item, "OpeningRate")),
        "closing_rate": _text_value(_get_ci(item, "ClosingRate")),
        "gst_type": _text_value(_get_ci(item, "GSTTypeOfSupply") or _get_ci(item, "GSTOVRDNTYPEOFSUPPLY") or _find_first(item, "GSTTypeOfSupply")),
        "gst_rate": _extract_gst_rate(item),
        "hsn_code": _text_value(
            _get_ci(item, "GSTHSNName")
            or _get_ci(item, "GSTHSNSACCode")
            or _get_ci(item, "HSNCode")
            or _find_first_text(item, "GSTHSNName")
            or _find_first_text(item, "GSTHSNSACCode")
            or _find_first_text(item, "HSNCode")
        ),
        "hsn_description": _text_value(_get_ci(item, "GSTHSNDescription") or _find_first_text(item, "GSTHSNDescription")),
        "taxability": _text_value(_get_ci(item, "GSTOVRDNTaxability") or _get_ci(item, "Taxability") or _find_first(item, "GSTOVRDNTaxability") or _find_first(item, "Taxability")),
        "raw": item,
    }


def _extract_gst_rate(item: dict[str, Any]) -> float | None:
    rates_by_head: dict[str, float] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            duty_head = _text_value(_get_ci(value, "GSTRateDutyHead") or _get_ci(value, "DutyHead"))
            rate = _text_value(_get_ci(value, "GSTRate") or _get_ci(value, "Rate") or _get_ci(value, "GSTRateValuationType"))
            if duty_head and rate:
                parsed = _parse_rate_number(rate)
                if parsed is not None:
                    rates_by_head[duty_head.lower()] = parsed
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(item)
    if rates_by_head:
        igst = rates_by_head.get("igst")
        if igst and igst > 0:
            return igst
        return sum(rate for head, rate in rates_by_head.items() if head in {"cgst", "sgst/utgst", "sgst", "utgst"})

    for key in ("GSTRate", "RateOfGST", "RateOfTaxCalculation", "RateOfVAT"):
        parsed = _parse_rate_number(_text_value(_find_first(item, key)))
        if parsed is not None:
            return parsed
    return None


def _parse_rate_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _parse_response(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except ValueError:
        pass
    text = _sanitize_xml(text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise TallyError(f"Tally returned unsupported response: {text[:500]}") from exc
    parsed = _xml_element_to_dict(root)
    if not isinstance(parsed, dict):
        raise TallyError(f"Tally request failed: {parsed}")
    return parsed


def _sanitize_xml(text: str) -> str:
    text = re.sub(r"&#(?:0*4|x0*4);", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<(/?)UDF:", r"<\1UDF_", text)
    return "".join(
        char
        for char in text
        if char in {"\t", "\n", "\r"} or ord(char) >= 0x20
    )


def _xml_element_to_dict(element: ET.Element) -> dict[str, Any] | str:
    children = list(element)
    if not children:
        text = (element.text or "").strip()
        if element.attrib:
            result = {key: value for key, value in element.attrib.items()}
            if text:
                result["VALUE"] = text
            return result
        return text

    result: dict[str, Any] = {key: value for key, value in element.attrib.items()}
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


def _sales_voucher_xml(voucher: dict[str, Any], company_name: str | None = None) -> str:
    voucher_date = str(voucher["Date"]).replace("-", "")
    voucher_type = _xml_text(voucher.get("VoucherTypeName", "Sales"))
    party_ledger = _xml_text(voucher["PartyLedgerName"])
    source = voucher.get("Source") or {}
    voucher_number = _xml_text(f"TSA-{source.get('import_id', 'manual')}-{source.get('import_row_id', '1')}")
    company_xml = ""
    if company_name:
        company_xml = f"<SVCURRENTCOMPANY>{_xml_text(company_name)}</SVCURRENTCOMPANY>"

    party_entry = _ledger_entry_xml(voucher["PartyLedgerName"], voucher["LedgerEntries"][1]["Amount"], is_party=True)
    sales_ledger_name = voucher["LedgerEntries"][0]["LedgerName"]
    inventory_entries = "\n".join(_inventory_entry_xml(item, sales_ledger_name) for item in voucher.get("InventoryEntries", []))

    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Import</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>Vouchers</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
          {company_xml}
          <SVVCHIMPORTFORMAT>XML</SVVCHIMPORTFORMAT>
          <IMPORTDUPS>@@DUPCOMBINE</IMPORTDUPS>
        </STATICVARIABLES>
    </DESC>
    <DATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="{voucher_type}" ACTION="Create" OBJVIEW="Invoice Voucher View">
            <DATE>{voucher_date}</DATE>
            <VCHSTATUSDATE>{voucher_date}</VCHSTATUSDATE>
            <EFFECTIVEDATE>{voucher_date}</EFFECTIVEDATE>
            <VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{voucher_number}</VOUCHERNUMBER>
            <PARTYLEDGERNAME>{party_ledger}</PARTYLEDGERNAME>
            <PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>
            <ISINVOICE>Yes</ISINVOICE>
            {inventory_entries}
            {party_entry}
          </VOUCHER>
        </TALLYMESSAGE>
    </DATA>
  </BODY>
</ENVELOPE>"""


def _stock_items_collection_xml(company_name: str | None = None) -> str:
    company_xml = f"<SVCURRENTCOMPANY>{_xml_text(company_name)}</SVCURRENTCOMPANY>" if company_name else ""
    fetch_fields = ",".join(
        [
            "Name",
            "Parent",
            "Category",
            "StockCategory",
            "BaseUnits",
            "AdditionalUnits",
            "OpeningBalance",
            "ClosingBalance",
            "OpeningValue",
            "ClosingValue",
            "OpeningRate",
            "ClosingRate",
            "GSTTypeOfSupply",
            "GSTOVRDNTYPEOFSUPPLY",
            "GSTOVRDNTaxability",
            "GSTHSNName",
            "GSTHSNSACCode",
            "GSTHSNDescription",
            "GSTDetails.*",
            "GSTDetails.RateDetails.*",
            "GSTDetails.StateWiseDetails.*",
            "GSTDetails.StateWiseDetails.RateDetails.*",
            "HSNDetails.*",
            "RateDetails.*",
        ]
    )
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>AccountPilotStockItems</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>XML</SVEXPORTFORMAT>
        {company_xml}
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="AccountPilotStockItems" ISMODIFY="No">
            <TYPE>Stock Item</TYPE>
            <FETCH>{fetch_fields}</FETCH>
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""


def _companies_collection_xml() -> str:
    return """<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>Company</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>XML</SVEXPORTFORMAT>
      </STATICVARIABLES>
    </DESC>
  </BODY>
</ENVELOPE>"""


def _gst_sales_voucher_xml(voucher: dict[str, Any], company_name: str | None = None) -> str:
    voucher_date = _date_yyyymmdd(voucher["Date"])
    voucher_type = _xml_text(voucher.get("VoucherTypeName", "Sales"))
    source = voucher.get("Source") or {}
    voucher_number = _xml_text(f"TSA-GST-{source.get('import_id', 'manual')}-{source.get('import_row_id', '1')}")
    company_xml = f"<SVCURRENTCOMPANY>{_xml_text(company_name)}</SVCURRENTCOMPANY>" if company_name else ""
    company_label = company_name or voucher.get("CompanyName") or ""
    buyer_name = _xml_text(voucher["BuyerName"])
    buyer_state = _xml_text(voucher["BuyerState"])
    buyer_gstin = _xml_text(voucher["BuyerGSTIN"])
    company_state = _xml_text(voucher["CompanyState"])
    company_gstin = _xml_text(voucher["CompanyGSTIN"])
    place_of_supply = _xml_text(voucher.get("PlaceOfSupply") or voucher["BuyerState"])
    registration_name = _xml_text(voucher.get("GSTRegistrationName") or "GST Registration")
    registration_type = _xml_text(voucher.get("GSTRegistrationType") or "Regular")
    inventory_entries = "\n".join(_gst_inventory_entry_xml(item) for item in voucher.get("InventoryEntries", []))
    tax_entries = _gst_tax_ledger_entries_xml(voucher)
    invoice_total = _xml_amount(-float(voucher["InvoiceTotal"]))

    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Import</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>Vouchers</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        {company_xml}
        <SVVCHIMPORTFORMAT>XML</SVVCHIMPORTFORMAT>
        <IMPORTDUPS>@@DUPCOMBINE</IMPORTDUPS>
      </STATICVARIABLES>
    </DESC>
    <DATA>
      <TALLYMESSAGE xmlns:UDF="TallyUDF">
        <VOUCHER VCHTYPE="{voucher_type}" ACTION="Create" OBJVIEW="Invoice Voucher View">
          <DATE>{voucher_date}</DATE>
          <VCHSTATUSDATE>{voucher_date}</VCHSTATUSDATE>
          <VOUCHERNUMBER>{voucher_number}</VOUCHERNUMBER>
          <GSTREGISTRATIONTYPE>{registration_type}</GSTREGISTRATIONTYPE>
          <STATENAME>{buyer_state}</STATENAME>
          <COUNTRYOFRESIDENCE>India</COUNTRYOFRESIDENCE>
          <PARTYGSTIN>{buyer_gstin}</PARTYGSTIN>
          <PLACEOFSUPPLY>{place_of_supply}</PLACEOFSUPPLY>
          <VOUCHERTYPENAME>{voucher_type}</VOUCHERTYPENAME>
          <PARTYNAME>{buyer_name}</PARTYNAME>
          <GSTREGISTRATION TAXTYPE="GST" TAXREGISTRATION="{company_gstin}">{registration_name}</GSTREGISTRATION>
          <CMPGSTIN>{company_gstin}</CMPGSTIN>
          <PARTYLEDGERNAME>{buyer_name}</PARTYLEDGERNAME>
          <BASICBUYERNAME>{buyer_name}</BASICBUYERNAME>
          <CMPGSTREGISTRATIONTYPE>{registration_type}</CMPGSTREGISTRATIONTYPE>
          <PARTYMAILINGNAME>{buyer_name}</PARTYMAILINGNAME>
          <DISPATCHFROMNAME>{_xml_text(company_label)}</DISPATCHFROMNAME>
          <DISPATCHFROMSTATENAME>{company_state}</DISPATCHFROMSTATENAME>
          <CONSIGNEEGSTIN>{buyer_gstin}</CONSIGNEEGSTIN>
          <CONSIGNEEMAILINGNAME>{buyer_name}</CONSIGNEEMAILINGNAME>
          <CONSIGNEESTATENAME>{buyer_state}</CONSIGNEESTATENAME>
          <CMPGSTSTATE>{company_state}</CMPGSTSTATE>
          <CONSIGNEECOUNTRYNAME>India</CONSIGNEECOUNTRYNAME>
          <BASICBASEPARTYNAME>{buyer_name}</BASICBASEPARTYNAME>
          <EFFECTIVEDATE>{voucher_date}</EFFECTIVEDATE>
          <ISINVOICE>Yes</ISINVOICE>
          {inventory_entries}
          <LEDGERENTRIES.LIST>
            <LEDGERNAME>{buyer_name}</LEDGERNAME>
            <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
            <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
            <AMOUNT>{invoice_total}</AMOUNT>
            <BILLALLOCATIONS.LIST>
              <NAME>{voucher_number}</NAME>
              <BILLTYPE>New Ref</BILLTYPE>
              <TDSDEDUCTEEISSPECIALRATE>No</TDSDEDUCTEEISSPECIALRATE>
              <AMOUNT>{invoice_total}</AMOUNT>
            </BILLALLOCATIONS.LIST>
          </LEDGERENTRIES.LIST>
          {tax_entries}
        </VOUCHER>
      </TALLYMESSAGE>
    </DATA>
  </BODY>
</ENVELOPE>"""


def _ledger_master_xml(name: str, group_name: str, company_name: str | None = None) -> str:
    ledger_name = _xml_text(name)
    parent = _xml_text(group_name)
    company_xml = ""
    if company_name:
        company_xml = f"<SVCURRENTCOMPANY>{_xml_text(company_name)}</SVCURRENTCOMPANY>"
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Import</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>All Masters</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        {company_xml}
      </STATICVARIABLES>
    </DESC>
    <DATA>
      <TALLYMESSAGE xmlns:UDF="TallyUDF">
        <LEDGER NAME="{ledger_name}" ACTION="Create">
          <NAME>{ledger_name}</NAME>
          <PARENT>{parent}</PARENT>
          <ISBILLWISEON>No</ISBILLWISEON>
          <AFFECTSSTOCK>No</AFFECTSSTOCK>
        </LEDGER>
      </TALLYMESSAGE>
    </DATA>
  </BODY>
</ENVELOPE>"""


def _inventory_entry_xml(item: dict[str, Any], sales_ledger_name: str) -> str:
    stock_item = _xml_text(item["StockItemName"])
    amount = _xml_amount(item["Amount"])
    unit = str(item.get("Unit") or item.get("BaseUnit") or "nos")
    rate = f"{_xml_amount(item.get('Rate', item['Amount']))}/{_xml_text(unit)}"
    quantity = _xml_quantity_with_unit(item.get("Quantity", 1), unit)
    sales_ledger = _xml_text(sales_ledger_name)
    return f"""<ALLINVENTORYENTRIES.LIST>
              <STOCKITEMNAME>{stock_item}</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <RATE>{rate}</RATE>
              <AMOUNT>{amount}</AMOUNT>
              <ACTUALQTY>{quantity}</ACTUALQTY>
              <BILLEDQTY>{quantity}</BILLEDQTY>
              <BATCHALLOCATIONS.LIST>
                <GODOWNNAME>Main Location</GODOWNNAME>
                <BATCHNAME>Primary Batch</BATCHNAME>
                <AMOUNT>{amount}</AMOUNT>
                <ACTUALQTY>{quantity}</ACTUALQTY>
                <BILLEDQTY>{quantity}</BILLEDQTY>
              </BATCHALLOCATIONS.LIST>
              <ACCOUNTINGALLOCATIONS.LIST>
                <LEDGERNAME>{sales_ledger}</LEDGERNAME>
                <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                <AMOUNT>{amount}</AMOUNT>
              </ACCOUNTINGALLOCATIONS.LIST>
            </ALLINVENTORYENTRIES.LIST>"""


def _gst_inventory_entry_xml(item: dict[str, Any]) -> str:
    stock_item = _xml_text(item["StockItemName"])
    amount = _xml_amount(item["Amount"])
    unit = str(item.get("Unit") or "nos")
    rate = f"{_xml_amount(item.get('Rate', item['Amount']))}/{_xml_text(unit)}"
    quantity = _xml_quantity_with_unit(item.get("Quantity", 1), unit)
    sales_ledger = _xml_text(item.get("SalesLedgerName") or "GST Sales")
    gst_rate = float(item.get("GSTRate") or 0)
    half_rate = gst_rate / 2
    return f"""<ALLINVENTORYENTRIES.LIST>
            <STOCKITEMNAME>{stock_item}</STOCKITEMNAME>
            <GSTOVRDNISREVCHARGEAPPL>Not Applicable</GSTOVRDNISREVCHARGEAPPL>
            <GSTOVRDNTAXABILITY>{_xml_text(item.get("Taxability") or "Taxable")}</GSTOVRDNTAXABILITY>
            <GSTSOURCETYPE>Stock Item</GSTSOURCETYPE>
            <GSTITEMSOURCE>{stock_item}</GSTITEMSOURCE>
            <HSNSOURCETYPE>Stock Item</HSNSOURCETYPE>
            <HSNITEMSOURCE>{stock_item}</HSNITEMSOURCE>
            <GSTOVRDNTYPEOFSUPPLY>{_xml_text(item.get("GSTType") or "Goods")}</GSTOVRDNTYPEOFSUPPLY>
            <GSTRATEINFERAPPLICABILITY>As per Masters/Company</GSTRATEINFERAPPLICABILITY>
            <GSTHSNNAME>{_xml_text(item.get("HSNCode") or "")}</GSTHSNNAME>
            <GSTHSNINFERAPPLICABILITY>As per Masters/Company</GSTHSNINFERAPPLICABILITY>
            <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
            <RATE>{rate}</RATE>
            <AMOUNT>{amount}</AMOUNT>
            <ACTUALQTY>{quantity}</ACTUALQTY>
            <BILLEDQTY>{quantity}</BILLEDQTY>
            <BATCHALLOCATIONS.LIST>
              <GODOWNNAME>Main Location</GODOWNNAME>
              <BATCHNAME>Primary Batch</BATCHNAME>
              <AMOUNT>{amount}</AMOUNT>
              <ACTUALQTY>{quantity}</ACTUALQTY>
              <BILLEDQTY>{quantity}</BILLEDQTY>
            </BATCHALLOCATIONS.LIST>
            <ACCOUNTINGALLOCATIONS.LIST>
              <LEDGERNAME>{sales_ledger}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <ISPARTYLEDGER>No</ISPARTYLEDGER>
              <AMOUNT>{amount}</AMOUNT>
            </ACCOUNTINGALLOCATIONS.LIST>
            {_gst_rate_detail_xml("CGST", half_rate)}
            {_gst_rate_detail_xml("SGST/UTGST", half_rate)}
            {_gst_rate_detail_xml("IGST", gst_rate)}
            {_gst_rate_detail_xml("Cess", None)}
            {_gst_rate_detail_xml("State Cess", 0)}
          </ALLINVENTORYENTRIES.LIST>"""


def _gst_tax_ledger_entries_xml(voucher: dict[str, Any]) -> str:
    tax = voucher.get("TaxSplit") or {}
    entries = []
    for ledger_name, amount in [
        (voucher.get("CGSTLedgerName"), tax.get("cgst_amount")),
        (voucher.get("SGSTLedgerName"), tax.get("sgst_amount")),
        (voucher.get("IGSTLedgerName"), tax.get("igst_amount")),
    ]:
        if amount is None or float(amount) <= 0:
            continue
        entries.append(_ledger_entry_xml(str(ledger_name), amount))
    return "\n".join(entries)


def _gst_rate_detail_xml(duty_head: str, rate: float | None) -> str:
    if rate is None:
        return f"""<RATEDETAILS.LIST>
              <GSTRATEDUTYHEAD>{_xml_text(duty_head)}</GSTRATEDUTYHEAD>
              <GSTRATEVALUATIONTYPE>Not Applicable</GSTRATEVALUATIONTYPE>
            </RATEDETAILS.LIST>"""
    return f"""<RATEDETAILS.LIST>
              <GSTRATEDUTYHEAD>{_xml_text(duty_head)}</GSTRATEDUTYHEAD>
              <GSTRATEVALUATIONTYPE>Based on Value</GSTRATEVALUATIONTYPE>
              <GSTRATE>{_xml_amount(rate)}</GSTRATE>
            </RATEDETAILS.LIST>"""


def _ledger_entry_xml(ledger_name: str, amount: Any, is_party: bool = False) -> str:
    amount_text = _xml_amount(amount)
    deemed_positive = "Yes" if float(amount) < 0 else "No"
    party_xml = "<ISPARTYLEDGER>Yes</ISPARTYLEDGER>" if is_party else ""
    return f"""<LEDGERENTRIES.LIST>
              <LEDGERNAME>{_xml_text(ledger_name)}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>{deemed_positive}</ISDEEMEDPOSITIVE>
              <ISLASTDEEMEDPOSITIVE>{deemed_positive}</ISLASTDEEMEDPOSITIVE>
              {party_xml}
              <AMOUNT>{amount_text}</AMOUNT>
            </LEDGERENTRIES.LIST>"""


def _xml_text(value: Any) -> str:
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


def _xml_amount(value: Any) -> str:
    return f"{float(value):.2f}"


def _xml_quantity(value: Any) -> str:
    quantity = float(value)
    quantity_text = str(int(quantity)) if quantity.is_integer() else str(quantity)
    return f"{quantity_text} Nos"


def _xml_quantity_with_unit(value: Any, unit: str) -> str:
    quantity = float(value)
    quantity_text = str(int(quantity)) if quantity.is_integer() else str(quantity)
    return f"{quantity_text} {_xml_text(unit)}"


def _date_yyyymmdd(value: Any) -> str:
    return str(value).strip().replace("-", "")


def _friendly_tally_line_error(message: str) -> str:
    if "voucher date is missing" in message.lower():
        return "Tally rejected the voucher date. If Tally is in educational mode, use the 1st, 2nd, or 31st of a month."
    return message.strip()
