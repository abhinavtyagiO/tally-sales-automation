"use client";

import { ChangeEvent } from "react";
import {
  ArrowLeft,
  BarChart3,
  Building2,
  CheckCircle2,
  ChevronRight,
  FileSpreadsheet,
  History,
  LogOut,
  RefreshCw,
  Upload,
  XCircle,
} from "lucide-react";

import {
  countCommittedVouchers,
  deriveImportStats,
  deriveImportStatus,
  formatCurrency,
  formatDateTime,
  formatNumber,
  formatRowError,
  getUserInitials,
  getVoucherIdentifier,
  lastSyncText,
  summarizePreview,
  tallyIsConnected,
} from "./lib/derivations";
import type { AppView, CommitSummary, Company, ImportPreview, ImportRecord, ImportRow, TallyCompanies, TallyStatus, User } from "./lib/types";

type ImportDetails = Record<number, ImportRow[]>;

export function LoginPanel({
  googleButtonRef,
  devEmail,
  setDevEmail,
  loginDev,
  busy,
  error,
  googleConfigured,
  devLoginEnabled,
}: {
  googleButtonRef: React.RefObject<HTMLDivElement | null>;
  devEmail: string;
  setDevEmail: (value: string) => void;
  loginDev: () => void;
  busy: boolean;
  error: string;
  googleConfigured: boolean;
  devLoginEnabled: boolean;
}) {
  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="login-brand">
          <span className="login-mark">
            <Building2 size={22} />
          </span>
          <h1>AccountPilot</h1>
          <p>Automating your financial precision with absolute clarity.</p>
        </div>
        {googleConfigured ? (
          <div className="google-button-wrap" ref={googleButtonRef} />
        ) : devLoginEnabled ? (
          <div className="login-form">
            <div className="login-divider">
              <span>OR</span>
            </div>
            <label className="field-label" htmlFor="dev-email">
              Email Address
            </label>
            <input id="dev-email" value={devEmail} onChange={(event) => setDevEmail(event.target.value)} placeholder="name@company.com" type="email" />
            <button className="primary-button" onClick={loginDev} disabled={busy || !devEmail.trim()}>
              Sign in for local dev
            </button>
          </div>
        ) : (
          <p className="alert error-alert">Google sign-in is not configured.</p>
        )}
        {error && <p className="alert error-alert">{error}</p>}
      </section>
    </main>
  );
}

export function AppShell({
  user,
  activeView,
  setActiveView,
  activeCompany,
  companies,
  busy,
  children,
  logout,
  refreshConnection,
}: {
  user: User;
  activeView: AppView;
  setActiveView: (view: AppView) => void;
  activeCompany: Company | null;
  companies: Company[];
  busy: boolean;
  children: React.ReactNode;
  logout: () => void;
  refreshConnection: () => void;
}) {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <span className="brand-mark">
            <Building2 size={22} />
          </span>
          <div>
            <h1>AccountPilot</h1>
            <p>Automation Pro</p>
          </div>
        </div>
        <nav className="nav-list" aria-label="Primary navigation">
          <NavButton icon={<BarChart3 size={18} />} label="Dashboard" active={activeView === "dashboard"} disabled={!companies.length} onClick={() => setActiveView("dashboard")} />
          <NavButton icon={<Upload size={18} />} label="Upload" active={activeView === "upload" || activeView === "preview"} disabled={!companies.length} onClick={() => setActiveView("upload")} />
          <NavButton icon={<History size={18} />} label="History/Logs" active={activeView === "history"} disabled={!companies.length} onClick={() => setActiveView("history")} />
        </nav>
        <button className="primary-button sidebar-action" onClick={() => setActiveView("upload")} disabled={!companies.length}>
          <Upload size={18} /> Upload Excel
        </button>
      </aside>
      <section className="main-panel">
        <TopHeader user={user} activeView={activeView} activeCompany={activeCompany} busy={busy} logout={logout} refreshConnection={refreshConnection} />
        <div className="content-wrap">{children}</div>
      </section>
    </main>
  );
}

function TopHeader({
  user,
  activeView,
  activeCompany,
  busy,
  logout,
  refreshConnection,
}: {
  user: User;
  activeView: AppView;
  activeCompany: Company | null;
  busy: boolean;
  logout: () => void;
  refreshConnection: () => void;
}) {
  const title = activeCompany ? viewTitle(activeView) : "Company Setup";
  return (
    <header className="top-header">
      <div>
        <h2>{title}</h2>
        {activeCompany && <p>{activeCompany.company_name}</p>}
      </div>
      <div className="header-actions">
        {activeCompany && <span className="sync-copy">{lastSyncText(activeCompany)}</span>}
        <button className="icon-button" onClick={refreshConnection} disabled={busy} aria-label="Refresh Tally connection" title="Refresh Tally connection">
          <RefreshCw size={18} />
        </button>
        <div className="user-menu">
          <span className="avatar">{getUserInitials(user)}</span>
          <span>{user.email}</span>
          <button className="ghost-button" onClick={logout} disabled={busy}>
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </div>
    </header>
  );
}

function NavButton({ icon, label, active, disabled, onClick }: { icon: React.ReactNode; label: string; active: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button className={active ? "nav-button active" : "nav-button"} onClick={onClick} disabled={disabled}>
      {icon}
      {label}
    </button>
  );
}

export function SetupView({
  companyName,
  setCompanyName,
  tallyCompanies,
  tallyStatus,
  addCompany,
  busy,
  existingCompanies,
  error,
}: {
  companyName: string;
  setCompanyName: (value: string) => void;
  tallyCompanies: TallyCompanies;
  tallyStatus: TallyStatus | null;
  addCompany: () => void;
  busy: boolean;
  existingCompanies: Company[];
  error: string;
}) {
  const duplicate = existingCompanies.some((company) => company.company_name.toLowerCase() === companyName.trim().toLowerCase());
  return (
    <div className="setup-layout">
      <section className="hero-panel">
        <StatusIcon connected={tallyIsConnected(tallyStatus)} />
        <div>
          <p className="eyebrow">First-run setup</p>
          <h1>Connect your Tally company</h1>
          <p className="lead">Add the company name exactly as it appears in Tally. AccountPilot will verify it before saving.</p>
        </div>
      </section>
      <section className="card form-card">
        <TallyConnection status={tallyStatus} />
        <label className="field-label" htmlFor="company-name">
          Tally company
        </label>
        <div className="inline-form">
          {tallyCompanies.available ? (
            <select id="company-name" value={companyName} onChange={(event) => setCompanyName(event.target.value)} disabled={busy}>
              <option value="">Select company</option>
              {tallyCompanies.companies.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          ) : (
            <input id="company-name" value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="Bhrama Enterprises" disabled={busy} />
          )}
          <button className="primary-button" onClick={addCompany} disabled={busy || !companyName.trim() || duplicate}>
            Add Company
          </button>
        </div>
        {duplicate && <p className="alert error-alert">This company is already added.</p>}
        {!tallyCompanies.available && tallyCompanies.message && <p className="muted">{tallyCompanies.message}</p>}
        {error && <p className="alert error-alert">{error}</p>}
      </section>
    </div>
  );
}

export function DashboardView({
  activeCompany,
  companies,
  imports,
  importDetails,
  tallyStatus,
  busy,
  selectCompany,
  setActiveView,
  error,
}: {
  activeCompany: Company;
  companies: Company[];
  imports: ImportRecord[];
  importDetails: ImportDetails;
  tallyStatus: TallyStatus | null;
  busy: boolean;
  selectCompany: (companyId: number) => void;
  setActiveView: (view: AppView) => void;
  error: string;
}) {
  const vouchersCreated = countCommittedVouchers(importDetails);
  const recentImports = imports.slice(0, 5);
  return (
    <div className="stack">
      {error && <p className="alert error-alert">{error}</p>}
      <div className="dashboard-grid">
        <section className="card connection-card">
          <StatusIcon connected={tallyIsConnected(tallyStatus)} />
          <div>
            <h3>Tally Prime Connection</h3>
            <p className={tallyIsConnected(tallyStatus) ? "status-line success-text" : "status-line error-text"}>
              {tallyIsConnected(tallyStatus) ? "Connected" : "Disconnected"}
              <span>{tallyStatus?.message || "Checking Tally connection..."}</span>
            </p>
          </div>
        </section>
        <section className="card active-company-card">
          <p className="eyebrow">Active Company</p>
          <h3>{activeCompany.company_name}</h3>
          {companies.length > 1 ? (
            <select value={activeCompany.id} onChange={(event) => selectCompany(Number(event.target.value))} disabled={busy}>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.company_name}
                </option>
              ))}
            </select>
          ) : (
            <p className="muted">Uploads and history apply to this company.</p>
          )}
        </section>
      </div>
      <section className="quick-actions">
        <h3>Quick Actions</h3>
        <div className="action-grid">
          <button className="action-card" onClick={() => setActiveView("upload")}>
            <Upload size={22} />
            <strong>Upload Excel</strong>
            <span>Process sales vouchers from a spreadsheet.</span>
          </button>
          <MetricCard label="Vouchers Created" value={formatNumber(vouchersCreated)} />
          <MetricCard label="Imports Processed" value={formatNumber(imports.length)} />
        </div>
      </section>
      <RecentActivity imports={recentImports} importDetails={importDetails} setActiveView={setActiveView} />
    </div>
  );
}

export function UploadView({
  selectedFile,
  setSelectedFile,
  processUpload,
  tallyStatus,
  busy,
  error,
}: {
  selectedFile: File | null;
  setSelectedFile: (file: File | null) => void;
  processUpload: () => void;
  tallyStatus: TallyStatus | null;
  busy: boolean;
  error: string;
}) {
  const connected = tallyIsConnected(tallyStatus);
  return (
    <div className="upload-layout">
      <section>
        <div className="page-intro">
          <h1>Import Financial Records</h1>
          <p>Select an Excel file to validate sales rows against your active Tally company.</p>
        </div>
        <label className="upload-picker">
          <Upload size={48} />
          <strong>{selectedFile ? selectedFile.name : "Choose your Excel file"}</strong>
          <span>Supports .xlsx and .xls files</span>
          <input type="file" accept=".xlsx,.xls" onChange={(event: ChangeEvent<HTMLInputElement>) => setSelectedFile(event.target.files?.[0] || null)} disabled={busy} />
        </label>
        {selectedFile && (
          <section className="card file-preview">
            <FileSpreadsheet size={24} />
            <div>
              <strong>{selectedFile.name}</strong>
              <p>{formatFileSize(selectedFile.size)}</p>
            </div>
            <button className="ghost-button" onClick={() => setSelectedFile(null)} disabled={busy}>
              Remove
            </button>
          </section>
        )}
      </section>
      <aside className="side-stack">
        <section className="card">
          <h3>Upload Guidelines</h3>
          <ol className="guideline-list">
            <li>Use columns `product_name`, `price`, `payment_mode`, and `voucher_date`.</li>
            <li>Product names must exactly match stock items in Tally.</li>
            <li>Each row becomes one sales voucher.</li>
            <li>Voucher dates must be valid.</li>
          </ol>
        </section>
        <section className="card">
          <h3>Tally Status</h3>
          <TallyConnection status={tallyStatus} />
          {!connected && <p className="alert warning-alert">You can choose a file, but processing needs a live Tally connection.</p>}
        </section>
      </aside>
      <footer className="sticky-actions">
        {error && <p className="alert error-alert">{error}</p>}
        <button className="primary-button" onClick={processUpload} disabled={busy || !selectedFile || !connected}>
          {busy ? "Processing..." : "Validate Excel"}
          <ChevronRight size={18} />
        </button>
      </footer>
    </div>
  );
}

export function PreviewCommitView({
  preview,
  tallyStatus,
  busy,
  commitRows,
  setActiveView,
  error,
}: {
  preview: ImportPreview;
  tallyStatus: TallyStatus | null;
  busy: boolean;
  commitRows: () => void;
  setActiveView: (view: AppView) => void;
  error: string;
}) {
  const summary = summarizePreview(preview.rows);
  const connected = tallyIsConnected(tallyStatus);
  return (
    <div className="stack">
      <div className="page-intro with-actions">
        <div>
          <p className="eyebrow">Preview and commit</p>
          <h1>Review before pushing to Tally</h1>
          <p>Valid rows can be committed now. Invalid rows will remain available for review.</p>
        </div>
        <button className="ghost-button back-button" onClick={() => setActiveView("upload")} disabled={busy}>
          <ArrowLeft size={18} /> Back to Upload
        </button>
      </div>
      {error && <p className="alert error-alert">{error}</p>}
      <SummaryCards summary={summary} />
      {summary.errorRows > 0 && <p className="alert warning-alert">{summary.errorRows} invalid row{summary.errorRows === 1 ? "" : "s"} will be skipped if you commit now.</p>}
      <section className="commit-layout">
        <div className="card">
          <h3>Validation Rows</h3>
          <RowsTable rows={preview.rows} />
        </div>
        <section className="card commit-card">
          <h3>Push to Tally</h3>
          <p className="alert warning-alert">This will create vouchers in your active Tally company. This action cannot be bulk-undone in AccountPilot.</p>
          <button className="primary-button wide-button" onClick={commitRows} disabled={busy || !connected || summary.validRows === 0}>
            {busy ? "Committing..." : `Commit ${summary.validRows} valid row${summary.validRows === 1 ? "" : "s"}`}
          </button>
          {!connected && <p className="muted">Open Tally and refresh the connection before committing.</p>}
        </section>
      </section>
    </div>
  );
}

export function CommitResultView({
  preview,
  summary,
  setActiveView,
}: {
  preview: ImportPreview;
  summary: CommitSummary;
  setActiveView: (view: AppView) => void;
}) {
  const resultRows = summary.rows;
  const previewSummary = summarizePreview(resultRows);
  return (
    <div className="stack">
      <div className="page-intro with-actions">
        <div>
          <p className="eyebrow">Commit result</p>
          <h1>Excel commit summary</h1>
          <p>{preview.import.filename || "Uploaded Excel"} has finished processing against Tally.</p>
        </div>
        <div className="result-actions">
          <button className="ghost-button" onClick={() => setActiveView("history")}>
            View History
          </button>
          <button className="primary-button" onClick={() => setActiveView("upload")}>
            Upload Another Excel
          </button>
        </div>
      </div>
      <div className="stats-grid">
        <MetricCard label="Rows in File" value={formatNumber(previewSummary.totalRows)} />
        <MetricCard label="Created in Tally" value={formatNumber(summary.success_count)} tone="success" />
        <MetricCard label="Failed During Commit" value={formatNumber(summary.failed_count)} tone={summary.failed_count ? "error" : "success"} />
      </div>
      <CommitSummaryPanel summary={summary} />
      <section className="card">
        <h3>Row Results</h3>
        <RowsTable rows={resultRows} showCommit />
      </section>
    </div>
  );
}

export function HistoryView({
  imports,
  importDetails,
  setPreviewFromImport,
  error,
}: {
  imports: ImportRecord[];
  importDetails: ImportDetails;
  setPreviewFromImport: (importRecord: ImportRecord) => void;
  error: string;
}) {
  return (
    <div className="stack">
      <div className="page-intro">
        <h1>History/Logs</h1>
        <p>Review uploaded batches and committed vouchers without technical connector logs.</p>
      </div>
      {error && <p className="alert error-alert">{error}</p>}
      <section className="card">
        <div className="card-heading">
          <h3>Recent Activity</h3>
          <span>{imports.length} entries</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date/Time</th>
                <th>File Name</th>
                <th>Rows</th>
                <th>Success</th>
                <th>Failed</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {imports.map((item) => {
                const rows = importDetails[item.id] || [];
                const stats = deriveImportStats(rows);
                const status = deriveImportStatus(item, rows);
                return (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.completed_at || item.created_at)}</td>
                    <td>{item.filename || "Uploaded Excel"}</td>
                    <td>{item.row_count}</td>
                    <td>{stats.successCount}</td>
                    <td>{stats.failedCount}</td>
                    <td>
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </td>
                    <td>
                      <button className="link-button" onClick={() => setPreviewFromImport(item)}>
                        View Details
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!imports.length && (
                <tr>
                  <td colSpan={7}>No imports yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function RecentActivity({ imports, importDetails, setActiveView }: { imports: ImportRecord[]; importDetails: ImportDetails; setActiveView: (view: AppView) => void }) {
  return (
    <section className="card">
      <div className="card-heading">
        <h3>Recent Activity</h3>
        <button className="link-button" onClick={() => setActiveView("history")}>
          View All Logs
        </button>
      </div>
      <div className="table-wrap inline-table">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Timestamp</th>
              <th>Rows</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {imports.map((item) => {
              const status = deriveImportStatus(item, importDetails[item.id] || []);
              return (
                <tr key={item.id}>
                  <td>{item.filename || "Uploaded Excel"}</td>
                  <td>{formatDateTime(item.created_at)}</td>
                  <td>{item.row_count}</td>
                  <td>
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </td>
                </tr>
              );
            })}
            {!imports.length && (
              <tr>
                <td colSpan={4}>No recent imports yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SummaryCards({ summary }: { summary: ReturnType<typeof summarizePreview> }) {
  return (
    <div className="stats-grid">
      <MetricCard label="Total Rows" value={formatNumber(summary.totalRows)} />
      <MetricCard label="Valid Rows" value={formatNumber(summary.validRows)} tone="success" />
      <MetricCard label="Errors Found" value={formatNumber(summary.errorRows)} tone={summary.errorRows ? "error" : "success"} />
      <MetricCard label="Ready to Sync" value={`${summary.readyPercentage}%`} inverse />
      <MetricCard label="Valid Amount" value={formatCurrency(summary.totalValidAmount)} />
      <MetricCard label="Date Range" value={summary.dateRangeText} />
    </div>
  );
}

function CommitSummaryPanel({ summary }: { summary: CommitSummary }) {
  const failedRows = summary.rows.filter((row) => row.commit_status === "failed");
  return (
    <section className="card result-summary">
      <h3>Commit Summary</h3>
      <div className="summary-line">
        <Badge tone="success">{summary.success_count} successful</Badge>
        <Badge tone={summary.failed_count ? "error" : "success"}>{summary.failed_count} failed</Badge>
      </div>
      {failedRows.length > 0 && (
        <ul>
          {failedRows.map((row) => (
            <li key={row.id}>
              Row {row.source_row_id}: {formatRowError(row.commit_error) || "Commit failed"}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RowsTable({ rows, showCommit = false }: { rows: ImportRow[]; showCommit?: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Row</th>
            <th>Product Name</th>
            <th>Price</th>
            <th>Payment Mode</th>
            <th>Voucher Date</th>
            <th>Status</th>
            <th>Error</th>
            {showCommit && <th>Voucher ID</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const validationTone = row.validation_status === "valid" ? "success" : "error";
            const commitTone = row.commit_status === "success" ? "success" : row.commit_status === "failed" ? "error" : validationTone;
            return (
              <tr key={row.id} className={row.validation_status === "invalid" || row.commit_status === "failed" ? "error-row" : ""}>
                <td>{row.source_row_id}</td>
                <td>{row.product_name}</td>
                <td>{formatCurrency(Number(row.price))}</td>
                <td>{row.payment_mode}</td>
                <td>{row.voucher_date}</td>
                <td>
                  <Badge tone={commitTone}>{row.commit_status === "success" ? "Committed" : row.commit_status === "failed" ? "Failed" : row.validation_status === "valid" ? "Valid" : "Error"}</Badge>
                </td>
                <td>{formatRowError(row.validation_error || row.commit_error)}</td>
                {showCommit && <td>{getVoucherIdentifier(row) || "-"}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TallyConnection({ status }: { status: TallyStatus | null }) {
  const connected = tallyIsConnected(status);
  return (
    <div className={connected ? "connection-mini connected" : "connection-mini disconnected"}>
      {connected ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
      <span>{status?.message || "Checking Tally connection..."}</span>
    </div>
  );
}

function StatusIcon({ connected }: { connected: boolean }) {
  return <span className={connected ? "status-icon connected" : "status-icon disconnected"}>{connected ? <CheckCircle2 size={28} /> : <XCircle size={28} />}</span>;
}

function MetricCard({ label, value, tone, inverse = false }: { label: string; value: string; tone?: "success" | "error"; inverse?: boolean }) {
  return (
    <section className={inverse ? "metric-card inverse" : "metric-card"}>
      <span>{label}</span>
      <strong className={tone ? `${tone}-text` : ""}>{value}</strong>
    </section>
  );
}

function Badge({ children, tone }: { children: React.ReactNode; tone: "success" | "error" | "warning" | "neutral" }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

function viewTitle(view: AppView) {
  if (view === "upload") return "Upload Page";
  if (view === "preview") return "Preview Page";
  if (view === "result") return "Commit Result";
  if (view === "history") return "History/Logs";
  return "Dashboard";
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}
