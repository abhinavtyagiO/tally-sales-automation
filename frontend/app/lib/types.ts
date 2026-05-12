export type User = { email: string; name?: string };

export type Company = {
  id: number;
  company_name: string;
  tally_url: string;
  last_sync_status?: string | null;
  last_sync_at?: string | null;
  last_selected_at?: string | null;
};

export type TallyStatus = {
  status: "connected" | "disconnected";
  detail?: string | null;
  message: string;
};

export type TallyCompanies = {
  available: boolean;
  companies: string[];
  message?: string | null;
};

export type ImportRecord = {
  id: number;
  filename?: string | null;
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
  payment_mode: string;
  voucher_date: string;
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

export type AppView = "dashboard" | "inventory" | "upload" | "preview" | "result" | "history";
