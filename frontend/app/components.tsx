"use client";

import { ChangeEvent, useMemo, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  Building2,
  CheckCircle2,
  ChevronRight,
  Copy,
  Download,
  FileSpreadsheet,
  History,
  LogOut,
  Package,
  RefreshCw,
  Search,
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
  importTypeLabel,
  lastSyncText,
  summarizePreview,
  tallyIsConnected,
  tallyIsChecking,
} from "./lib/derivations";
import { INDIAN_GST_STATES } from "./lib/gst";
import type { AppView, CommitRun, CommitSummary, Company, HelperStatus, ImportPreview, ImportRecord, ImportRow, ImportType, StockGroup, StockGroupItemsResponse, StockGroupsResponse, StockItem, TallyCompanies, TallyStatus, User } from "./lib/types";

type ImportDetails = Record<number, ImportRow[]>;
const INVENTORY_PAGE_SIZE = 15;

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
          <NavButton icon={<Package size={18} />} label="Inventory" active={activeView === "inventory"} disabled={!companies.length} onClick={() => setActiveView("inventory")} />
          <NavButton icon={<Upload size={18} />} label="Upload" active={activeView === "upload" || activeView === "preview"} disabled={!companies.length} onClick={() => setActiveView("upload")} />
          <NavButton icon={<History size={18} />} label="History/Logs" active={activeView === "history" || activeView === "historyDetail"} disabled={!companies.length} onClick={() => setActiveView("history")} />
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
  supplierGstin,
  setSupplierGstin,
  supplierState,
  setSupplierState,
  tallyCompanies,
  tallyStatus,
  helperStatus,
  helperInstallCommand,
  helperDownloadHref,
  addCompany,
  startHelperSetup,
  showHelperSetup,
  helperDownloadConfigured,
  refreshConnection,
  busy,
  existingCompanies,
  error,
}: {
  companyName: string;
  setCompanyName: (value: string) => void;
  supplierGstin: string;
  setSupplierGstin: (value: string) => void;
  supplierState: string;
  setSupplierState: (value: string) => void;
  tallyCompanies: TallyCompanies;
  tallyStatus: TallyStatus | null;
  helperStatus: HelperStatus | null;
  helperInstallCommand: string;
  helperDownloadHref: string;
  addCompany: () => void;
  startHelperSetup: () => void;
  showHelperSetup: boolean;
  helperDownloadConfigured: boolean;
  refreshConnection: () => void;
  busy: boolean;
  existingCompanies: Company[];
  error: string;
}) {
  const duplicate = existingCompanies.some((company) => company.company_name.toLowerCase() === companyName.trim().toLowerCase());
  const gstinValue = supplierGstin.trim().toUpperCase();
  const gstinLooksValid = !gstinValue || /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(gstinValue);
  const canAddCompany = Boolean(companyName.trim() && gstinValue && supplierState.trim() && gstinLooksValid && !duplicate && !busy);
  return (
    <div className="setup-layout">
      <section className="hero-panel">
        <StatusIcon connected={tallyIsConnected(tallyStatus)} checking={tallyIsChecking(tallyStatus)} />
        <div>
          <p className="eyebrow">First-run setup</p>
          <h1>Connect your Tally company</h1>
          <p className="lead">Add the company name and GST details exactly as they apply to your Tally company. AccountPilot will verify the company before saving.</p>
        </div>
      </section>
      <section className="card form-card">
        {showHelperSetup ? (
          <HelperSetupPanel
            status={helperStatus}
            installCommand={helperInstallCommand}
            downloadHref={helperDownloadHref}
            busy={busy}
            helperDownloadConfigured={helperDownloadConfigured}
            startHelperSetup={startHelperSetup}
            refreshConnection={refreshConnection}
          />
        ) : null}
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
          <button className="primary-button" onClick={addCompany} disabled={!canAddCompany}>
            Add Company
          </button>
        </div>
        <div className="setup-gst-grid">
          <div>
            <label className="field-label" htmlFor="supplier-gstin">
              Company GSTIN
            </label>
            <input id="supplier-gstin" value={supplierGstin} onChange={(event) => setSupplierGstin(event.target.value.toUpperCase())} placeholder="29AAECP4424C1ZN" disabled={busy} required />
          </div>
          <div>
            <label className="field-label" htmlFor="supplier-state">
              Company GST state
            </label>
            <select id="supplier-state" value={supplierState} onChange={(event) => setSupplierState(event.target.value)} disabled={busy} required>
              <option value="">Select GST state</option>
              {INDIAN_GST_STATES.map((stateName) => (
                <option key={stateName} value={stateName}>
                  {stateName}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="muted">GST details are required during setup so GST tax invoices can be created without extra configuration later.</p>
        {duplicate && <p className="alert error-alert">This company is already added.</p>}
        {gstinValue && !gstinLooksValid && <p className="alert error-alert">Enter a valid 15-character GSTIN.</p>}
        {!tallyCompanies.available && tallyCompanies.message && <p className="muted">{tallyCompanies.message}</p>}
        {error && <p className="alert error-alert">{error}</p>}
      </section>
    </div>
  );
}

function HelperSetupPanel({
  status,
  installCommand,
  downloadHref,
  busy,
  helperDownloadConfigured,
  startHelperSetup,
  refreshConnection,
}: {
  status: HelperStatus | null;
  installCommand: string;
  downloadHref: string;
  busy: boolean;
  helperDownloadConfigured: boolean;
  startHelperSetup: () => void;
  refreshConnection: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const current = status?.status || "helper_required";
  const connected = current === "connected";
  const waiting = current === "waiting_for_helper";
  async function copyInstallCommand() {
    if (!installCommand) return;
    await navigator.clipboard.writeText(installCommand);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }
  return (
    <div className={connected ? "helper-panel connected" : "helper-panel"}>
      <StatusIcon connected={connected} />
      <div>
        <p className="eyebrow">AccountPilot Helper</p>
        <h3>{connected ? "Helper connected" : waiting ? "Finish Helper setup" : "Install Helper on your Tally computer"}</h3>
        <p>{status?.message || "Install AccountPilot Helper to connect with Tally."}</p>
        {!connected && (
          <div className="helper-actions">
            <button className="primary-button" onClick={startHelperSetup} disabled={busy || !helperDownloadConfigured}>
              <DownloadIcon /> Download for Windows
            </button>
            <button className="ghost-button" onClick={refreshConnection} disabled={busy}>
              <RefreshCw size={16} /> Check again
            </button>
          </div>
        )}
        {installCommand && !connected && (
          <div className="helper-command">
            <p className="muted">Run this in PowerShell after downloading the installer.</p>
            <code>{installCommand}</code>
            <button className="ghost-button" onClick={copyInstallCommand} disabled={busy}>
              {copied ? <CheckCircle2 size={16} /> : <Copy size={16} />} {copied ? "Copied" : "Copy command"}
            </button>
            {downloadHref && (
              <a className="text-link" href={downloadHref} target="_blank" rel="noreferrer">
                Open installer download
              </a>
            )}
          </div>
        )}
        {!helperDownloadConfigured && !connected && <p className="muted">Helper download is not configured for this environment.</p>}
      </div>
    </div>
  );
}

function DownloadIcon() {
  return <Download size={16} />;
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
  stockGroups,
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
  stockGroups: StockGroupsResponse | null;
  error: string;
}) {
  const vouchersCreated = countCommittedVouchers(importDetails);
  const recentImports = imports.slice(0, 5);
  return (
    <div className="stack">
      {error && <p className="alert error-alert">{error}</p>}
      <div className="dashboard-grid">
        <section className="card connection-card">
          <StatusIcon connected={tallyIsConnected(tallyStatus)} checking={tallyIsChecking(tallyStatus)} />
          <div>
            <h3>Tally Prime Connection</h3>
            <p className={tallyIsConnected(tallyStatus) ? "status-line success-text" : tallyIsChecking(tallyStatus) ? "status-line checking-text" : "status-line error-text"}>
              {tallyIsConnected(tallyStatus) ? "Connected" : tallyIsChecking(tallyStatus) ? "Checking" : "Disconnected"}
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
          <button className="action-card" onClick={() => setActiveView("inventory")}>
            <Package size={22} />
            <strong>Inventory</strong>
            <span>{formatNumber(stockGroups?.total_items || 0)} synced stock items across {formatNumber(stockGroups?.count || 0)} groups.</span>
          </button>
          <MetricCard label="Vouchers Created" value={formatNumber(vouchersCreated)} />
          <MetricCard label="Imports Processed" value={formatNumber(imports.length)} />
        </div>
      </section>
      <RecentActivity imports={recentImports} importDetails={importDetails} setActiveView={setActiveView} />
    </div>
  );
}

export function InventoryView({
  stockGroups,
  activeCompany,
  api,
  busy,
  syncInventory,
  refreshInventory,
  error,
}: {
  stockGroups: StockGroupsResponse | null;
  activeCompany: Company;
  api: (path: string, init?: RequestInit) => Promise<any>;
  busy: boolean;
  syncInventory: () => Promise<void>;
  refreshInventory: () => Promise<void>;
  error: string;
}) {
  const [query, setQuery] = useState("");
  const [selectedGroup, setSelectedGroup] = useState<StockGroup | null>(null);
  const [groupItems, setGroupItems] = useState<StockGroupItemsResponse | null>(null);
  const [loadingGroupName, setLoadingGroupName] = useState<string | null>(null);
  const [groupError, setGroupError] = useState("");
  const [groupPage, setGroupPage] = useState(1);
  const groups = stockGroups?.groups || [];
  const filteredGroups = useMemo(
    () =>
      groups.filter((group) => {
        const searchText = `${group.name} ${group.parent_name || ""}`.toLowerCase();
        return searchText.includes(query.trim().toLowerCase());
      }),
    [groups, query],
  );

  async function openGroup(group: StockGroup) {
    setSelectedGroup(group);
    setGroupItems(null);
    setGroupError("");
    setGroupPage(1);
    setLoadingGroupName(group.name);
    try {
      const response = await api(`/companies/${activeCompany.id}/stock-group-items?group_name=${encodeURIComponent(group.name)}`);
      setSelectedGroup(response.group);
      setGroupItems(response);
    } catch (groupFetchError) {
      setGroupError(groupFetchError instanceof Error ? groupFetchError.message : "Could not load stock items for this group");
    } finally {
      setLoadingGroupName(null);
    }
  }

  async function retryGroup(group: StockGroup) {
    setLoadingGroupName(group.name);
    try {
      await api(`/companies/${activeCompany.id}/stock-groups/${group.id}/retry`, { method: "POST", body: JSON.stringify({}) });
      await refreshInventory();
    } finally {
      setLoadingGroupName(null);
    }
  }

  function closeGroup() {
    setSelectedGroup(null);
    setGroupItems(null);
    setGroupError("");
    setGroupPage(1);
  }

  const groupItemRows = groupItems?.items || [];
  const groupTotalPages = Math.max(1, Math.ceil(groupItemRows.length / INVENTORY_PAGE_SIZE));
  const safeGroupPage = Math.min(groupPage, groupTotalPages);
  const groupStartIndex = (safeGroupPage - 1) * INVENTORY_PAGE_SIZE;
  const paginatedGroupItems = groupItemRows.slice(groupStartIndex, groupStartIndex + INVENTORY_PAGE_SIZE);
  const groupRangeStart = groupItemRows.length ? groupStartIndex + 1 : 0;
  const groupRangeEnd = Math.min(groupStartIndex + INVENTORY_PAGE_SIZE, groupItemRows.length);

  if (selectedGroup) {
    return (
      <div className="stack">
        <div className="page-intro with-actions">
          <div>
            <button className="ghost-button back-button" onClick={closeGroup}>
              <ArrowLeft size={18} /> Back to stock groups
            </button>
            <p className="eyebrow">Stock Group</p>
            <h1>{selectedGroup.name}</h1>
            <p>Review stock items synced under this Tally stock group.</p>
          </div>
          <button className="primary-button" onClick={() => openGroup(selectedGroup)} disabled={loadingGroupName === selectedGroup.name}>
            <RefreshCw size={18} /> {loadingGroupName === selectedGroup.name ? "Refreshing..." : "Refresh Group"}
          </button>
        </div>
        {groupError && <p className="alert error-alert">{groupError}</p>}
        <section className="card inventory-card">
          {loadingGroupName === selectedGroup.name && !groupItems ? <p className="muted inventory-loading">Loading stock items...</p> : <InventoryTable items={paginatedGroupItems} />}
          <div className="table-footer inventory-detail-footer">
            <span>
              Showing {formatNumber(groupRangeStart)}-{formatNumber(groupRangeEnd)} of {formatNumber(groupItemRows.length)} items
            </span>
            <div className="pagination-controls">
              <button className="ghost-button" onClick={() => setGroupPage((page) => Math.max(1, page - 1))} disabled={safeGroupPage <= 1}>
                Previous
              </button>
              <span>
                Page {formatNumber(safeGroupPage)} of {formatNumber(groupTotalPages)}
              </span>
              <button className="ghost-button" onClick={() => setGroupPage((page) => Math.min(groupTotalPages, page + 1))} disabled={safeGroupPage >= groupTotalPages}>
                Next
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="page-intro with-actions">
        <div>
          <h1>Stock Inventory</h1>
          <p>Review the stock masters synced from your active Tally company.</p>
        </div>
        <button className="primary-button" onClick={syncInventory} disabled={busy}>
          <RefreshCw size={18} /> {busy ? "Syncing..." : "Sync Inventory"}
        </button>
      </div>
      {error && <p className="alert error-alert">{error}</p>}
      <div className="stats-grid">
        <MetricCard label="Stock Groups" value={formatNumber(stockGroups?.count || 0)} />
        <MetricCard label="Stock Items" value={formatNumber(stockGroups?.total_items || 0)} />
        <MetricCard label="Groups Needing Retry" value={formatNumber(stockGroups?.failed_count || 0)} tone={stockGroups?.failed_count ? "error" : "success"} />
      </div>
      <section className="card inventory-card">
        <div className="inventory-toolbar">
          <label className="search-box">
            <Search size={18} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search stock groups" />
          </label>
          {query && (
            <button className="ghost-button" onClick={() => setQuery("")}>
              Clear Filters
            </button>
          )}
        </div>
        <StockGroupsTable groups={filteredGroups} loadingGroupName={loadingGroupName} openGroup={openGroup} retryGroup={retryGroup} />
        <div className="table-footer">
          Showing {formatNumber(filteredGroups.length)} of {formatNumber(groups.length)} groups
          {stockGroups?.last_sync_at && <span>Last synced: {formatDateTime(stockGroups.last_sync_at)}</span>}
        </div>
      </section>
    </div>
  );
}

export function UploadView({
  selectedFile,
  setSelectedFile,
  importType,
  setImportType,
  processUpload,
  tallyStatus,
  stockGroups,
  busy,
  error,
}: {
  selectedFile: File | null;
  setSelectedFile: (file: File | null) => void;
  importType: ImportType;
  setImportType: (value: ImportType) => void;
  processUpload: () => void;
  tallyStatus: TallyStatus | null;
  stockGroups: StockGroupsResponse | null;
  busy: boolean;
  error: string;
}) {
  const connected = tallyIsConnected(tallyStatus);
  const stockSyncReady = Boolean(stockGroups?.stock_item_sync_ready);
  const isGst = importType === "gst_tax_invoice";
  const guidelines = isGst
    ? [
        "Use columns `voucher_date`, `buyer_name`, `buyer_gstin`, `buyer_state`, `product_name`, `quantity`, `rate`, and `payment_mode`.",
        "Buyer GSTIN must be valid and buyer state must match the place of supply.",
        "Product names must exactly match Tally stock items with GST rate configured.",
        "Valid rows become GST sales invoices with CGST/SGST or IGST calculated automatically.",
      ]
    : [
        "Use columns `product_name`, `price`, `payment_mode`, and `voucher_date`.",
        "Product names must exactly match stock items in Tally with GST rate configured.",
        "Price is GST-inclusive; CGST and SGST are calculated automatically.",
        "Each valid row becomes one sales invoice for an individual customer.",
        "Voucher dates must be valid.",
      ];
  return (
    <div className="upload-layout">
      <section>
        <div className="page-intro">
          <h1>Import Financial Records</h1>
          <p>Select an Excel file to validate sales rows against your active Tally company.</p>
        </div>
        <div className="upload-type-grid">
          <button className={importType === "retail_sales" ? "upload-type-card active" : "upload-type-card"} onClick={() => setImportType("retail_sales")} disabled={busy}>
            <FileSpreadsheet size={22} />
            <strong>Invoice for Individual Customers</strong>
            <span>GST-inclusive invoice rows</span>
          </button>
          <button className={isGst ? "upload-type-card active" : "upload-type-card"} onClick={() => setImportType("gst_tax_invoice")} disabled={busy}>
            <FileSpreadsheet size={22} />
            <strong>Invoice for GST Firms</strong>
            <span>Buyer GSTIN, state, tax and invoice rows</span>
          </button>
        </div>
        <label className="upload-picker">
          <Upload size={48} />
          <strong>{selectedFile ? selectedFile.name : `Choose your ${importTypeLabel(importType)} Excel`}</strong>
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
            {guidelines.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </section>
        <section className="card">
          <h3>Template</h3>
          <p className="muted">Download a starter sheet with the required headers for {importTypeLabel(importType).toLowerCase()}.</p>
          <button className="ghost-button wide-button" onClick={() => downloadTemplate(importType)} disabled={busy}>
            Download Template
          </button>
        </section>
        <section className="card">
          <h3>Tally Status</h3>
          <TallyConnection status={tallyStatus} />
          {!connected && <p className="alert warning-alert">You can choose a file, but processing needs a live Tally connection.</p>}
          {connected && !stockSyncReady && <p className="alert warning-alert">Stock items are still syncing by group. Upload will unlock when the background sync finishes.</p>}
        </section>
      </aside>
      <footer className="sticky-actions">
        {error && <p className="alert error-alert">{error}</p>}
        <button className="primary-button" onClick={processUpload} disabled={busy || !selectedFile || !connected || !stockSyncReady}>
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
  commitRun,
  busy,
  commitRows,
  setActiveView,
  error,
}: {
  preview: ImportPreview;
  tallyStatus: TallyStatus | null;
  commitRun: CommitRun | null;
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
          {commitRun && (
            <p className="muted">
              {commitRun.status === "queued" ? "Queued" : commitRun.status === "processing" ? "Creating vouchers" : "Finalizing"}: {commitRun.success_count} succeeded, {commitRun.failed_count} failed
            </p>
          )}
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
  openImportLog,
  error,
}: {
  imports: ImportRecord[];
  importDetails: ImportDetails;
  openImportLog: (importRecord: ImportRecord) => void;
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
                <th>Type</th>
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
                    <td>{importTypeLabel(item.import_type)}</td>
                    <td>{item.row_count}</td>
                    <td>{stats.successCount}</td>
                    <td>{stats.failedCount}</td>
                    <td>
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </td>
                    <td>
                      <button className="link-button" onClick={() => openImportLog(item)}>
                        View Details
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!imports.length && (
                <tr>
                  <td colSpan={8}>No imports yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export function HistoryDetailView({
  detail,
  setActiveView,
  error,
}: {
  detail: ImportPreview;
  setActiveView: (view: AppView) => void;
  error: string;
}) {
  const rows = detail.rows;
  const previewSummary = summarizePreview(rows);
  const stats = deriveImportStats(rows);
  const status = deriveImportStatus(detail.import, rows);
  return (
    <div className="stack">
      <div className="page-intro with-actions">
        <div>
          <p className="eyebrow">Upload log</p>
          <h1>{detail.import.filename || "Uploaded Excel"}</h1>
          <p>
            {importTypeLabel(detail.import.import_type)} uploaded on {formatDateTime(detail.import.created_at)}.
          </p>
        </div>
        <button className="ghost-button back-button" onClick={() => setActiveView("history")}>
          <ArrowLeft size={18} /> Back to History
        </button>
      </div>
      {error && <p className="alert error-alert">{error}</p>}
      <div className="stats-grid">
        <MetricCard label="Rows in File" value={formatNumber(detail.import.row_count)} />
        <MetricCard label="Valid Rows" value={formatNumber(previewSummary.validRows)} tone="success" />
        <MetricCard label="Invalid Rows" value={formatNumber(previewSummary.errorRows)} tone={previewSummary.errorRows ? "error" : "success"} />
        <MetricCard label="Committed" value={formatNumber(stats.successCount)} tone={stats.successCount ? "success" : undefined} />
        <MetricCard label="Failed" value={formatNumber(stats.failedCount)} tone={stats.failedCount ? "error" : undefined} />
        <MetricCard label="Pending" value={formatNumber(stats.pendingCount)} />
      </div>
      <section className="card">
        <div className="card-heading">
          <h3>Upload Event</h3>
          <Badge tone={status.tone}>{status.label}</Badge>
        </div>
        <div className="detail-grid">
          <p>
            <span>Created</span>
            <strong>{formatDateTime(detail.import.created_at)}</strong>
          </p>
          <p>
            <span>Completed</span>
            <strong>{formatDateTime(detail.import.completed_at)}</strong>
          </p>
          <p>
            <span>Upload Type</span>
            <strong>{importTypeLabel(detail.import.import_type)}</strong>
          </p>
          <p>
            <span>Total Value</span>
            <strong>{formatCurrency(previewSummary.totalValidAmount)}</strong>
          </p>
        </div>
      </section>
      <section className="card">
        <h3>Rows</h3>
        <RowsTable rows={rows} showCommit />
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
              <th>Type</th>
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
                  <td>{importTypeLabel(item.import_type)}</td>
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
                <td colSpan={5}>No recent imports yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StockGroupsTable({
  groups,
  loadingGroupName,
  openGroup,
  retryGroup,
}: {
  groups: StockGroup[];
  loadingGroupName: string | null;
  openGroup: (group: StockGroup) => void;
  retryGroup: (group: StockGroup) => void;
}) {
  return (
    <div className="table-wrap inventory-table">
      <table>
        <thead>
          <tr>
            <th>Stock Group</th>
            <th>Parent</th>
            <th>Items</th>
            <th>Last Synced</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => {
            const failed = group.sync_status === "failed";
            const empty = group.sync_status === "completed" && !group.item_count;
            return (
              <tr key={group.id} className={failed ? "warning-row" : ""}>
                <td>
                  <strong>{group.name}</strong>
                  {failed && group.sync_error ? <p className="muted">{group.sync_error}</p> : null}
                </td>
                <td>{group.parent_name || "-"}</td>
                <td>{formatNumber(group.item_count || 0)}</td>
                <td>{group.last_synced_at ? formatDateTime(group.last_synced_at) : "-"}</td>
                <td>
                  {failed ? (
                    <button className="ghost-button" onClick={() => retryGroup(group)} disabled={loadingGroupName === group.name}>
                      <RefreshCw size={16} /> Retry
                    </button>
                  ) : empty ? (
                    <span className="muted">No items</span>
                  ) : (
                    <button className="link-button" onClick={() => openGroup(group)} disabled={loadingGroupName === group.name || group.sync_status !== "completed"}>
                      View <ChevronRight size={16} />
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
          {!groups.length && (
            <tr>
              <td colSpan={5}>No stock groups found. Sync inventory after Tally is connected.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}


function InventoryTable({ items }: { items: StockItem[] }) {
  return (
    <div className="table-wrap inventory-table">
      <table>
        <thead>
          <tr>
            <th>Item Name</th>
            <th>Stock Group</th>
            <th>Category</th>
            <th>Unit</th>
            <th>GST</th>
            <th>Opening Bal.</th>
            <th>Closing Bal.</th>
            <th>Closing Value</th>
          </tr>
        </thead>
        <tbody>
          {!items.length && (
            <tr>
              <td colSpan={8}>No stock items found in this group.</td>
            </tr>
          )}
          {items.map((item) => {
            const closingQuantity = parseStockNumber(item.closing_balance);
            return (
              <tr key={item.id} className={closingQuantity !== null && closingQuantity <= 5 ? "warning-row" : ""}>
                <td>
                  <strong>{item.name}</strong>
                </td>
                <td>{item.group_name || "-"}</td>
                <td>{item.category ? <Badge tone="neutral">{item.category}</Badge> : "-"}</td>
                <td>{item.base_unit || "-"}</td>
                <td>{formatGst(item)}</td>
                <td>{item.opening_balance || "-"}</td>
                <td>
                  <strong className={closingQuantity !== null && closingQuantity <= 5 ? "error-text" : ""}>{item.closing_balance || "-"}</strong>
                </td>
                <td>{formatStockValue(item.closing_value)}</td>
              </tr>
            );
          })}
          {!items.length && (
            <tr>
              <td colSpan={8}>No stock items found. Sync inventory after Tally is connected.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
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
  const isGst = rows.some((row) => row.buyer_gstin || row.total_amount || row.gst_rate);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Row</th>
            <th>Product Name</th>
            {isGst && <th>Buyer</th>}
            {isGst && <th>GSTIN</th>}
            <th>{isGst ? "Taxable" : "Price"}</th>
            {isGst && <th>GST</th>}
            {isGst && <th>Total</th>}
            <th>Payment Mode</th>
            <th>Voucher Date</th>
            <th>Status</th>
            <th>Error</th>
            {showCommit && <th>Voucher ID</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const validationTone = row.validation_status === "valid" ? "success" : "error";
            const commitTone = row.commit_status === "success" ? "success" : row.commit_status === "failed" ? "error" : validationTone;
            return (
              <tr key={row.id} className={row.validation_status === "invalid" || row.commit_status === "failed" ? "error-row" : ""}>
                <td title={`Excel row ${row.source_row_id}`}>{index + 1}</td>
                <td>{row.product_name}</td>
                {isGst && <td>{row.buyer_name || "-"}</td>}
                {isGst && <td>{row.buyer_gstin || "-"}</td>}
                <td>{formatCurrency(Number(row.taxable_amount || row.price))}</td>
                {isGst && <td>{row.gst_rate ? `${row.gst_rate}%` : "-"}</td>}
                {isGst && <td>{formatCurrency(Number(row.total_amount || row.price))}</td>}
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

function downloadTemplate(importType: ImportType) {
  const rows =
    importType === "gst_tax_invoice"
      ? [
          ["voucher_date", "buyer_name", "buyer_gstin", "buyer_state", "buyer_address", "place_of_supply", "product_name", "quantity", "rate", "payment_mode"],
          ["2026-03-01", "Chanda Enterprises", "29AAACH1004N1ZQ", "Karnataka", "Bengaluru", "Karnataka", "GST Coffee", "20", "75", "Bank Transfer"],
        ]
      : [
          ["product_name", "price", "payment_mode", "voucher_date"],
          ["Coffee Powder", "450", "Cash", "2026-03-01"],
        ];
  const sheetRows = rows
    .map((row) => `<Row>${row.map((cell) => `<Cell><Data ss:Type="String">${escapeXml(cell)}</Data></Cell>`).join("")}</Row>`)
    .join("");
  const workbook = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
  xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:x="urn:schemas-microsoft-com:office:excel"
  xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
  <Worksheet ss:Name="Template"><Table>${sheetRows}</Table></Worksheet>
</Workbook>`;
  const blob = new Blob([workbook], { type: "application/vnd.ms-excel" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = importType === "gst_tax_invoice" ? "invoice-for-gst-firms-template.xls" : "invoice-for-individual-customers-template.xls";
  link.click();
  URL.revokeObjectURL(link.href);
}

function escapeXml(value: string) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function TallyConnection({ status }: { status: TallyStatus | null }) {
  const connected = tallyIsConnected(status);
  const checking = tallyIsChecking(status);
  return (
    <div className={connected ? "connection-mini connected" : checking ? "connection-mini checking" : "connection-mini disconnected"}>
      {connected ? <CheckCircle2 size={18} /> : checking ? <RefreshCw size={18} /> : <XCircle size={18} />}
      <span>{status?.message || "Checking Tally connection..."}</span>
    </div>
  );
}

function StatusIcon({ connected, checking = false }: { connected: boolean; checking?: boolean }) {
  return (
    <span className={connected ? "status-icon connected" : checking ? "status-icon checking" : "status-icon disconnected"}>
      {connected ? <CheckCircle2 size={28} /> : checking ? <RefreshCw size={28} /> : <XCircle size={28} />}
    </span>
  );
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
  if (view === "inventory") return "Inventory Management";
  if (view === "preview") return "Preview Page";
  if (view === "result") return "Commit Result";
  if (view === "history" || view === "historyDetail") return "History/Logs";
  return "Dashboard";
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatGst(item: StockItem) {
  if (item.gst_rate !== null && item.gst_rate !== undefined) return `${item.gst_rate}%`;
  return item.gst_type || "-";
}

function formatStockValue(value?: string | null) {
  const parsed = parseStockNumber(value);
  return parsed === null ? "-" : formatCurrency(parsed);
}

function parseStockNumber(value?: string | null) {
  if (!value) return null;
  const match = String(value).replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : null;
}
