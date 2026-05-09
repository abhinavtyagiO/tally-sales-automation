from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import requests


DEFAULT_COLLECTIONS = [
    "Company",
    "Group",
    "Ledger",
    "StockGroup",
    "StockCategory",
    "StockItem",
    "Unit",
    "Godown",
    "VoucherType",
    "Currency",
    "CostCategory",
    "CostCentre",
    "Budget",
    "GSTClassification",
    "TaxUnit",
]

VOUCHER_FETCHES = [
    "DATE",
    "VOUCHERNUMBER",
    "VOUCHERTYPENAME",
    "PARTYLEDGERNAME",
    "MASTERID",
    "GUID",
    "ALLLEDGERENTRIES.*",
    "ALLINVENTORYENTRIES.*",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump Tally XML reference data for local contract inspection.")
    parser.add_argument("--base-url", default="http://192.168.1.15:9000")
    parser.add_argument("--company", default="Bhrama Enterprises")
    parser.add_argument("--out", default="tally_reference")
    args = parser.parse_args()

    out_dir = Path(args.out) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = out_dir / "raw"
    summary_dir = out_dir / "summaries"
    raw_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "base_url": args.base_url,
        "company": args.company,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "exports": [],
    }

    ping = requests.get(args.base_url, timeout=10)
    (raw_dir / "00_ping.xml").write_text(ping.text)
    manifest["ping"] = {"status_code": ping.status_code, "body": ping.text[:200]}

    for collection in DEFAULT_COLLECTIONS:
        export_name = f"collection_{safe_name(collection)}"
        fetch_and_record(
            args.base_url,
            collection_xml(collection, args.company),
            export_name,
            raw_dir,
            summary_dir,
            manifest,
        )

    fetch_and_record(
        args.base_url,
        voucher_collection_xml(args.company),
        "collection_vouchers_all",
        raw_dir,
        summary_dir,
        manifest,
    )

    for report_name in ["Day Book", "Sales Register", "Trial Balance", "Balance Sheet", "Profit and Loss"]:
        fetch_and_record(
            args.base_url,
            report_xml(report_name, args.company),
            f"report_{safe_name(report_name)}",
            raw_dir,
            summary_dir,
            manifest,
        )

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    write_readme(out_dir, manifest)
    print(out_dir)


def fetch_and_record(
    base_url: str,
    xml: str,
    name: str,
    raw_dir: Path,
    summary_dir: Path,
    manifest: dict[str, Any],
) -> None:
    response = requests.post(base_url, data=xml, headers={"Content-Type": "text/xml"}, timeout=60)
    raw_path = raw_dir / f"{name}.xml"
    raw_path.write_text(response.text)
    summary = summarize_xml(response.text)
    summary_path = summary_dir / f"{name}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    manifest["exports"].append(
        {
            "name": name,
            "status_code": response.status_code,
            "bytes": len(response.text.encode("utf-8")),
            "raw": str(raw_path),
            "summary": str(summary_path),
            "top_tags": summary.get("top_tags", [])[:10],
            "likely_records": summary.get("likely_records", {}),
            "error": summary.get("error"),
        }
    )


def collection_xml(collection_id: str, company: str) -> str:
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Collection</TYPE>
    <ID>{xml_text(collection_id)}</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>XML</SVEXPORTFORMAT>
        <SVCURRENTCOMPANY>{xml_text(company)}</SVCURRENTCOMPANY>
      </STATICVARIABLES>
    </DESC>
  </BODY>
</ENVELOPE>"""


def voucher_collection_xml(company: str) -> str:
    fetch_tags = "\n".join(f"<FETCH>{xml_text(fetch)}</FETCH>" for fetch in VOUCHER_FETCHES)
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>EXPORT</TALLYREQUEST>
    <TYPE>COLLECTION</TYPE>
    <ID>AllVouchersReference</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
        <SVCURRENTCOMPANY>{xml_text(company)}</SVCURRENTCOMPANY>
      </STATICVARIABLES>
      <TDL>
        <TDLMESSAGE>
          <COLLECTION NAME="AllVouchersReference" ISINITIALIZE="Yes">
            <TYPE>Voucher</TYPE>
            {fetch_tags}
          </COLLECTION>
        </TDLMESSAGE>
      </TDL>
    </DESC>
  </BODY>
</ENVELOPE>"""


def report_xml(report_name: str, company: str) -> str:
    return f"""<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <TALLYREQUEST>Export</TALLYREQUEST>
    <TYPE>Data</TYPE>
    <ID>{xml_text(report_name)}</ID>
  </HEADER>
  <BODY>
    <DESC>
      <STATICVARIABLES>
        <SVEXPORTFORMAT>XML</SVEXPORTFORMAT>
        <SVCURRENTCOMPANY>{xml_text(company)}</SVCURRENTCOMPANY>
      </STATICVARIABLES>
    </DESC>
  </BODY>
</ENVELOPE>"""


def summarize_xml(text: str) -> dict[str, Any]:
    sanitized = sanitize_xml(text)
    summary: dict[str, Any] = {"bytes": len(text.encode("utf-8"))}
    try:
        root = ET.fromstring(sanitized)
    except ET.ParseError as exc:
        summary["error"] = f"XML parse error: {exc}"
        summary["head"] = text[:1000]
        return summary

    tags = Counter(element.tag for element in root.iter())
    summary["root"] = root.tag
    summary["top_tags"] = tags.most_common(30)
    summary["likely_records"] = {
        tag: tags[tag]
        for tag in [
            "COMPANY",
            "GROUP",
            "LEDGER",
            "STOCKGROUP",
            "STOCKCATEGORY",
            "STOCKITEM",
            "UNIT",
            "GODOWN",
            "VOUCHERTYPE",
            "VOUCHER",
            "ALLLEDGERENTRIES.LIST",
            "ALLINVENTORYENTRIES.LIST",
        ]
        if tags[tag]
    }
    summary["record_shapes"] = record_shapes(root)
    summary["sample_records"] = sample_records(root)
    return summary


def record_shapes(root: ET.Element) -> dict[str, Any]:
    shapes: dict[str, Any] = {}
    for tag in [
        "COMPANY",
        "GROUP",
        "LEDGER",
        "STOCKITEM",
        "UNIT",
        "GODOWN",
        "VOUCHERTYPE",
        "VOUCHER",
        "ALLLEDGERENTRIES.LIST",
        "ALLINVENTORYENTRIES.LIST",
    ]:
        element = find_record_element(root, tag)
        if element is None:
            continue
        child_tags = []
        seen = set()
        for child in list(element):
            if child.tag not in seen:
                child_tags.append(child.tag)
                seen.add(child.tag)
        shapes[tag] = {"attributes": sorted(element.attrib), "children": child_tags[:80]}
    return shapes


def sample_records(root: ET.Element) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for tag in ["LEDGER", "STOCKITEM", "VOUCHERTYPE", "VOUCHER", "ALLLEDGERENTRIES.LIST", "ALLINVENTORYENTRIES.LIST"]:
        element = find_record_element(root, tag)
        if element is None:
            continue
        samples[tag] = compact_element(element, max_children=30)
    return samples


def find_record_element(root: ET.Element, tag: str) -> ET.Element | None:
    fallback = None
    for element in root.iter(tag):
        fallback = fallback or element
        if element.attrib or list(element):
            return element
    return fallback


def compact_element(element: ET.Element, max_children: int) -> dict[str, Any]:
    result: dict[str, Any] = {"_tag": element.tag}
    if element.attrib:
        result["_attributes"] = dict(element.attrib)
    text = (element.text or "").strip()
    if text:
        result["_text"] = text
    for child in list(element)[:max_children]:
        value = compact_element(child, max_children=8) if list(child) else ((child.text or "").strip())
        if child.attrib and not list(child):
            value = {"_attributes": dict(child.attrib), "_text": (child.text or "").strip()}
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(value)
        else:
            result[child.tag] = value
    return result


def write_readme(out_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Tally Reference Dump",
        "",
        f"- Company: `{manifest['company']}`",
        f"- Base URL: `{manifest['base_url']}`",
        f"- Created at: `{manifest['created_at']}`",
        "",
        "Raw XML is in `raw/`; parsed contract summaries are in `summaries/`.",
        "",
        "## Exports",
        "",
    ]
    for item in manifest["exports"]:
        lines.append(
            f"- `{item['name']}`: {item['bytes']} bytes, records {json.dumps(item.get('likely_records', {}), sort_keys=True)}"
        )
        if item.get("error"):
            lines.append(f"  - error: `{item['error']}`")
    out_dir.joinpath("README.md").write_text("\n".join(lines) + "\n")


def sanitize_xml(text: str) -> str:
    text = re.sub(r"&#(?:0*4|x0*4);", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(<\/?)([A-Za-z_][\w.-]*):", r"\1\2_", text)
    text = re.sub(r"(\s)([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*=)", r"\1\2_\3", text)
    return "".join(char for char in text if char in {"\t", "\n", "\r"} or ord(char) >= 0x20)


def safe_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def xml_text(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


if __name__ == "__main__":
    main()
