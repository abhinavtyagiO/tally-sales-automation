import type { Company, ImportRecord, ImportRow, ImportType, TallyStatus, User } from "./types";

export type PreviewSummary = {
  totalRows: number;
  validRows: number;
  errorRows: number;
  readyPercentage: number;
  totalValidAmount: number;
  dateRangeText: string;
};

export type ImportDetailStats = {
  successCount: number;
  failedCount: number;
  pendingCount: number;
  voucherCount: number;
};

const INR_FORMATTER = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

export function summarizePreview(rows: ImportRow[]): PreviewSummary {
  const validRows = rows.filter((row) => row.validation_status === "valid");
  const dates = validRows
    .map((row) => row.voucher_date)
    .filter(Boolean)
    .sort();

  return {
    totalRows: rows.length,
    validRows: validRows.length,
    errorRows: rows.filter((row) => row.validation_status === "invalid").length,
    readyPercentage: rows.length ? Math.round((validRows.length / rows.length) * 1000) / 10 : 0,
    totalValidAmount: validRows.reduce((total, row) => total + Number(row.total_amount || row.price || 0), 0),
    dateRangeText: formatDateRange(dates[0], dates[dates.length - 1]),
  };
}

export function deriveImportStats(rows: ImportRow[] = []): ImportDetailStats {
  return {
    successCount: rows.filter((row) => row.commit_status === "success").length,
    failedCount: rows.filter((row) => row.commit_status === "failed").length,
    pendingCount: rows.filter((row) => row.commit_status === "pending").length,
    voucherCount: rows.filter((row) => row.commit_status === "success").length,
  };
}

export function deriveImportStatus(importRecord: ImportRecord, rows: ImportRow[] = []) {
  const stats = deriveImportStats(rows);
  if (stats.successCount && stats.failedCount) return { label: "Partial", tone: "warning" as const };
  if (stats.successCount) return { label: "Committed", tone: "success" as const };
  if (stats.failedCount) return { label: "Failed", tone: "error" as const };
  if (importRecord.error_count > 0 && importRecord.valid_count > 0) return { label: "Needs review", tone: "warning" as const };
  if (importRecord.error_count > 0) return { label: "Invalid", tone: "error" as const };
  if (importRecord.valid_count > 0) return { label: "Ready", tone: "success" as const };
  return { label: sentenceCase(importRecord.status || "Uploaded"), tone: "neutral" as const };
}

export function countCommittedVouchers(detailRowsByImportId: Record<number, ImportRow[]>) {
  return Object.values(detailRowsByImportId).reduce((total, rows) => total + deriveImportStats(rows).voucherCount, 0);
}

export function formatCurrency(value: number) {
  return INR_FORMATTER.format(value || 0);
}

export function importTypeLabel(importType?: ImportType | string | null) {
  return importType === "gst_tax_invoice" ? "GST Tax Invoice" : "Retail Sales";
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-IN").format(value || 0);
}

export function formatDateTime(value?: string | null) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(value?: string | null) {
  if (!value) return "Not available";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateRange(start?: string, end?: string) {
  if (!start) return "No valid dates";
  if (!end || start === end) return formatDate(start);
  return `${formatDate(start)} - ${formatDate(end)}`;
}

export function lastSyncText(company: Company | null) {
  if (!company?.last_sync_at) return "Last synced: Not yet";
  return `Last synced: ${formatDateTime(company.last_sync_at)}`;
}

export function getUserInitials(user: User | null) {
  const source = user?.name || user?.email || "User";
  const parts = source.split("@")[0].split(/[.\s_-]+/).filter(Boolean);
  return (parts[0]?.[0] || "U").toUpperCase() + (parts[1]?.[0] || "").toUpperCase();
}

export function tallyIsConnected(status: TallyStatus | null) {
  return status?.status === "connected";
}

export function getVoucherIdentifier(row: ImportRow) {
  return findIdentifier(row.tally_response) || "";
}

export function formatUserError(message: string, status?: number) {
  const lower = message.toLowerCase();
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (lower.includes("already added")) return "This company is already added.";
  if (lower.includes("company not found")) return "Company not found in Tally. Check the company name and try again.";
  if (lower.includes("stock item") || lower.includes("product")) return message;
  if (lower.includes("connect to tally") || lower.includes("unreachable") || lower.includes("connection refused")) {
    return "Can't connect to Tally right now. Open Tally and check the connection, then try again.";
  }
  return message || "Something went wrong. Please try again.";
}

export function formatRowError(message?: string | null) {
  if (!message) return "";
  const lineError = extractLineError(message);
  const selected = lineError || message;
  const lower = selected.toLowerCase();
  if (lower.includes("voucher date is missing") || lower.includes("educational mode")) {
    return "Tally rejected the voucher date. If Tally is in educational mode, use the 1st, 2nd, or 31st of a month.";
  }
  if (lower.includes("product not found") || lower.includes("stock item")) {
    return "Product not found in synced Tally stock items.";
  }
  if (lower.includes("connect") || lower.includes("connection refused") || lower.includes("no route to host")) {
    return "Could not connect to Tally. Check that Tally is open and reachable.";
  }
  return selected.split(" Verify the data")[0].split(" {'ENVELOPE'")[0].replace(/^Local agent request failed:\s*/i, "").trim();
}

function sentenceCase(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

function findIdentifier(value: unknown, depth = 0): string {
  if (!value || depth > 3) return "";
  if (typeof value === "string") {
    const voucherMatch = value.match(/(?:voucher|number|id)[^A-Za-z0-9]{0,8}([A-Za-z0-9/_-]{3,})/i);
    return voucherMatch?.[1] || "";
  }
  if (typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  const keys = [
    "voucher_number",
    "voucherNumber",
    "voucher_no",
    "voucherNo",
    "voucher_id",
    "voucherId",
    "alter_id",
    "alterId",
    "master_id",
    "masterId",
    "id",
  ];
  for (const key of keys) {
    const found = record[key];
    if (typeof found === "string" || typeof found === "number") return String(found);
  }
  for (const nested of Object.values(record)) {
    const found = findIdentifier(nested, depth + 1);
    if (found) return found;
  }
  return "";
}

function extractLineError(message: string) {
  const doubleQuoted = message.match(/LINEERROR['"]?:\s*["']([^"']+)/i);
  if (doubleQuoted?.[1]) return doubleQuoted[1];
  const xml = message.match(/<LINEERROR>(.*?)<\/LINEERROR>/i);
  return xml?.[1] || "";
}
