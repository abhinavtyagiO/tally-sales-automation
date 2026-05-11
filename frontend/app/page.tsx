"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AppShell, DashboardView, HistoryView, LoginPanel, PreviewCommitView, SetupView, UploadView } from "./components";
import { formatUserError, tallyIsConnected } from "./lib/derivations";
import type { AppView, CommitSummary, Company, ImportPreview, ImportRecord, ImportRow, TallyCompanies, TallyStatus, User } from "./lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";
const ENABLE_DEV_LOGIN = process.env.NEXT_PUBLIC_ENABLE_DEV_LOGIN === "true";

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
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [importDetails, setImportDetails] = useState<Record<number, ImportRow[]>>({});
  const [activeView, setActiveView] = useState<AppView>("dashboard");
  const [companyName, setCompanyName] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [devEmail, setDevEmail] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [commitSummary, setCommitSummary] = useState<CommitSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
      return;
    }
    void loadImports(activeCompany.id);
  }, [activeCompany?.id]);

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
      throw new Error(formatUserError(message, response.status));
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
      // Reset the local UI even if the server session has already expired.
    } finally {
      setUser(null);
      setCompanies([]);
      setActiveCompanyId(null);
      setImports([]);
      setImportDetails({});
      setPreview(null);
      setCommitSummary(null);
      setTallyStatus(null);
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
      setTallyCompanies(await api("/tally/companies"));
    } catch {
      setTallyCompanies({ available: false, companies: [], message: "Company list is unavailable. You can type the Tally company name." });
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
    try {
      const data = await api("/companies", { method: "POST", body: JSON.stringify({ company_name: name }) });
      await loadCompanies();
      setActiveCompanyId(data.company.id);
      setCompanyName("");
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
      const data = await api(`/companies/${activeCompany.id}/imports/${preview.import.id}/commit`, { method: "POST", body: JSON.stringify({}) });
      setCommitSummary(data);
      setPreview({ import: preview.import, rows: data.rows });
      setImportDetails((current) => ({ ...current, [preview.import.id]: data.rows }));
      await loadImports(activeCompany.id);
    } catch (commitError) {
      setError(commitError instanceof Error ? commitError.message : "Commit failed");
    } finally {
      setBusy(false);
    }
  }

  function setPreviewFromImport(importRecord: ImportRecord) {
    const rows = importDetails[importRecord.id] || [];
    setPreview({ import: importRecord, rows });
    setCommitSummary(null);
    setActiveView("preview");
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
          tallyCompanies={tallyCompanies}
          tallyStatus={tallyStatus}
          addCompany={addCompany}
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
          error={error}
        />
      )}
      {activeView === "upload" && (
        <UploadView selectedFile={selectedFile} setSelectedFile={setSelectedFile} processUpload={processUpload} tallyStatus={tallyStatus} busy={busy} error={error} />
      )}
      {activeView === "preview" &&
        (preview ? (
          <PreviewCommitView preview={preview} commitSummary={commitSummary} tallyStatus={tallyStatus} busy={busy} commitRows={commitRows} setActiveView={setActiveView} error={error} />
        ) : (
          <UploadView selectedFile={selectedFile} setSelectedFile={setSelectedFile} processUpload={processUpload} tallyStatus={tallyStatus} busy={busy} error={error} />
        ))}
      {activeView === "history" && <HistoryView imports={imports} importDetails={importDetails} setPreviewFromImport={setPreviewFromImport} error={error} />}
    </AppShell>
  );
}
