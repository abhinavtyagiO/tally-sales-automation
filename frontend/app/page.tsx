"use client";

import { useEffect, useMemo, useState } from "react";
import { Building2, LogOut, RefreshCw, UploadCloud, Wifi } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type User = { email: string; name?: string };
type Company = {
  id: number;
  company_name: string;
  tally_url: string;
  sales_ledger_name: string;
  cash_ledger_name: string;
  upi_fallback_ledger_name: string;
  upi_fallback_group_name: string;
  local_agent_id?: number;
  last_sync_status?: string;
  last_sync_at?: string;
};

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [activeCompanyId, setActiveCompanyId] = useState<number | null>(null);
  const [status, setStatus] = useState("Ready");
  const [companyName, setCompanyName] = useState("");
  const [pairingToken, setPairingToken] = useState("");

  const activeCompany = useMemo(
    () => companies.find((company) => company.id === activeCompanyId) || companies[0],
    [companies, activeCompanyId]
  );

  useEffect(() => {
    void loadMe();
  }, []);

  async function api(path: string, init: RequestInit = {}) {
    const response = await fetch(`${API_URL}${path}`, {
      credentials: "include",
      headers: {"Content-Type": "application/json", ...(init.headers || {})},
      ...init
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    return response.json();
  }

  async function loadMe() {
    try {
      const data = await api("/auth/me");
      setUser(data.user);
      await loadCompanies();
    } catch {
      setUser(null);
    }
  }

  async function login() {
    const email = window.prompt("Google email for MVP dev login");
    if (!email) return;
    const data = await api("/auth/google", {
      method: "POST",
      body: JSON.stringify({id_token: `test:${email}`})
    });
    setUser(data.user);
    await loadCompanies();
  }

  async function logout() {
    await api("/auth/logout", {method: "POST"});
    setUser(null);
    setCompanies([]);
  }

  async function loadCompanies() {
    const data = await api("/companies");
    setCompanies(data.companies);
    setActiveCompanyId(data.companies[0]?.id || null);
  }

  async function addCompany() {
    if (!companyName.trim()) return;
    await api("/companies", {
      method: "POST",
      body: JSON.stringify({company_name: companyName.trim()})
    });
    setCompanyName("");
    await loadCompanies();
  }

  async function createPairingToken() {
    if (!activeCompany) return;
    const data = await api(`/companies/${activeCompany.id}/agents/pairing-token`, {
      method: "POST",
      body: JSON.stringify({device_name: "Local Tally machine", base_url: "http://localhost:9100"})
    });
    setPairingToken(data.pairing_token);
    await loadCompanies();
  }

  async function syncMasters() {
    if (!activeCompany) return;
    setStatus("Syncing masters...");
    try {
      await api(`/companies/${activeCompany.id}/sync`, {method: "POST"});
      setStatus("Sync complete");
      await loadCompanies();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Sync failed");
    }
  }

  if (!user) {
    return (
      <main className="shell login">
        <section className="panel">
          <h1>Tally Sales Automation</h1>
          <button onClick={login}>Sign in with Google</button>
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <aside>
        <h1>Tally Sales</h1>
        <p>{user.email}</p>
        <button onClick={logout}><LogOut size={16} /> Sign out</button>
      </aside>
      <section className="workspace">
        <header>
          <h2>Company Setup</h2>
          <button onClick={loadCompanies}><RefreshCw size={16} /></button>
        </header>

        <div className="toolbar">
          <input value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="Tally company name" />
          <button onClick={addCompany}><Building2 size={16} /> Add company</button>
        </div>

        <div className="grid">
          {companies.map((company) => (
            <button
              key={company.id}
              className={company.id === activeCompany?.id ? "card active" : "card"}
              onClick={() => setActiveCompanyId(company.id)}
            >
              <strong>{company.company_name}</strong>
              <span>{company.tally_url}</span>
              <span>{company.last_sync_status || "not synced"}</span>
            </button>
          ))}
        </div>

        {activeCompany && (
          <section className="panel">
            <h2>{activeCompany.company_name}</h2>
            <div className="actions">
              <button onClick={createPairingToken}><Wifi size={16} /> Pair local agent</button>
              <button onClick={syncMasters}><RefreshCw size={16} /> Sync masters</button>
              <button disabled><UploadCloud size={16} /> Upload Excel</button>
            </div>
            {pairingToken && <pre>{pairingToken}</pre>}
            <p>{status}</p>
          </section>
        )}
      </section>
    </main>
  );
}
