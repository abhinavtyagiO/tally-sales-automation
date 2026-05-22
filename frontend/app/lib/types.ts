export type User = { email: string; name?: string };

export type ImportType = "retail_sales" | "gst_tax_invoice";

export type Company = {
  id: number;
  company_name: string;
  tally_url: string;
  supplier_gstin?: string | null;
  supplier_state?: string | null;
  gst_registration_name?: string | null;
  gst_registration_type?: string | null;
  gst_sales_ledger_name?: string | null;
  cgst_ledger_name?: string | null;
  sgst_ledger_name?: string | null;
  igst_ledger_name?: string | null;
  gst_buyer_ledger_group?: string | null;
  last_sync_status?: string | null;
  last_sync_at?: string | null;
  last_selected_at?: string | null;
};

export type TallyStatus = {
  status: "connected" | "disconnected" | "checking";
  detail?: string | null;
  message: string;
};

export type TallyCompanies = {
  available: boolean;
  companies: string[];
  message?: string | null;
};

export type HelperStatus = {
  status: "helper_required" | "waiting_for_helper" | "connected" | "stale";
  message: string;
  agent?: { id: number; device_name: string; last_seen_at?: string | null } | null;
};

export type ImportRecord = {
  id: number;
  filename?: string | null;
  import_type?: ImportType | string | null;
  status: string;
  row_count: number;
  valid_count: number;
  error_count: number;
  created_at?: string | null;
  completed_at?: string | null;
};

export type ImportRow = {
  id: number;
  source_row_id: string;
  product_name: string;
  price: number;
  quantity?: number | null;
  rate?: number | null;
  payment_mode: string;
  voucher_date: string;
  buyer_name?: string | null;
  buyer_gstin?: string | null;
  buyer_state?: string | null;
  buyer_address?: string | null;
  place_of_supply?: string | null;
  taxable_amount?: number | null;
  gst_rate?: number | null;
  cgst_amount?: number | null;
  sgst_amount?: number | null;
  igst_amount?: number | null;
  total_amount?: number | null;
  validation_status: "pending" | "valid" | "invalid";
  validation_error?: string | null;
  commit_status: "pending" | "success" | "failed";
  commit_error?: string | null;
  tally_response?: unknown;
};

export type ImportPreview = { import: ImportRecord; rows: ImportRow[] };

export type StockItem = {
  id: number;
  company_id: number;
  name: string;
  group_name?: string | null;
  category?: string | null;
  base_unit?: string | null;
  additional_unit?: string | null;
  opening_balance?: string | null;
  closing_balance?: string | null;
  opening_value?: string | null;
  closing_value?: string | null;
  opening_rate?: string | null;
  closing_rate?: string | null;
  gst_type?: string | null;
  gst_rate?: number | null;
  hsn_code?: string | null;
  hsn_description?: string | null;
  taxability?: string | null;
  raw?: unknown;
};

export type StockItemsResponse = {
  company_id: number;
  company: string;
  last_sync_at?: string | null;
  last_sync_status?: string | null;
  count: number;
  groups: string[];
  categories: string[];
  low_stock_count: number;
  items: StockItem[];
};

export type CommitResult = {
  import_row_id: number;
  status: string;
  error?: string;
  response?: unknown;
};

export type CommitSummary = {
  success_count: number;
  failed_count: number;
  rows: ImportRow[];
  results: CommitResult[];
};

export type CommitRun = {
  id: number;
  company_id: number;
  import_id: number;
  status: "queued" | "processing" | "completed" | "failed";
  total_count: number;
  success_count: number;
  failed_count: number;
  error_message?: string | null;
  result?: CommitSummary | Record<string, never>;
};

export type AppView = "dashboard" | "inventory" | "upload" | "preview" | "result" | "history" | "historyDetail";
