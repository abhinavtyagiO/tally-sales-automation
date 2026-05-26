import type { Company, HelperStatus, MasterSyncStatus, TallyCompanies, TallyStatus } from "./types";

export type OnboardingStepId =
  | "welcome"
  | "prepare_tally"
  | "download_helper"
  | "run_command"
  | "connecting"
  | "connected"
  | "company"
  | "sync"
  | "ready";

export type OnboardingStepStatus = "locked" | "current" | "complete" | "available";

export type OnboardingLocalState = {
  welcomeComplete: boolean;
  tallyPrepared: boolean;
  helperDownloaded: boolean;
  commandRun: boolean;
  connectionAcknowledged: boolean;
};

export type OnboardingFacts = {
  helperSetupEnabled: boolean;
  activeCompany: Company | null;
  helperStatus: HelperStatus | null;
  tallyStatus: TallyStatus | null;
  tallyCompanies: TallyCompanies;
  syncStatus: MasterSyncStatus | null;
  local: OnboardingLocalState;
  requestedStepId?: OnboardingStepId | null;
  allowDevNavigation?: boolean;
};

export type OnboardingDerivedState = {
  currentStepId: OnboardingStepId;
  currentStepIndex: number;
  progressPercent: number;
  steps: Array<{
    id: OnboardingStepId;
    title: string;
    eyebrow: string;
    status: OnboardingStepStatus;
    locked: boolean;
  }>;
  helperReady: boolean;
  tallyDiscoveryReady: boolean;
  connectionReady: boolean;
  companyReady: boolean;
  syncReady: boolean;
  setupComplete: boolean;
};

export const ONBOARDING_STEPS: Array<{ id: OnboardingStepId; title: string; eyebrow: string }> = [
  { id: "welcome", title: "Welcome", eyebrow: "Start" },
  { id: "prepare_tally", title: "Prepare Tally", eyebrow: "Manual" },
  { id: "download_helper", title: "Download Helper", eyebrow: "Windows" },
  { id: "run_command", title: "Run Setup Command", eyebrow: "Pair" },
  { id: "connecting", title: "Connecting to Tally", eyebrow: "Verify" },
  { id: "connected", title: "Connected", eyebrow: "Success" },
  { id: "company", title: "Company Setup", eyebrow: "Tally" },
  { id: "sync", title: "Sync Tally Data", eyebrow: "Masters" },
  { id: "ready", title: "Ready", eyebrow: "Done" },
];

const STEP_INDEX = new Map(ONBOARDING_STEPS.map((step, index) => [step.id, index]));

export function deriveOnboardingState(facts: OnboardingFacts): OnboardingDerivedState {
  const helperReady = !facts.helperSetupEnabled || facts.helperStatus?.status === "connected";
  const tallyDiscoveryReady = !facts.helperSetupEnabled || facts.tallyCompanies.status === "available" || facts.tallyCompanies.status === "empty" || facts.tallyCompanies.available;
  const connectionReady = helperReady && tallyDiscoveryReady;
  const companyReady = Boolean(facts.activeCompany);
  const syncReady = isCompanySetupComplete(facts.activeCompany) || facts.syncStatus?.status === "completed";
  const setupComplete = companyReady && syncReady;
  const maxAllowedIndex = deriveMaxAllowedStepIndex(facts, { helperReady, connectionReady, companyReady, syncReady });
  const requestedIndex = facts.requestedStepId ? STEP_INDEX.get(facts.requestedStepId) ?? 0 : 0;
  const currentStepIndex = facts.allowDevNavigation ? requestedIndex : Math.min(requestedIndex, maxAllowedIndex);
  const currentStepId = ONBOARDING_STEPS[currentStepIndex]?.id || "welcome";
  const steps = ONBOARDING_STEPS.map((step, index) => {
    const locked = !facts.allowDevNavigation && index > maxAllowedIndex;
    let status: OnboardingStepStatus = "available";
    if (locked) status = "locked";
    else if (index < currentStepIndex) status = "complete";
    else if (index === currentStepIndex) status = "current";
    return { ...step, status, locked };
  });

  return {
    currentStepId,
    currentStepIndex,
    progressPercent: Math.round(((currentStepIndex + 1) / ONBOARDING_STEPS.length) * 100),
    steps,
    helperReady,
    tallyDiscoveryReady,
    connectionReady,
    companyReady,
    syncReady,
    setupComplete,
  };
}

export function isCompanySetupComplete(company: Company | null) {
  if (!company?.last_sync_at) return false;
  return ["success", "completed"].includes((company.last_sync_status || "").toLowerCase());
}

function deriveMaxAllowedStepIndex(
  facts: OnboardingFacts,
  readiness: { helperReady: boolean; connectionReady: boolean; companyReady: boolean; syncReady: boolean },
) {
  if (readiness.companyReady && readiness.syncReady) return stepIndex("ready");
  if (readiness.companyReady) return stepIndex("sync");
  if (facts.local.connectionAcknowledged && readiness.connectionReady) return stepIndex("company");
  if (readiness.connectionReady) return stepIndex("connected");
  if (readiness.helperReady) return stepIndex("connecting");
  if (facts.local.commandRun) return stepIndex("connecting");
  if (facts.local.helperDownloaded) return stepIndex("run_command");
  if (facts.local.tallyPrepared) return stepIndex("download_helper");
  if (facts.local.welcomeComplete) return stepIndex("prepare_tally");
  return stepIndex("welcome");
}

function stepIndex(stepId: OnboardingStepId) {
  return STEP_INDEX.get(stepId) ?? 0;
}
