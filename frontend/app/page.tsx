"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell, CommitResultView, DashboardView, HistoryDetailView, HistoryView, InventoryView, LoginPanel, PreviewCommitView, SetupView, UploadView } from "./components";
import { formatUserError, tallyIsConnected } from "./lib/derivations";
import type { AppView, CommitRun, CommitSummary, Company, HelperStatus, ImportPreview, ImportRecord, ImportRow, ImportType, StockItemsResponse, TallyCompanies, TallyStatus, User } from "./lib/types";

const CONFIGURED_API_URL = process.env.NEXT_PUBLIC_API_URL || "";
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";
const ENABLE_DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";
const HELPER_DOWNLOAD_URL = process.env.NEXT_PUBLIC_HELPER_DOWNLOAD_URL || "";
const CONNECTOR_MODE = (process.env.NEXT_PUBLIC_CONNECTOR_MODE || (process.env.NODE_ENV === "production" ? "polling" : "direct")).toLowerCase();
const HELPER_SETUP_ENABLED = CONNECTOR_MODE === "polling";
const SESSION_TOKEN_KEY = "accountpilot.session_token";

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
  const [helperStatus, setHelperStatus] = useState<HelperStatus | null>(null);
  const [helperInstallCommand, setHelperInstallCommand] = useState("");
  const [helperDownloadHref, setHelperDownloadHref] = useState("");
  const [tallyCompanies, setTallyCompanies] = useState<TallyCompanies>({ available: false, companies: [] });
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [importDetails, setImportDetails] = useState<Record<number, ImportRow[]>>({});
  const [stockItems, setStockItems] = useState<StockItemsResponse | null>(null);
  const [activeView, setActiveView] = useState<AppView>("dashboard");
  const [companyName, setCompanyName] = useState("");
  const [supplierGstin, setSupplierGstin] = useState("");
  const [supplierState, setSupplierState] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importType, setImportType] = useState<ImportType>("retail_sales");
  const [devEmail, setDevEmail] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [commitSummary, setCommitSummary] = useState<CommitSummary | null>(null);
  const [commitRun, setCommitRun] = useState<CommitRun | null>(null);
  const [historyDetail, setHistoryDetail] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const helperSetupInFlight = useRef(false);

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

  useEffect(() => {
    if (!activeCompany?.id) {
      setImports([]);
      setImportDetails({});
      setStockItems(null);
      return;
    }
    void Promise.all([
      loadImports(activeCompany.id),
      loadStockItems(activeCompany.id),
      HELPER_SETUP_ENABLED ? loadConnectorStatus(activeCompany.id) : loadTallyStatus(),
    ]);
  }, [activeCompany?.id]);

  useEffect(() => {
    if (!HELPER_SETUP_ENABLED || !user || helperStatus?.status === "connected") return;
    const interval = window.setInterval(() => {
      void loadHelperStatus();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [user, helperStatus?.status]);

  useEffect(() => {
    if (!HELPER_SETUP_ENABLED || !user || !helperStatus || helperStatus.status === "connected" || helperInstallCommand) return;
    void prepareHelperSetup();
  }, [user, helperStatus?.status, helperInstallCommand]);

  async function api(path: string, init: RequestInit = {}) {
    const sessionToken = getStoredSessionToken();
    const response = await fetch(`${apiUrl()}${path}`, {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}),
        ...(init.headers || {}),
      },
      ...init,
    });
    return parseResponse(response);
  }

  async function uploadApi(path: string, formData: FormData) {
    const sessionToken = getStoredSessionToken();
    const response = await fetch(`${apiUrl()}${path}`, {
      method: "POST",
      credentials: "include",
      headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : undefined,
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
      throw new Error(formatUserError(message, response.status));
    }
    return response.json();
  }

  async function loadSession() {
    try {
      const data = await api("/auth/me");
      setUser(data.user);
      await Promise.all([loadCompanies(), HELPER_SETUP_ENABLED ? loadHelperStatus() : Promise.resolve(), loadTallyStatus(), loadTallyCompanies()]);
    } catch {
      clearStoredSessionToken();
      setUser(null);
    }
  }

  async function loginWithToken(idToken: string) {
    setBusy(true);
    setError("");
    try {
      const data = await api("/auth/google", { method: "POST", body: JSON.stringify({ id_token: idToken }) });
      if (data.session_token) storeSessionToken(data.session_token);
      setUser(data.user);
      await Promise.all([loadCompanies(), HELPER_SETUP_ENABLED ? loadHelperStatus() : Promise.resolve(), loadTallyStatus(), loadTallyCompanies()]);
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
      // Reset the local UI even if the server session has already expired.
    } finally {
      clearStoredSessionToken();
      setUser(null);
      setCompanies([]);
      setActiveCompanyId(null);
      setImports([]);
      setImportDetails({});
      setStockItems(null);
      setPreview(null);
      setCommitSummary(null);
      setCommitRun(null);
      setHistoryDetail(null);
      setTallyStatus(null);
      setHelperStatus(null);
      setBusy(false);
      setActiveView("dashboard");
    }
  }

  async function loadCompanies() {
    const data = await api("/companies");
    setCompanies(data.companies);
    setActiveCompanyId(data.active_company_id || data.companies[0]?.id || null);
    if (!data.companies.length) setActiveView("dashboard");
  }

  async function loadTallyStatus() {
    try {
      setTallyStatus(await api("/tally/status"));
    } catch (statusError) {
      setTallyStatus({ status: "disconnected", message: statusError instanceof Error ? statusError.message : "Can't connect to Tally right now.", detail: "unknown" });
    }
  }

  async function loadTallyCompanies() {
    try {
      if (HELPER_SETUP_ENABLED && helperStatus?.status === "connected") {
        const connectorCompanies = await api("/connector/tally-companies");
        if (connectorCompanies.status === "not_requested") {
          const queued = await api("/connector/tally-companies/check", { method: "POST", body: JSON.stringify({}) });
          setTallyCompanies(queued.companies);
          return;
        }
        setTallyCompanies(connectorCompanies);
        return;
      }
      setTallyCompanies(await api("/tally/companies"));
    } catch {
      setTallyCompanies({ available: false, companies: [], message: "Company list is unavailable. You can type the Tally company name." });
    }
  }

  async function loadHelperStatus() {
    if (!HELPER_SETUP_ENABLED) {
      setHelperStatus(null);
      return;
    }
    try {
      setHelperStatus(await api("/connector/status"));
    } catch {
      setHelperStatus({ status: "helper_required", message: "Install AccountPilot Helper to connect with Tally.", agent: null });
    }
  }

  async function startHelperSetup() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const setup = await prepareHelperSetup();
      const downloadHref = setup?.downloadHref || helperDownloadHref;
      if (downloadHref) window.open(downloadHref, "_blank", "noopener,noreferrer");
    } catch (setupError) {
      setError(setupError instanceof Error ? setupError.message : "Unable to start AccountPilot Helper setup");
    } finally {
      setBusy(false);
    }
  }

  async function prepareHelperSetup() {
    if (!HELPER_SETUP_ENABLED || helperSetupInFlight.current) return null;
    helperSetupInFlight.current = true;
    try {
      const setup = await api("/connector/setup-session", { method: "POST", body: JSON.stringify({}) });
      const downloadHref = buildHelperDownloadHref(setup.setup_token);
      setHelperDownloadHref(downloadHref);
      setHelperInstallCommand(buildHelperInstallCommand(apiUrl(), setup.setup_token));
      await loadHelperStatus();
      return { downloadHref, setupToken: setup.setup_token };
    } finally {
      helperSetupInFlight.current = false;
    }
  }

  async function loadConnectorStatus(companyId: number) {
    try {
      const data = await api(`/companies/${companyId}/connector/status`);
      if (data?.status) setTallyStatus(data);
    } catch {
      // Keep the current direct-mode status if the tracer endpoint is unavailable.
    }
  }

  async function loadImports(companyId: number) {
    try {
      const data = await api(`/companies/${companyId}/imports`);
      const importRecords: ImportRecord[] = data.imports || [];
      setImports(importRecords);
      const detailEntries = await Promise.all(
        importRecords.slice(0, 25).map(async (item) => {
          try {
            const detail = await api(`/companies/${companyId}/imports/${item.id}`);
            return [item.id, detail.rows || []] as const;
          } catch {
            return [item.id, []] as const;
          }
        }),
      );
      setImportDetails(Object.fromEntries(detailEntries));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load imports");
    }
  }

  async function loadStockItems(companyId: number) {
    try {
      setStockItems(await api(`/companies/${companyId}/stock-items`));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load inventory");
    }
  }

  async function refreshConnection() {
    setBusy(true);
    setError("");
    try {
      if (HELPER_SETUP_ENABLED) await loadHelperStatus();
      if (HELPER_SETUP_ENABLED && activeCompany?.id) {
        try {
          await api(`/companies/${activeCompany.id}/connector/health-check`, { method: "POST", body: JSON.stringify({}) });
          await loadConnectorStatus(activeCompany.id);
        } catch (statusError) {
          setTallyStatus({ status: "disconnected", message: statusError instanceof Error ? statusError.message : "Can't connect to Tally right now.", detail: "connector_unavailable" });
        }
      } else {
        await loadTallyStatus();
      }
      await loadTallyCompanies();
    } finally {
      setBusy(false);
    }
  }

  async function syncInventory() {
    if (!activeCompany || busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`/companies/${activeCompany.id}/sync`, { method: "POST" });
      await Promise.all([loadCompanies(), loadStockItems(activeCompany.id), loadTallyStatus()]);
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Inventory sync failed");
    } finally {
      setBusy(false);
    }
  }

  async function addCompany() {
    const name = companyName.trim();
    const gstin = supplierGstin.trim().toUpperCase();
    const state = supplierState.trim();
    if (!name || !gstin || !state || busy) return;
    setBusy(true);
    setError("");
    try {
      const data = await api("/companies", {
        method: "POST",
        body: JSON.stringify({
          company_name: name,
          supplier_gstin: gstin,
          supplier_state: state,
        }),
      });
      await loadCompanies();
      setActiveCompanyId(data.company.id);
      setCompanyName("");
      setSupplierGstin("");
      setSupplierState("");
      setPreview(null);
      setCommitSummary(null);
      setActiveView("dashboard");
    } catch (companyError) {
      setError(companyError instanceof Error ? companyError.message : "Company was not added");
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
      setHistoryDetail(null);
      setSelectedFile(null);
      await loadCompanies();
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : "Unable to select company");
    } finally {
      setBusy(false);
    }
  }

  async function processUpload() {
    if (!selectedFile || !activeCompany || busy) return;
    if (!tallyIsConnected(tallyStatus)) {
      setError("Open Tally and refresh the connection before processing this file.");
      return;
    }
    setBusy(true);
    setError("");
    setCommitSummary(null);
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("import_type", importType);
      const data = await uploadApi(`/companies/${activeCompany.id}/imports/upload`, formData);
      const nextPreview = { import: data.import, rows: data.rows };
      setPreview(nextPreview);
      setImportDetails((current) => ({ ...current, [data.import.id]: data.rows }));
      setSelectedFile(null);
      setActiveView("preview");
      await Promise.all([loadCompanies(), loadImports(activeCompany.id)]);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Excel upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function commitRows() {
    if (!activeCompany || !preview || busy) return;
    setBusy(true);
    setError("");
    try {
      const started = await api(`/companies/${activeCompany.id}/imports/${preview.import.id}/commit-runs`, { method: "POST", body: JSON.stringify({}) });
      const completed = await waitForCommitRun(activeCompany.id, preview.import.id, started.commit_run);
      const summary = completed.result as CommitSummary | undefined;
      if (completed.status === "failed" || !summary?.rows) throw new Error(completed.error_message || "Commit failed");
      setCommitSummary(summary);
      setPreview({ import: preview.import, rows: summary.rows });
      setImportDetails((current) => ({ ...current, [preview.import.id]: summary.rows }));
      await loadImports(activeCompany.id);
      setActiveView("result");
    } catch (commitError) {
      setError(commitError instanceof Error ? commitError.message : "Commit failed");
    } finally {
      setBusy(false);
      setCommitRun(null);
    }
  }

  async function waitForCommitRun(companyId: number, importId: number, initialRun: CommitRun): Promise<CommitRun> {
    let current = initialRun;
    setCommitRun(current);
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (current.status === "completed" || current.status === "failed") return current;
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const data = await api(`/companies/${companyId}/imports/${importId}/commit-runs/${current.id}`);
      current = data.commit_run;
      setCommitRun(current);
    }
    throw new Error("Commit is still processing. Check history in a few minutes.");
  }

  async function openImportLog(importRecord: ImportRecord) {
    if (!activeCompany) return;
    setBusy(true);
    setError("");
    try {
      let rows = importDetails[importRecord.id] || [];
      if (!rows.length) {
        const detail = await api(`/companies/${activeCompany.id}/imports/${importRecord.id}`);
        rows = detail.rows || [];
        setImportDetails((current) => ({ ...current, [importRecord.id]: rows }));
      }
      setHistoryDetail({ import: importRecord, rows });
      setActiveView("historyDetail");
    } catch (detailError) {
      setError(detailError instanceof Error ? detailError.message : "Unable to load upload log");
    } finally {
      setBusy(false);
    }
  }

  if (!user) {
    return (
      <LoginPanel
        googleButtonRef={googleButtonRef}
        devEmail={devEmail}
        setDevEmail={setDevEmail}
        loginDev={loginDev}
        busy={busy}
        error={error}
        googleConfigured={Boolean(GOOGLE_CLIENT_ID)}
        devLoginEnabled={ENABLE_DEV_LOGIN}
      />
    );
  }

  if (!activeCompany) {
    return (
      <AppShell user={user} activeView="dashboard" setActiveView={setActiveView} activeCompany={null} companies={companies} busy={busy} logout={logout} refreshConnection={refreshConnection}>
        <SetupView
          companyName={companyName}
          setCompanyName={setCompanyName}
          supplierGstin={supplierGstin}
          setSupplierGstin={setSupplierGstin}
          supplierState={supplierState}
          setSupplierState={setSupplierState}
          tallyCompanies={tallyCompanies}
          tallyStatus={tallyStatus}
          helperStatus={helperStatus}
          helperInstallCommand={helperInstallCommand}
          helperDownloadHref={helperDownloadHref}
          addCompany={addCompany}
          startHelperSetup={startHelperSetup}
          showHelperSetup={HELPER_SETUP_ENABLED}
          helperDownloadConfigured={Boolean(HELPER_DOWNLOAD_URL)}
          refreshConnection={refreshConnection}
          busy={busy}
          existingCompanies={companies}
          error={error}
        />
      </AppShell>
    );
  }

  return (
    <AppShell
      user={user}
      activeView={activeView}
      setActiveView={setActiveView}
      activeCompany={activeCompany}
      companies={companies}
      busy={busy}
      logout={logout}
      refreshConnection={refreshConnection}
    >
      {activeView === "dashboard" && (
        <DashboardView
          activeCompany={activeCompany}
          companies={companies}
          imports={imports}
          importDetails={importDetails}
          tallyStatus={tallyStatus}
          busy={busy}
          selectCompany={selectCompany}
          setActiveView={setActiveView}
          stockItems={stockItems}
          error={error}
        />
      )}
      {activeView === "inventory" && <InventoryView stockItems={stockItems} busy={busy} syncInventory={syncInventory} error={error} />}
      {activeView === "upload" && (
        <UploadView
          selectedFile={selectedFile}
          setSelectedFile={setSelectedFile}
          importType={importType}
          setImportType={setImportType}
          processUpload={processUpload}
          tallyStatus={tallyStatus}
          busy={busy}
          error={error}
        />
      )}
      {activeView === "preview" &&
        (preview ? (
          <PreviewCommitView preview={preview} tallyStatus={tallyStatus} commitRun={commitRun} busy={busy} commitRows={commitRows} setActiveView={setActiveView} error={error} />
        ) : (
          <UploadView
            selectedFile={selectedFile}
            setSelectedFile={setSelectedFile}
            importType={importType}
            setImportType={setImportType}
            processUpload={processUpload}
            tallyStatus={tallyStatus}
            busy={busy}
            error={error}
          />
        ))}
      {activeView === "result" &&
        (preview && commitSummary ? (
          <CommitResultView preview={preview} summary={commitSummary} setActiveView={setActiveView} />
        ) : (
          <HistoryView imports={imports} importDetails={importDetails} openImportLog={openImportLog} error={error} />
        ))}
      {activeView === "history" && <HistoryView imports={imports} importDetails={importDetails} openImportLog={openImportLog} error={error} />}
      {activeView === "historyDetail" &&
        (historyDetail ? (
          <HistoryDetailView detail={historyDetail} setActiveView={setActiveView} error={error} />
        ) : (
          <HistoryView imports={imports} importDetails={importDetails} openImportLog={openImportLog} error={error} />
        ))}
    </AppShell>
  );
}

function apiUrl() {
  if (CONFIGURED_API_URL) return CONFIGURED_API_URL;
  if (typeof window === "undefined") return "http://localhost:8000";
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

function buildHelperInstallCommand(backendUrl: string, setupToken: string) {
  const quote = (value: string) => `'${value.replace(/'/g, "''")}'`;
  return `& "$env:USERPROFILE\\Downloads\\AccountPilotHelperSetup.exe" /BACKEND_URL=${quote(backendUrl)} /SETUP_TOKEN=${quote(setupToken)} /TALLY_URL='http://127.0.0.1:9000'`;
}

function buildHelperDownloadHref(setupToken: string) {
  if (!HELPER_DOWNLOAD_URL) return "";
  const url = new URL(HELPER_DOWNLOAD_URL, window.location.href);
  url.searchParams.set("setup_token", setupToken);
  url.searchParams.set("backend_url", apiUrl());
  return url.toString();
}

function getStoredSessionToken() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(SESSION_TOKEN_KEY) || "";
}

function storeSessionToken(token: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SESSION_TOKEN_KEY, token);
}

function clearStoredSessionToken() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SESSION_TOKEN_KEY);
}
