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
  importTypeLabel,
  summarizePreview,
} from "./derivations.ts";
import { deriveOnboardingState, isCompanySetupComplete } from "./onboarding.ts";
import type { Company, ImportRecord, ImportRow } from "./types";

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

test("importTypeLabel uses product-facing invoice names", () => {
  assert.equal(importTypeLabel("retail_sales"), "Invoice for Individual Customers");
  assert.equal(importTypeLabel("gst_tax_invoice"), "Invoice for GST Firms");
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
  assert.equal(
    formatRowError("GST rate is missing for this stock item"),
    "GST rate is missing for this product. Add the GST rate in Tally, sync inventory, and try again.",
  );
});

test("deriveOnboardingState gates production progress by real setup facts", () => {
  const base = deriveOnboardingState({
    helperSetupEnabled: true,
    activeCompany: null,
    helperStatus: null,
    tallyStatus: null,
    tallyCompanies: { available: false, companies: [] },
    syncStatus: null,
    requestedStepId: "company",
    local: {
      welcomeComplete: true,
      tallyPrepared: true,
      helperDownloaded: true,
      commandRun: false,
      connectionAcknowledged: false,
    },
  });

  assert.equal(base.currentStepId, "run_command");
  assert.equal(base.connectionReady, false);
  assert.equal(base.steps.find((step) => step.id === "company")?.locked, true);
});

test("deriveOnboardingState resumes connected users at company setup after acknowledgement", () => {
  const state = deriveOnboardingState({
    helperSetupEnabled: true,
    activeCompany: null,
    helperStatus: { status: "connected", message: "Connected" },
    tallyStatus: { status: "connected", message: "Connected to Tally" },
    tallyCompanies: { available: true, companies: ["Bhrama Enterprises"], status: "available" },
    syncStatus: null,
    requestedStepId: "company",
    local: {
      welcomeComplete: true,
      tallyPrepared: true,
      helperDownloaded: true,
      commandRun: true,
      connectionAcknowledged: true,
    },
  });

  assert.equal(state.currentStepId, "company");
  assert.equal(state.connectionReady, true);
  assert.equal(state.steps.find((step) => step.id === "company")?.locked, false);
});

test("deriveOnboardingState sends syncing companies to sync and completed companies to ready", () => {
  const company: Company = {
    id: 1,
    company_name: "Bhrama Enterprises",
    tally_url: "http://127.0.0.1:9000",
    supplier_gstin: "29AAECP4424C1ZN",
    supplier_state: "Karnataka",
    last_sync_status: "queued",
  };
  const facts = {
    helperSetupEnabled: true,
    activeCompany: company,
    helperStatus: { status: "connected", message: "Connected" },
    tallyStatus: { status: "connected", message: "Connected" },
    tallyCompanies: { available: true, companies: ["Bhrama Enterprises"], status: "available" },
    syncStatus: { status: "syncing", message: "Syncing Tally masters..." },
    requestedStepId: "ready",
    local: {
      welcomeComplete: true,
      tallyPrepared: true,
      helperDownloaded: true,
      commandRun: true,
      connectionAcknowledged: true,
    },
  } as const;
  const syncing = deriveOnboardingState(facts);
  const completedCompany = { ...company, last_sync_status: "success", last_sync_at: "2026-05-26T10:00:00+05:30" };
  const ready = deriveOnboardingState({
    ...facts,
    activeCompany: { ...company, last_sync_status: "success", last_sync_at: "2026-05-26T10:00:00+05:30" },
    syncStatus: { status: "completed", message: "Tally masters synced." },
  });

  assert.equal(syncing.currentStepId, "sync");
  assert.equal(ready.currentStepId, "ready");
  assert.equal(isCompanySetupComplete(completedCompany), true);
});
