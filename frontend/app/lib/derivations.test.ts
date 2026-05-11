import assert from "node:assert/strict";
import test from "node:test";

import {
  countCommittedVouchers,
  deriveImportStats,
  deriveImportStatus,
  formatUserError,
  formatRowError,
  getUserInitials,
  getVoucherIdentifier,
  summarizePreview,
} from "./derivations.ts";
import type { ImportRecord, ImportRow } from "./types";

const baseImport: ImportRecord = {
  id: 1,
  filename: "sales.xlsx",
  status: "processed",
  row_count: 3,
  valid_count: 2,
  error_count: 1,
};

const rows: ImportRow[] = [
  {
    id: 1,
    source_row_id: "1",
    product_name: "Coffee Powder",
    price: 100,
    payment_mode: "Cash",
    voucher_date: "2026-05-01",
    validation_status: "valid",
    commit_status: "success",
    tally_response: { voucher_number: "SAL-001" },
  },
  {
    id: 2,
    source_row_id: "2",
    product_name: "Samsung Monitor",
    price: 2500,
    payment_mode: "UPI",
    voucher_date: "2026-05-03",
    validation_status: "valid",
    commit_status: "pending",
  },
  {
    id: 3,
    source_row_id: "3",
    product_name: "Missing Item",
    price: 500,
    payment_mode: "Cash",
    voucher_date: "2026-05-02",
    validation_status: "invalid",
    validation_error: "Stock item not found",
    commit_status: "failed",
    commit_error: "Skipped",
  },
];

test("summarizePreview derives user-visible batch totals from rows", () => {
  const summary = summarizePreview(rows);

  assert.equal(summary.totalRows, 3);
  assert.equal(summary.validRows, 2);
  assert.equal(summary.errorRows, 1);
  assert.equal(summary.readyPercentage, 66.7);
  assert.equal(summary.totalValidAmount, 2600);
  assert.match(summary.dateRangeText, /01 May 2026/);
  assert.match(summary.dateRangeText, /03 May 2026/);
});

test("deriveImportStats and dashboard count use successful committed rows", () => {
  assert.deepEqual(deriveImportStats(rows), {
    successCount: 1,
    failedCount: 1,
    pendingCount: 1,
    voucherCount: 1,
  });
  assert.equal(countCommittedVouchers({ 1: rows, 2: [rows[0]] }), 2);
});

test("deriveImportStatus handles partial and validation states", () => {
  assert.deepEqual(deriveImportStatus(baseImport, rows), { label: "Partial", tone: "warning" });
  assert.deepEqual(deriveImportStatus({ ...baseImport, valid_count: 0, error_count: 3 }, []), { label: "Invalid", tone: "error" });
  assert.deepEqual(deriveImportStatus({ ...baseImport, valid_count: 3, error_count: 0 }, []), { label: "Ready", tone: "success" });
});

test("voucher identifiers and user initials degrade gracefully", () => {
  assert.equal(getVoucherIdentifier(rows[0]), "SAL-001");
  assert.equal(getVoucherIdentifier({ ...rows[0], tally_response: { nested: { masterId: 42 } } }), "42");
  assert.equal(getVoucherIdentifier(rows[1]), "");
  assert.equal(getUserInitials({ email: "feel.dunfi@gmail.com" }), "FD");
});

test("formatUserError keeps frontend errors plain-language", () => {
  assert.equal(formatUserError("Company not found", 404), "Company not found in Tally. Check the company name and try again.");
  assert.equal(formatUserError("connection refused", 502), "Can't connect to Tally right now. Open Tally and check the connection, then try again.");
  assert.equal(formatUserError("no session", 401), "Your session has expired. Please sign in again.");
});

test("formatRowError extracts short row-level Tally errors", () => {
  const raw = `Local agent request failed: Tally returned exceptions: {'ENVELOPE': {'BODY': {'DATA': {'IMPORTRESULT': {'LINEERROR': "Voucher date is missing for: 'Sales' voucher TSA-19-58. Verify the data, resolve errors (if any) and retry Split."}}}}}`;
  assert.equal(
    formatRowError(raw),
    "Tally rejected the voucher date. If Tally is in educational mode, use the 1st, 2nd, or 31st of a month.",
  );
  assert.equal(formatRowError("Product not found in synced Tally stock items"), "Product not found in synced Tally stock items.");
});
