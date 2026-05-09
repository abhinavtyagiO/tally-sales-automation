"use client";

import { ChangeEvent, RefObject, useEffect, useMemo, useRef, useState } from "react";
import { Building2, CheckCircle2, FileSpreadsheet, LogOut, RefreshCw, UploadCloud, XCircle } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";
const ENABLE_DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";

type User = { email: string; name?: string };
type Company = {
  id: number;
  company_name: string;
  tally_url: string;
  last_sync_status?: string;
  last_sync_at?: string;
  last_selected_at?: string;
};
type TallyStatus = { status: "connected" | "disconnected"; detail?: string | null; message: string };
type TallyCompanies = { available: boolean; companies: string[]; message?: string | null };
type ImportRecord = {
  id: number;
  filename?: string;
  status: string;
  row_count: number;
  valid_count: number;
  error_count: number;
};
type ImportRow = {
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
};
type ImportPreview = { import: ImportRecord; rows: ImportRow[] };
type CommitSummary = { success_count: number; failed_count: number; rows: ImportRow[]; results: Array<{ import_row_id: number; status: string; error?: string }> };

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: { client_id: string; callback: (response: { credential?: string }) => void }) => void;
          renderButton: (element: HTMLElement, options: Record<string, string | number | boolean>) => void;
        };
      };
    };
  }
}

export default function Home() {
  const googleButtonRef = useRef<HTMLDivElement | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [activeCompanyId, setActiveCompanyId] = useState<number | null>(null);
  const [tallyStatus, setTallyStatus] = useState<TallyStatus | null>(null);
  const [tallyCompanies, setTallyCompanies] = useState<TallyCompanies>({ available: false, companies: [] });
  const [companyName, setCompanyName] = useState("");
  const [devEmail, setDevEmail] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [commitSummary, setCommitSummary] = useState<CommitSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("Ready");

  const activeCompany = useMemo(
    () => companies.find((company) => company.id === activeCompanyId) || companies[0] || null,
    [companies, activeCompanyId],
  );

  useEffect(() => {
    void loadSession();
  }, []);

  useEffect(() => {
    if (user || !GOOGLE_CLIENT_ID || !googleButtonRef.current) return;
    const renderGoogleButton = () => {
      if (!window.google || !googleButtonRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => {
          if (response.credential) void loginWithToken(response.credential);
        },
      });
      googleButtonRef.current.innerHTML = "";
      window.google.accounts.id.renderButton(googleButtonRef.current, { theme: "outline", size: "large", width: 280 });
    };
    if (window.google) {
      renderGoogleButton();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = renderGoogleButton;
    document.body.appendChild(script);
  }, [user]);

  async function api(path: string, init: RequestInit = {}) {
    const response = await fetch(`${API_URL}${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init.headers || {}) },
      ...init,
    });
    return parseResponse(response);
  }

  async function uploadApi(path: string, formData: FormData) {
    const response = await fetch(`${API_URL}${path}`, {
      method: "POST",
      credentials: "include",
      body: formData,
    });
    return parseResponse(response);
  }

  async function parseResponse(response: Response) {
    if (!response.ok) {
      let message = await response.text();
      try {
        const parsed = JSON.parse(message);
        message = parsed.detail || message;
      } catch {
        // Keep raw response text.
      }
      throw new Error(normalizeError(message, response.status));
    }
    return response.json();
  }

  async function loadSession() {
    try {
      const data = await api("/auth/me");
      setUser(data.user);
      await Promise.all([loadCompanies(), loadTallyStatus(), loadTallyCompanies()]);
    } catch {
      setUser(null);
    }
  }

  async function loginWithToken(idToken: string) {
    setBusy(true);
    setError("");
    try {
      const data = await api("/auth/google", { method: "POST", body: JSON.stringify({ id_token: idToken }) });
      setUser(data.user);
      await Promise.all([loadCompanies(), loadTallyStatus(), loadTallyCompanies()]);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  async function loginDev() {
    if (devEmail.trim()) await loginWithToken(`test:${devEmail.trim()}`);
  }

  async function logout() {
    setBusy(true);
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      // The local UI should still reset when the server session is already gone.
    } finally {
      setUser(null);
      setCompanies([]);
      setActiveCompanyId(null);
      setPreview(null);
      setCommitSummary(null);
      setTallyStatus(null);
      setBusy(false);
    }
  }

  async function loadCompanies() {
    const data = await api("/companies");
    setCompanies(data.companies);
    setActiveCompanyId(data.active_company_id || data.companies[0]?.id || null);
  }

  async function loadTallyStatus() {
    try {
      setTallyStatus(await api("/tally/status"));
    } catch (statusError) {
      setTallyStatus({ status: "disconnected", message: normalizeUnknown(statusError), detail: "unknown" });
    }
  }

  async function loadTallyCompanies() {
    try {
      setTallyCompanies(await api("/tally/companies"));
    } catch {
      setTallyCompanies({ available: false, companies: [], message: "Company list is unavailable. You can type the Tally company name." });
    }
  }

  async function refreshConnection() {
    setBusy(true);
    setError("");
    try {
      await Promise.all([loadTallyStatus(), loadTallyCompanies()]);
    } finally {
      setBusy(false);
    }
  }

  async function addCompany() {
    const name = companyName.trim();
    if (!name || busy) return;
    setBusy(true);
    setError("");
    setNotice("Checking Tally company...");
    try {
      const data = await api("/companies", { method: "POST", body: JSON.stringify({ company_name: name }) });
      await loadCompanies();
      setActiveCompanyId(data.company.id);
      setCompanyName("");
      setPreview(null);
      setCommitSummary(null);
      setNotice("Company is ready for Excel upload");
    } catch (companyError) {
      setError(companyError instanceof Error ? companyError.message : "Company was not added");
      setNotice("Company was not added");
    } finally {
      setBusy(false);
    }
  }

  async function selectCompany(companyId: number) {
    setBusy(true);
    setError("");
    try {
      const data = await api(`/companies/${companyId}/select`, { method: "POST" });
      setActiveCompanyId(data.company.id);
      setPreview(null);
      setCommitSummary(null);
      await loadCompanies();
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to select company");
    } finally {
      setBusy(false);
    }
  }

  async function uploadExcel(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !activeCompany || busy) return;
    setBusy(true);
    setError("");
    setCommitSummary(null);
    setNotice("Reading Excel and checking Tally data...");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const data = await uploadApi(`/companies/${activeCompany.id}/imports/upload`, formData);
      setPreview({ import: data.import, rows: data.rows });
      setNotice("Review the rows before committing to Tally");
      await loadCompanies();
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Excel upload failed");
      setNotice("Excel was not processed");
    } finally {
      setBusy(false);
    }
  }

  async function commitRows() {
    if (!activeCompany || !preview || busy) return;
    setBusy(true);
    setError("");
    setNotice("Committing valid rows to Tally...");
    try {
      const data = await api(`/companies/${activeCompany.id}/imports/${preview.import.id}/commit`, { method: "POST", body: JSON.stringify({}) });
      setCommitSummary(data);
      setPreview({ import: preview.import, rows: data.rows });
      setNotice("Commit complete");
    } catch (commitError) {
      setError(commitError instanceof Error ? commitError.message : "Commit failed");
      setNotice("Commit failed");
    } finally {
      setBusy(false);
    }
  }

  if (!user) {
    return (
      <main className="shell login">
        <LoginPanel
          googleButtonRef={googleButtonRef}
          devEmail={devEmail}
          setDevEmail={setDevEmail}
          loginDev={loginDev}
          busy={busy}
          error={error}
        />
      </main>
    );
  }

  return (
    <main className="shell">
      <Sidebar user={user} companies={companies} activeCompany={activeCompany} busy={busy} logout={logout} selectCompany={selectCompany} />
      <section className="workspace">
        <header>
          <div>
            <h2>{activeCompany ? activeCompany.company_name : "Company Setup"}</h2>
            <p className="muted">{notice}</p>
          </div>
          <button onClick={refreshConnection} disabled={busy} aria-label="Refresh Tally connection">
            <RefreshCw size={16} /> Check Tally
          </button>
        </header>

        <TallyConnection status={tallyStatus} />
        <CompanySetup
          companyName={companyName}
          setCompanyName={setCompanyName}
          tallyCompanies={tallyCompanies}
          addCompany={addCompany}
          busy={busy}
          existingCompanies={companies}
        />
        {error && <p className="error">{error}</p>}

        {activeCompany && <ImportWorkflow busy={busy} preview={preview} commitSummary={commitSummary} uploadExcel={uploadExcel} commitRows={commitRows} />}
      </section>
    </main>
  );
}

function LoginPanel({
  googleButtonRef,
  devEmail,
  setDevEmail,
  loginDev,
  busy,
  error,
}: {
  googleButtonRef: RefObject<HTMLDivElement | null>;
  devEmail: string;
  setDevEmail: (value: string) => void;
  loginDev: () => void;
  busy: boolean;
  error: string;
}) {
  return (
    <section className="panel login-panel">
      <h1>Tally Sales Automation</h1>
      {GOOGLE_CLIENT_ID ? (
        <div ref={googleButtonRef} />
      ) : ENABLE_DEV_LOGIN ? (
        <div className="login-form">
          <input value={devEmail} onChange={(event) => setDevEmail(event.target.value)} placeholder="Email for local dev" type="email" />
          <button onClick={loginDev} disabled={busy || !devEmail.trim()}>
            Sign in for local dev
          </button>
        </div>
      ) : (
        <p className="error">Google sign-in is not configured. Set Google client IDs before using the app.</p>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function Sidebar({
  user,
  companies,
  activeCompany,
  busy,
  logout,
  selectCompany,
}: {
  user: User;
  companies: Company[];
  activeCompany: Company | null;
  busy: boolean;
  logout: () => void;
  selectCompany: (companyId: number) => void;
}) {
  return (
    <aside>
      <h1>Tally Sales</h1>
      <p>{user.email}</p>
      <div className="company-list">
        {companies.map((company) => (
          <button key={company.id} className={company.id === activeCompany?.id ? "company-pill active" : "company-pill"} onClick={() => selectCompany(company.id)} disabled={busy}>
            {company.company_name}
          </button>
        ))}
      </div>
      <button onClick={logout} disabled={busy}>
        <LogOut size={16} /> Sign out
      </button>
    </aside>
  );
}

function TallyConnection({ status }: { status: TallyStatus | null }) {
  const connected = status?.status === "connected";
  return (
    <section className={connected ? "status-band connected" : "status-band disconnected"}>
      {connected ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
      <span>{status?.message || "Checking Tally connection..."}</span>
    </section>
  );
}

function CompanySetup({
  companyName,
  setCompanyName,
  tallyCompanies,
  addCompany,
  busy,
  existingCompanies,
}: {
  companyName: string;
  setCompanyName: (value: string) => void;
  tallyCompanies: TallyCompanies;
  addCompany: () => void;
  busy: boolean;
  existingCompanies: Company[];
}) {
  const duplicate = existingCompanies.some((company) => company.company_name.toLowerCase() === companyName.trim().toLowerCase());
  return (
    <section className="panel">
      <h3>Add Tally Company</h3>
      <div className="toolbar">
        {tallyCompanies.available ? (
          <select value={companyName} onChange={(event) => setCompanyName(event.target.value)} disabled={busy}>
            <option value="">Select company</option>
            {tallyCompanies.companies.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        ) : (
          <input value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="Tally company name" disabled={busy} />
        )}
        <button onClick={addCompany} disabled={busy || !companyName.trim() || duplicate}>
          <Building2 size={16} /> Add company
        </button>
      </div>
      {duplicate && <p className="error">This company is already added.</p>}
      {!tallyCompanies.available && tallyCompanies.message && <p className="muted">{tallyCompanies.message}</p>}
    </section>
  );
}

function ImportWorkflow({
  busy,
  preview,
  commitSummary,
  uploadExcel,
  commitRows,
}: {
  busy: boolean;
  preview: ImportPreview | null;
  commitSummary: CommitSummary | null;
  uploadExcel: (event: ChangeEvent<HTMLInputElement>) => void;
  commitRows: () => void;
}) {
  const validCount = preview?.rows.filter((row) => row.validation_status === "valid").length || 0;
  return (
    <section className="panel">
      <h3>Excel Import</h3>
      <div className="actions">
        <label className={busy ? "file-button disabled" : "file-button"}>
          <UploadCloud size={16} /> Upload Excel
          <input type="file" accept=".xlsx,.xls" onChange={uploadExcel} disabled={busy} />
        </label>
        {preview && (
          <button onClick={commitRows} disabled={busy || validCount === 0}>
            <FileSpreadsheet size={16} /> Commit valid rows
          </button>
        )}
      </div>
      {preview && <PreviewTable preview={preview} />}
      {commitSummary && <CommitSummaryView summary={commitSummary} />}
    </section>
  );
}

function PreviewTable({ preview }: { preview: ImportPreview }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Row</th>
            <th>Product</th>
            <th>Price</th>
            <th>Payment</th>
            <th>Date</th>
            <th>Status</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row) => (
            <tr key={row.id}>
              <td>{row.source_row_id}</td>
              <td>{row.product_name}</td>
              <td>{row.price}</td>
              <td>{row.payment_mode}</td>
              <td>{row.voucher_date}</td>
              <td>{row.validation_status === "valid" ? "Ready" : "Error"}</td>
              <td>{row.validation_error || row.commit_error || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CommitSummaryView({ summary }: { summary: CommitSummary }) {
  const failedRows = summary.rows.filter((row) => row.commit_status === "failed");
  return (
    <section className="summary">
      <strong>Commit summary</strong>
      <span>{summary.success_count} successful</span>
      <span>{summary.failed_count} failed</span>
      {failedRows.length > 0 && (
        <ul>
          {failedRows.map((row) => (
            <li key={row.id}>
              Row {row.source_row_id}: {row.commit_error}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function normalizeError(message: string, status: number) {
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (message.toLowerCase().includes("already added")) return "This company is already added.";
  if (message.toLowerCase().includes("company not found")) return "Company not found in Tally. Check the company name and try again.";
  if (message.toLowerCase().includes("connect to tally")) return "Can't connect to Tally right now. Please try again or contact support.";
  return message || "Something went wrong. Please try again.";
}

function normalizeUnknown(error: unknown) {
  return error instanceof Error ? error.message : "Can't connect to Tally right now. Please try again or contact support.";
}
