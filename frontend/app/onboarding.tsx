"use client";

import { useState } from "react";
import { Building2, Check, CheckCircle2, ClipboardCheck, Copy, Download, FileSpreadsheet, Loader2, LogOut, MonitorCheck, PlugZap, RefreshCw, TerminalSquare, Upload } from "lucide-react";

import type { OnboardingDerivedState, OnboardingStepId } from "./lib/onboarding";
import { getUserInitials, tallyIsConnected } from "./lib/derivations";
import { INDIAN_GST_STATES } from "./lib/gst";
import type { Company, HelperStatus, MasterSyncStatus, TallyCompanies, TallyStatus, User } from "./lib/types";

export function OnboardingFlow({
  user,
  state,
  busy,
  error,
  helperStatus,
  tallyStatus,
  tallyCompanies,
  syncStatus,
  helperInstallCommand,
  helperDownloadHref,
  helperDownloadConfigured,
  companyName,
  setCompanyName,
  supplierGstin,
  setSupplierGstin,
  supplierState,
  setSupplierState,
  existingCompanies,
  requestStep,
  completeWelcome,
  completePrepareTally,
  confirmHelperDownloaded,
  confirmCommandRun,
  acknowledgeConnection,
  startHelperSetup,
  refreshConnection,
  addCompany,
  retrySync,
  goToDashboard,
  goToUpload,
  logout,
}: {
  user: User;
  state: OnboardingDerivedState;
  busy: boolean;
  error: string;
  helperStatus: HelperStatus | null;
  tallyStatus: TallyStatus | null;
  tallyCompanies: TallyCompanies;
  syncStatus: MasterSyncStatus | null;
  helperInstallCommand: string;
  helperDownloadHref: string;
  helperDownloadConfigured: boolean;
  companyName: string;
  setCompanyName: (value: string) => void;
  supplierGstin: string;
  setSupplierGstin: (value: string) => void;
  supplierState: string;
  setSupplierState: (value: string) => void;
  existingCompanies: Company[];
  requestStep: (step: OnboardingStepId) => void;
  completeWelcome: () => void;
  completePrepareTally: () => void;
  confirmHelperDownloaded: () => void;
  confirmCommandRun: () => void;
  acknowledgeConnection: () => void;
  startHelperSetup: () => void;
  refreshConnection: () => void;
  addCompany: () => void;
  retrySync: () => void;
  goToDashboard: () => void;
  goToUpload: () => void;
  logout: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const duplicate = existingCompanies.some((company) => company.company_name.toLowerCase() === companyName.trim().toLowerCase());
  const gstinValue = supplierGstin.trim().toUpperCase();
  const gstinLooksValid = !gstinValue || /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(gstinValue);
  const canAddCompany = Boolean(companyName.trim() && gstinValue && supplierState.trim() && gstinLooksValid && !duplicate && !busy);

  async function copyCommand() {
    if (!helperInstallCommand) return;
    await navigator.clipboard.writeText(helperInstallCommand);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <main className="onboarding-page">
      <aside className="onboarding-sidebar">
        <div className="onboarding-brand">
          <span className="onboarding-brand-mark">
            <Building2 size={22} />
          </span>
          <div>
            <strong>AccountPilot</strong>
            <span>Tally setup</span>
          </div>
        </div>
        <nav className="onboarding-steps" aria-label="Onboarding steps">
          {state.steps.map((step, index) => (
            <button key={step.id} className={`onboarding-step ${step.status}`} disabled={step.locked} onClick={() => requestStep(step.id)}>
              <span className="onboarding-step-index">{step.status === "complete" ? <Check size={14} /> : index + 1}</span>
              <span>
                <small>{step.eyebrow}</small>
                {step.title}
              </span>
            </button>
          ))}
        </nav>
        <button className="ghost-button onboarding-signout" onClick={logout} disabled={busy}>
          <LogOut size={16} /> Sign out
        </button>
      </aside>

      <section className="onboarding-main">
        <header className="onboarding-header">
          <div>
            <p className="eyebrow">Step {state.currentStepIndex + 1} of {state.steps.length}</p>
            <div className="onboarding-progress" aria-label={`Setup ${state.progressPercent}% complete`}>
              <span style={{ width: `${state.progressPercent}%` }} />
            </div>
          </div>
          <div className="onboarding-user">
            <span className="avatar">{getUserInitials(user)}</span>
            <span>{user.email}</span>
          </div>
        </header>

        <section className="onboarding-card">
          {state.currentStepId === "welcome" && (
            <OnboardingScreen eyebrow="Welcome" title="Set up AccountPilot with Tally" description="Connect AccountPilot Helper, choose your Tally company, and sync ledgers and stock items before uploading Excel files.">
              <div className="onboarding-checklist">
                <ChecklistRow done label="Install AccountPilot Helper on the Windows Tally machine" />
                <ChecklistRow done label="Pair the helper with this signed-in account" />
                <ChecklistRow done label="Select or add the Tally company with GST details" />
                <ChecklistRow done label="Sync ledgers and stock items for uploads" />
              </div>
              <FooterActions primaryLabel="Start setup" primaryIcon={<MonitorCheck size={18} />} onPrimary={completeWelcome} busy={busy} />
            </OnboardingScreen>
          )}

          {state.currentStepId === "prepare_tally" && (
            <OnboardingScreen eyebrow="Prepare Tally" title="Open Tally and enable the local connection" description="Use the Windows machine where Tally is installed. Keep the target company open while setup continues.">
              <div className="instruction-list">
                <Instruction index="1" title="Open Tally" copy="Start Tally Prime and sign in as usual." />
                <Instruction index="2" title="Open the target company" copy="Select the company you want AccountPilot to use." />
                <Instruction index="3" title="Enable HTTP on port 9000" copy="Confirm Tally is listening locally at http://127.0.0.1:9000." />
              </div>
              <StatusPill tone="warning" label="Waiting for manual confirmation" />
              <FooterActions primaryLabel="I've enabled Tally connection" primaryIcon={<CheckCircle2 size={18} />} onPrimary={completePrepareTally} busy={busy} />
            </OnboardingScreen>
          )}

          {state.currentStepId === "download_helper" && (
            <OnboardingScreen eyebrow="Download Helper" title="Download AccountPilot Helper" description="Install the helper on the Windows computer where Tally runs. It will run in the background after setup.">
              <div className="download-panel">
                <Download size={32} />
                <div>
                  <strong>AccountPilotHelperSetup.exe</strong>
                  <p className="muted">The installer is usually saved in the Downloads folder.</p>
                </div>
              </div>
              {!helperDownloadConfigured && <p className="alert error-alert">The Windows helper download URL is not configured.</p>}
              {helperDownloadHref && (
                <a className="text-link" href={helperDownloadHref} target="_blank" rel="noreferrer">
                  Open installer download
                </a>
              )}
              <FooterActions
                secondaryLabel="Download for Windows"
                secondaryIcon={<Download size={18} />}
                onSecondary={startHelperSetup}
                primaryLabel="I've downloaded and installed it"
                primaryIcon={<CheckCircle2 size={18} />}
                onPrimary={confirmHelperDownloaded}
                primaryDisabled={!helperDownloadConfigured}
                busy={busy}
              />
            </OnboardingScreen>
          )}

          {state.currentStepId === "run_command" && (
            <OnboardingScreen eyebrow="PowerShell" title="Run the setup command" description="Copy this command into PowerShell after downloading the installer. This pairs the helper with your AccountPilot account.">
              <div className="command-box">
                <code>{helperInstallCommand || "Preparing setup command..."}</code>
                <button className="ghost-button" onClick={copyCommand} disabled={busy || !helperInstallCommand}>
                  {copied ? <CheckCircle2 size={16} /> : <Copy size={16} />} {copied ? "Copied" : "Copy command"}
                </button>
              </div>
              <FooterActions primaryLabel="I ran the command" primaryIcon={<TerminalSquare size={18} />} onPrimary={confirmCommandRun} primaryDisabled={!helperInstallCommand} busy={busy} />
            </OnboardingScreen>
          )}

          {state.currentStepId === "connecting" && (
            <OnboardingScreen eyebrow="Connecting" title="Waiting for AccountPilot Helper" description="Keep Tally open. AccountPilot is checking helper registration and loading companies from Tally.">
              <div className="onboarding-checklist">
                <ChecklistRow done={helperStatus?.status === "connected"} label="Helper paired with this account" />
                <ChecklistRow done={state.tallyDiscoveryReady} loading={helperStatus?.status === "connected" && !state.tallyDiscoveryReady} label="Tally reachable through helper" />
                <ChecklistRow done={state.connectionReady} label="Connection verified" />
              </div>
              <ConnectionSummary helperStatus={helperStatus} tallyCompanies={tallyCompanies} tallyStatus={tallyStatus} />
              <FooterActions secondaryLabel="Check again" secondaryIcon={<RefreshCw size={18} />} onSecondary={refreshConnection} primaryLabel="Continue" onPrimary={acknowledgeConnection} primaryDisabled={!state.connectionReady} busy={busy} />
            </OnboardingScreen>
          )}

          {state.currentStepId === "connected" && (
            <OnboardingScreen eyebrow="Connected" title="Tally is connected" description="AccountPilot Helper is paired and Tally is reachable. Continue to choose the company and complete setup.">
              <div className="success-panel">
                <CheckCircle2 size={40} />
                <div>
                  <strong>AccountPilot connected</strong>
                  <p>{helperStatus?.agent?.device_name || "Windows helper"} is ready for Tally work.</p>
                </div>
              </div>
              <FooterActions primaryLabel="Continue to company setup" primaryIcon={<Building2 size={18} />} onPrimary={acknowledgeConnection} busy={busy} />
            </OnboardingScreen>
          )}

          {state.currentStepId === "company" && (
            <OnboardingScreen eyebrow="Company Setup" title="Choose your Tally company" description="Select a company returned from Tally, or type it manually if it is not listed. GSTIN and state are required for GST invoice uploads.">
              {tallyCompanies.available && (
                <div className="company-options">
                  {tallyCompanies.companies.map((name) => (
                    <button key={name} className={companyName === name ? "company-option selected" : "company-option"} onClick={() => setCompanyName(name)} disabled={busy}>
                      <Building2 size={18} />
                      <span>{name}</span>
                      {companyName === name && <CheckCircle2 size={18} />}
                    </button>
                  ))}
                </div>
              )}
              <div className="onboarding-form-grid">
                <label>
                  <span className="field-label">Company name</span>
                  <input value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="Bhrama Enterprises" disabled={busy} />
                </label>
                <label>
                  <span className="field-label">Company GSTIN</span>
                  <input value={supplierGstin} onChange={(event) => setSupplierGstin(event.target.value.toUpperCase())} placeholder="29AAECP4424C1ZN" disabled={busy} />
                </label>
                <label>
                  <span className="field-label">Company GST state</span>
                  <select value={supplierState} onChange={(event) => setSupplierState(event.target.value)} disabled={busy}>
                    <option value="">Select GST state</option>
                    {INDIAN_GST_STATES.map((stateName) => (
                      <option key={stateName} value={stateName}>
                        {stateName}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {!tallyCompanies.available && tallyCompanies.message && <p className="muted">{tallyCompanies.message}</p>}
              {duplicate && <p className="alert error-alert">This company is already added.</p>}
              {gstinValue && !gstinLooksValid && <p className="alert error-alert">Enter a valid 15-character GSTIN.</p>}
              <FooterActions primaryLabel="Use this company" primaryIcon={<CheckCircle2 size={18} />} onPrimary={addCompany} primaryDisabled={!canAddCompany} busy={busy} />
            </OnboardingScreen>
          )}

          {state.currentStepId === "sync" && (
            <OnboardingScreen eyebrow="Sync Tally Data" title="Syncing ledgers and stock groups" description="AccountPilot is preparing the core Tally masters. Stock items will continue syncing by group in the background.">
              <div className="sync-panel">
                <Loader2 size={34} className={syncStatus?.status === "failed" ? "" : "spin"} />
                <div>
                  <strong>{syncStatus?.status === "failed" ? "Sync needs attention" : "Master sync in progress"}</strong>
                  <p>{syncStatus?.message || "Preparing sync..."}</p>
                </div>
              </div>
              <div className="onboarding-checklist">
                <ChecklistRow done={syncStatus?.status === "completed"} loading={syncStatus?.status === "syncing"} label="Ledgers synced" />
                <ChecklistRow done={syncStatus?.status === "completed"} loading={syncStatus?.status === "syncing"} label="Stock groups synced" />
              </div>
              <FooterActions secondaryLabel="Retry sync" secondaryIcon={<RefreshCw size={18} />} onSecondary={retrySync} primaryLabel="Continue" primaryDisabled={!state.syncReady} onPrimary={goToDashboard} busy={busy} />
            </OnboardingScreen>
          )}

          {state.currentStepId === "ready" && (
            <OnboardingScreen eyebrow="Ready" title="AccountPilot is ready" description="Your Tally connection, company details, ledgers, and stock groups are ready. Stock items continue syncing by group for Excel uploads.">
              <div className="ready-grid">
                <ReadyItem icon={<PlugZap size={20} />} label="Tally connected" />
                <ReadyItem icon={<Building2 size={20} />} label="Company selected" />
                <ReadyItem icon={<ClipboardCheck size={20} />} label="Ledgers synced" />
                <ReadyItem icon={<FileSpreadsheet size={20} />} label="Stock groups synced" />
              </div>
              <FooterActions
                secondaryLabel="Upload first Excel file"
                secondaryIcon={<Upload size={18} />}
                onSecondary={goToUpload}
                primaryLabel="Go to dashboard"
                primaryIcon={<CheckCircle2 size={18} />}
                onPrimary={goToDashboard}
                busy={busy}
              />
            </OnboardingScreen>
          )}

          {error && <p className="alert error-alert onboarding-error">{error}</p>}
        </section>
      </section>
    </main>
  );
}

function OnboardingScreen({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="onboarding-screen">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="lead">{description}</p>
      </div>
      {children}
    </div>
  );
}

function FooterActions({
  primaryLabel,
  primaryIcon,
  onPrimary,
  primaryDisabled,
  secondaryLabel,
  secondaryIcon,
  onSecondary,
  busy,
}: {
  primaryLabel: string;
  primaryIcon?: React.ReactNode;
  onPrimary: () => void;
  primaryDisabled?: boolean;
  secondaryLabel?: string;
  secondaryIcon?: React.ReactNode;
  onSecondary?: () => void;
  busy: boolean;
}) {
  return (
    <footer className="onboarding-footer">
      {secondaryLabel && onSecondary && (
        <button className="ghost-button" onClick={onSecondary} disabled={busy}>
          {secondaryIcon} {secondaryLabel}
        </button>
      )}
      <button className="primary-button" onClick={onPrimary} disabled={busy || primaryDisabled}>
        {primaryLabel}
        {primaryIcon}
      </button>
    </footer>
  );
}

function ChecklistRow({ done, loading, label }: { done: boolean; loading?: boolean; label: string }) {
  return (
    <div className={done ? "checklist-row done" : "checklist-row"}>
      <span>{done ? <Check size={16} /> : loading ? <Loader2 size={16} className="spin" /> : null}</span>
      <p>{label}</p>
    </div>
  );
}

function Instruction({ index, title, copy }: { index: string; title: string; copy: string }) {
  return (
    <div className="instruction">
      <span>{index}</span>
      <div>
        <strong>{title}</strong>
        <p>{copy}</p>
      </div>
    </div>
  );
}

function StatusPill({ tone, label }: { tone: "success" | "warning" | "error" | "neutral"; label: string }) {
  return <span className={`onboarding-pill ${tone}`}>{label}</span>;
}

function ConnectionSummary({ helperStatus, tallyCompanies, tallyStatus }: { helperStatus: HelperStatus | null; tallyCompanies: TallyCompanies; tallyStatus: TallyStatus | null }) {
  const connected = helperStatus?.status === "connected";
  return (
    <div className="connection-summary">
      <StatusPill tone={connected ? "success" : "warning"} label={helperStatus?.message || "Waiting for AccountPilot Helper"} />
      <StatusPill tone={tallyCompanies.status === "failed" || tallyStatus?.status === "disconnected" ? "error" : tallyCompanies.available || tallyIsConnected(tallyStatus) ? "success" : "warning"} label={tallyCompanies.message || tallyStatus?.message || "Checking Tally connection"} />
    </div>
  );
}

function ReadyItem({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="ready-item">
      <span>{icon}</span>
      <strong>{label}</strong>
    </div>
  );
}
