/**
 * CSP DocMaker — API Client
 *
 * Centralized HTTP client for all backend API calls.
 * Handles authentication tokens, error responses, and type safety.
 */

import { withBase } from "./basePath";

const API_BASE = withBase("/api");

/** Document types — must match backend DocumentType enum values. */
export const DOCUMENT_TYPES = [
  { key: "csp_id_card", label: "CSP ID Card" },
  { key: "csp_certificate", label: "Appointment Letter" },
  { key: "training_certificate", label: "Training Certificate" },
  { key: "bcp", label: "Business Continuity Plan (BCP)" },
] as const;

export type DocumentTypeKey = (typeof DOCUMENT_TYPES)[number]["key"];

export interface AgentInfo {
  key: string;
  name: string;
  owns: string;
  does: string[];
  may: string[];
  proposes: string[];
  trigger: string;
  every_minutes: number | null;
  implemented: boolean;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_summary: string | null;
  consecutive_failures: number;
}

export interface AgentFinding {
  id: string;
  agent: string;
  severity: string;
  status: string;
  title: string;
  detail: string;
  proposal: Record<string, unknown> | null;
  needs_decision: boolean;
  subject_type: string | null;
  subject_id: string | null;
  created_at: string;
}

export interface MessageChannelInfo {
  id: string;
  name: string;
  kind: string;
  provider: string;
  is_default: boolean;
  active: boolean;
  secret_ref: string | null;
  config: Record<string, unknown>;
  last_error: string | null;
  last_used_at: string | null;
  can_send: boolean;
}

export interface MessageTemplateInfo {
  id: string;
  name: string;
  purpose: string;
  channel_kind: string;
  subject: string | null;
  body: string;
  languages: string[];
  active: boolean;
  is_builtin: boolean;
}

export interface WhatsAppCounts {
  total: number;
  not_sent: number;
  not_received: number;
  sent: number;
  delivered: number;
  read: number;
  responded: number;
  not_responded: number;
}

export interface WhatsAppMessageRow {
  id: string;
  kind: "data_request" | "missing_data" | "documents_ready" | "other";
  csp_id: string | null;
  csp_name: string | null;
  phone: string;
  is_test: boolean;
  sent_at: string | null;
  stage: "not_sent" | "not_received" | "sent" | "delivered" | "read";
  reason: string;
  delivery_updated_at: string | null;
  responded: boolean | null;
  responded_at: string | null;
  response_kind: "form" | "whatsapp" | null;
  response_text: string | null;
  auto_reply_at: string | null;
  auto_reply_text: string | null;
  job_id: string | null;
  check_error: string | null;
  source: string;
  /** Why it was sent (No. 156); null = the usual flow. */
  sent_because: string | null;
  sent_because_label: string;
}

/** How many messages were sent for each reason other than the usual flow. */
export interface SentBecause {
  key: string;
  label: string;
  count: number;
}

export interface WhatsAppReport {
  summary: Record<"data_request" | "missing_data" | "documents_ready", WhatsAppCounts>;
  rows: WhatsAppMessageRow[];
  total_rows: number;
  truncated: boolean;
  last_checked_at: string | null;
  status_days: number;
  sent_because: SentBecause[];
}

export interface WhatsAppFieldChange {
  field: string;
  label: string;
  before: string | null;
  after: string | null;
  outcome: "changed" | "added" | "confirmed" | "blank" | "given";
}

export interface WhatsAppMessageDetail {
  message: WhatsAppMessageRow;
  timeline: Array<{ at: string | null; what: string }>;
  request: {
    status: string;
    answered: boolean;
    answered_at: string | null;
    expires_at: string | null;
    fields: WhatsAppFieldChange[];
    counts: Record<WhatsAppFieldChange["outcome"], number>;
    before_known: boolean;
    photo_asked: boolean;
    photo_sent_at: string | null;
    sheet_saved: string[] | null;
    sheet_error: string | null;
  } | null;
}

export interface WhatsAppChat {
  phone: string;
  items: Array<{
    at: string;
    from: "us" | "csp";
    text: string;
    type: string;
    automatic: boolean;
  }>;
  error: string | null;
}

export interface WhatsAppRefreshResult {
  imported: number;
  checked: number;
  status_changed: number;
  responded: number;
  errors: string[];
}

export interface MessagingOverview {
  channels: MessageChannelInfo[];
  templates: MessageTemplateInfo[];
  campaigns: Array<{
    id: string; name: string; status: string; sent: number;
    failed: number; skipped: number; recipients: number;
    started_by: string | null; created_at: string;
  }>;
  channel_kinds: string[];
  providers: string[];
  purposes: string[];
}

export interface SendCandidate {
  csp_id: string;
  name: string;
  missing: string[];
  email: string;
  mobile: string;
  already_asked: boolean;
  reachable: boolean;
}

export interface SendResult {
  asked: number;
  sent: number;
  failed: number;
  results: Array<{ csp_id: string; sent: boolean; reason?: string }>;
}

export interface DashboardSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  icon: string;
  is_system: boolean;
  active: boolean;
  position: number;
  widget_count: number;
  can_remove: boolean;
  can_hide: boolean;
}

export interface WidgetData {
  id: string;
  kind: string;
  metric: string;
  title: string;
  config: Record<string, unknown>;
  width: number;
  position: number;
  shape: string | null;
  drillable: boolean;
  data?:
    | { value: number }
    | Array<{ label: string; value: number; key?: string }>
    | { columns: Array<{ key: string; label: string }>; rows: Array<Record<string, unknown>> };
  error?: string;
}

export interface DashboardDetail extends DashboardSummary {
  widgets: WidgetData[];
}

/** One recorded sign-in. The history only goes back to when recording
 *  began — before that only a single overwritten timestamp survived. */
export interface LoginEntry {
  at: string;
  address: string;
  role: string;
}

/** One pass an agent made: when, what it concluded, and whether it was a
 *  person clicking "Run now" or the schedule. */
export interface AgentRun {
  id: string;
  status: string;
  summary: string;
  detail: string | null;
  error: string | null;
  duration_ms: number | null;
  triggered_by: string | null;
  started_at: string;
  findings: number;
}

/** A sheet this workspace reads.
 *
 *  `tabs_live` is read from the spreadsheet on every request, so a tab
 *  added or removed in Google Sheets appears or disappears here on its
 *  own. It is null when the spreadsheet could not be opened, and `error`
 *  then says why. */
export interface SheetSource {
  id: string;
  name: string;
  title?: string;
  kind: string;
  purpose: string;
  active: boolean;
  spreadsheet_id: string;
  tab: string;
  tabs_configured: string[];
  last_status: string;
  last_error: string | null;
  tabs_live: Array<{
    tab_id: number;
    title: string;
    rows: number;
    columns: number;
  }> | null;
  error?: string | null;
}

/** One tab's contents. Each row carries its real spreadsheet row number,
 *  so an edit addresses the row a person can see, not an index into a
 *  list that shifts. */
export interface SheetTabData {
  tab: string;
  columns: string[];
  rows: Array<{ row_number: number; cells: Record<string, string> }>;
  truncated: boolean;
}

/** What a drillable number opens into. Columns vary by metric, so the
 *  table is driven by what the server sends rather than hard-coded. */
export interface MetricRecords {
  metric: string;
  columns: Array<{ key: string; label: string }>;
  rows: Array<Record<string, string>>;
  count: number;
  truncated: boolean;
}

export interface MetricOption {
  key: string;
  label: string;
  shape: string;
  description: string;
  widgets: string[];
  drillable: boolean;
}

export interface MetricGroup {
  group: string;
  label: string;
  metrics: MetricOption[];
}

export interface WidgetSpec {
  kind: string;
  metric: string;
  title: string;
  width: number;
}

export interface AccessPerson {
  email: string;
  name: string;
  mobile: string;
  role: "rm" | "admin";
  active: boolean;
  registered: boolean;
  last_login: string | null;
  synchronized_at: string | null;
}

export interface WorkspaceChoice {
  id: string;
  name: string;
  role: string;
}

/** What verify-otp and select-workspace answer. Either tokens, or — for
 *  someone in several workspaces — a list to choose from. */
export interface SignInResult {
  verified: boolean;
  access_token?: string;
  refresh_token?: string;
  role?: string;
  name?: string;
  workspace_id?: string;
  workspace_name?: string;
  choose_workspace?: boolean;
  workspaces?: WorkspaceChoice[];
  selection_token?: string;
}

export interface AccessListing {
  people: AccessPerson[];
  total: number;
  super_admins: string[];
  source: string;
  sync_interval_minutes: number;
}

export interface TemplateSummary {
  code: string;
  name: string;
  is_builtin: boolean;
  active: boolean;
  version: number;
  filename: string | null;
  photo_marker: string | null;
  placeholder_count: number;
  unmapped_count: number;
  ready: boolean;
  error?: string;
}

export interface TemplatePlaceholder {
  text: string;
  field: string;
  guessed: boolean;
}

export interface TemplateParagraph {
  index: number;
  text: string;
  has_placeholder: boolean;
}

export interface TemplateDetail extends TemplateSummary {
  placeholders: TemplatePlaceholder[];
  paragraphs: TemplateParagraph[];
  photo_marker_guess: string | null;
  fields: Array<{ field: string; label: string }>;
}

interface ApiError {
  /** Human-readable message, always a string. */
  detail: string;
  status: number;
  /** Structured error body when the backend returns an object detail
   *  (e.g. missing-data results on a 422). */
  data?: unknown;
}

/** Mirrors the backend CSPDetailResponse. Fields dropped when the schema
 *  moved to the real CSP sheet (module_name, onboarding_*, status) are gone. */
/** The Database section (Super Admin, No. 89). */
export interface DatabaseRow {
  csp_id: string;
  csp_code: string | null;
  name: string | null;
  level: string;
  district: string | null;
  state: string | null;
  rm_name: string | null;
  photo: string[];
  documents: string[];
  updated_at: string | null;
}

export interface DatabaseField {
  key: string;
  label: string;
  value: string | number | boolean | null;
}

export interface DatabaseRecord {
  csp_id: string;
  name: string | null;
  level: string;
  sheet: DatabaseField[];
  app: DatabaseField[];
  photos: { kind: string; filename: string; size: number; updated_at: string | null }[];
  documents: {
    document_type: string;
    label: string;
    versions: { id: string; version: number; filename: string; size: number; created_at: string | null }[];
  }[];
}

export interface CSPDetail {
  csp_id: string;
  csp_code?: string | null;
  name: string;
  email?: string | null;
  mobile?: string | null;
  address?: string | null;
  branch_name?: string | null;
  branch_code?: string | null;
  district?: string | null;
  state?: string | null;
  ao?: string | null;
  lho?: string | null;
  dc?: string | null;
  dc_email?: string | null;
  dc_contact?: string | null;
  rbo_name?: string | null;
  asm_name?: string | null;
  asm_email?: string | null;
  asm_contact?: string | null;
  photo_url?: string | null;
  certificate_date?: string | null;
  origin?: string | null;
  rm_name?: string | null;
  rm_email?: string | null;
  rm_resolution?: string | null;
  /** Why nothing may be sent to this CSP now (No. 121), or null. */
  send_hold?: string | null;
}

// ---- Ask-anything chat (No. 114) ----

export interface AssistantField {
  key: string;
  label: string;
  value: string | number | boolean | null;
}

export interface AssistantDocument {
  id: string;
  document_type: string;
  label: string;
  version: number;
  versions: number;
  filename: string;
  size: number;
  created_at: string | null;
}

export interface AssistantCspSummary {
  csp_code: string;
  name: string;
  district: string | null;
  state: string | null;
  branch_name: string | null;
  rm_name: string | null;
}

export type AssistantCard =
  | {
      type: "csp";
      csp_id: string;
      csp_code: string;
      name: string;
      fields: AssistantField[];
      documents: AssistantDocument[];
      has_photo: boolean;
    }
  | {
      type: "documents";
      csp_id: string;
      csp_code: string;
      name: string;
      documents: AssistantDocument[];
    }
  | {
      type: "csp_list";
      query: string;
      total: number;
      items: AssistantCspSummary[];
    }
  | {
      type: "draft";
      id: string;
      csp_id: string;
      csp_code: string;
      csp_name: string;
      channel: "whatsapp" | "email";
      to: string;
      preview: string;
      subject: string | null;
      expires_at: string;
    }
  | {
      type: "setup";
      done: number;
      total: number;
      complete: boolean;
      steps: AssistantSetupStep[];
    }
  | {
      type: "action";
      id: string;
      kind: string;
      title: string;
      detail: string;
      extra: string[];
      expires_at: string;
    };

// ---- Workspace setup through the chat (No. 117) ----

export interface AssistantSetupStep {
  key: string;
  title: string;
  status: "done" | "todo" | "problem" | "blocked" | "optional";
  label: string;
  detail: string;
  how: string;
  /** A question that makes the chat explain or offer to do this step. */
  ask: string | null;
}

export interface AssistantSetupStatus {
  owner: boolean;
  complete: boolean;
  done?: number;
  total?: number;
  reply?: string;
  cards?: AssistantCard[];
}

export interface AssistantActionResult {
  ok: boolean;
  message: string;
  next: { title: string; ask: string } | null;
}

export interface AssistantTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantAnswer {
  reply: string;
  cards: AssistantCard[];
  /** Questions to tap next: related Knowledge Base entries, or examples. */
  suggestions?: string[];
}

// ---- Emails (No. 127) ----

export interface EmailCounts {
  title: string;
  sent: number;
  failed: number;
  bounced: number;
  opened: number;
  not_opened: number;
}

export interface EmailRow {
  id: string;
  csp_id: string | null;
  csp_name: string | null;
  to: string;
  kind: string;
  subject: string;
  status: "failed" | "bounced" | "opened" | "not_opened";
  sent_at: string;
  error: string | null;
  opened_at: string | null;
  open_count: number;
  bounced_at: string | null;
  bounce_reason: string | null;
  sent_because: string | null;
  sent_because_label: string;
}

export interface EmailReport {
  counts: Record<string, EmailCounts>;
  sent_because: SentBecause[];
  total: number;
  messages: EmailRow[];
  note: string;
}

// ---- Data quality (No. 146) ----

export type FreshnessStatus = "ok" | "stale" | "stuck" | "failed" | "never";

export interface FreshnessBadge {
  source: string;
  label: string;
  status: FreshnessStatus;
  last_success_at: string | null;
  minutes_since_success: number | null;
  expected_every_minutes: number;
  unfinished_runs: number;
  /** Admins and Super Admins only, when the newest read failed. */
  error?: string;
}

/** Where one automatically filled value came from (CSP panel). */
export interface FieldSource {
  source: string;
  source_label: string;
  detail: string;
  status: "auto" | "confirmed" | "corrected";
  auto_value: string;
  checked_via: string | null;
  checked_at: string | null;
  filled_at: string | null;
}

export interface QualityCounts {
  auto: number;
  confirmed: number;
  corrected: number;
  withdrawn: number;
  filled: number;
  acceptance_rate: number | null;
  checked_kept_rate: number | null;
  avg_edit_distance: number | null;
}

export interface QualityFieldRow extends QualityCounts {
  field: string;
  label: string;
  source: string;
  source_label: string;
}

export interface QualityScoreboard {
  total: QualityCounts;
  fields: QualityFieldRow[];
  trend: Array<{
    week: string;
    filled: number;
    corrections: number;
    avg_edit_distance: number | null;
  }>;
}

/** Loop 5 (No. 152): did CSPs get their documents? */
export interface FeedbackSummary {
  asked: number;
  answers: { "1": number; "2": number; "3": number };
  no_answer: number;
  rows: {
    csp_id: string;
    csp_name: string;
    ask_status: string;
    asked_at: string | null;
    answer: string | null;
    answer_label: string;
    answer_text: string | null;
    answered_at: string | null;
    note: string;
  }[];
}

/** No. 154: drafts sent as they were, changed or skipped, per kind. */
export interface ReplyLearning {
  days: number;
  sent: number;
  unchanged: number;
  edited: number;
  skipped: number;
  unchanged_rate: number | null;
  kinds: {
    key: string;
    intents: string[];
    label: string;
    sent: number;
    unchanged: number;
    edited: number;
    skipped: number;
    unchanged_rate: number | null;
    avg_distance: number | null;
    skipped_rate: number | null;
    suggested: { text: string; times: number }[];
    can_use: boolean;
  }[];
}

/** A reply to what a CSP wrote on WhatsApp (No. 151). */
export interface CspReplyRow {
  id: string;
  csp_id: string;
  csp_name: string;
  messages: { at: string; text: string; type: string }[];
  last_in_at: string | null;
  intents: { key: string; label: string }[];
  reply_text: string;
  /** No. 154: the agent's own draft, and whether the person changed it. */
  draft_text: string;
  edited: boolean | null;
  edit_distance: number | null;
  action: string | null;
  status: "draft" | "sent" | "skipped" | "failed" | "expired";
  note: string;
  decided_by: string | null;
  sent_at: string | null;
}

/** Loop 1 (No. 150): a suggested fix to INFO from repeated corrections. */
export interface InfoSuggestion {
  id: string;
  field: string;
  label: string;
  rule: string;
  from_value: string;
  to_value: string;
  csps: { csp_id: string; name: string }[];
  still_wrong: number;
  status: "open" | "accepted" | "fixed" | "dismissed";
  decided_by: string | null;
  decided_at: string | null;
  fixed_at: string | null;
  /** No. 153: what the app changed in INFO itself. */
  applied: { cell: string; before: string; after: string }[];
  /** Why it was left for a person, or "INFO corrected by the app". */
  note: string;
  /** AO / RBO Name: the app fixes these in INFO itself. */
  automatic: boolean;
}

/** Loop 2 (No. 150): a bad WhatsApp number or a bounced email, and what was done. */
export interface ContactFixRow {
  csp_id: string;
  csp_name: string;
  problem: string;
  problem_label: string;
  bad_value: string;
  failed_kind: string;
  status: "open" | "trying_alternate" | "asked" | "corrected" | "resent" | "done" | "stopped";
  alternate: string | null;
  asked_via: string | null;
  asked_at: string | null;
  corrected_value: string | null;
  resent_at: string | null;
  tries: number;
  note: string;
  updated_at: string | null;
}

/** One way the app checks its own work (Data quality → Harness, No. 149). */
export interface HarnessCheck {
  key: string;
  name: string;
  watches: string;
  how: string;
  now: string;
  state: "ok" | "attention" | "empty" | "laptop";
}

/** One value the app filled in by itself, as the Data quality page lists it. */
export interface QualityValue {
  csp_id: string;
  csp_name: string;
  field: string;
  label: string;
  source: string;
  source_label: string;
  detail: string;
  status: "auto" | "confirmed" | "corrected" | "withdrawn";
  auto_value: string;
  current_value: string;
  edit_distance: number | null;
  checked_via: string | null;
  checked_by: string | null;
  checked_at: string | null;
  filled_at: string | null;
  editable: boolean;
  not_editable_reason: string;
}

export interface QualityCorrection {
  csp_id: string;
  field: string;
  label: string;
  source_label: string;
  auto_value: string;
  old_value: string;
  new_value: string;
  edit_distance: number;
  changed_via: string;
  changed_by: string | null;
  created_at: string | null;
}

// ---- Workspace Rules (No. 120) ----

export interface WorkspaceRulesInput {
  /** Domains that may join, e.g. ["eko.co.in"]; empty = any address. */
  allowed_email_domains: string[];
  session_hours: number;
  members_added_by: "owner" | "owner_and_admins";
  message_signoff: string;
}

export interface WorkspaceRules extends WorkspaceRulesInput {
  workspace: { id: string; name: string };
  allowed_email_domains_set: boolean;
  server_defaults: { allowed_email_domains: string[]; session_hours: number };
  /** After a save: wordings whose sign-off line was changed. */
  wordings_resigned?: string[];
  note?: string;
}

// ---- Knowledge Base (No. 116) ----

export interface KnowledgeEntry {
  id: string;
  question: string;
  phrasings: string;
  keywords: string;
  answer: string;
  category: string;
  active: boolean;
  updated_by: string | null;
  updated_at: string | null;
}

export type KnowledgeEntryInput = Omit<KnowledgeEntry, "id" | "updated_by" | "updated_at"> & {
  from_miss?: string | null;
};

export interface KnowledgeMiss {
  id: string;
  question: string;
  times_asked: number;
  last_asked_by: string | null;
  last_asked_at: string | null;
}

export interface KnowledgeTry {
  answer_at: number;
  suggest_at: number;
  matches: { id: string; question: string; score: number }[];
}

export interface AssistantSendResult {
  draft_id: string;
  channel: string;
  to: string;
  state: "sent" | "pending" | "rejected" | "failed";
  reason: string;
}

class ApiClient {
  // Only a fallback for browsers that refuse storage (some private modes).
  private accessToken: string | null = null;

  // The sign-in is kept in localStorage, not sessionStorage (No. 100): it
  // survives closing the tab or the browser, and lasts until the person logs
  // out or the server's 24 hours run out. Read from storage on every call,
  // so logging out in one tab logs out every tab.
  setToken(token: string) {
    this.accessToken = token;
    try {
      localStorage.setItem("access_token", token);
    } catch {
      /* storage refused: the in-memory copy serves this tab */
    }
  }

  getToken(): string | null {
    if (typeof window === "undefined") return null;
    try {
      return localStorage.getItem("access_token");
    } catch {
      return this.accessToken;
    }
  }

  clearToken() {
    this.accessToken = null;
    try {
      for (const key of ["access_token", "refresh_token", "user"]) {
        localStorage.removeItem(key);
        // Left by the version that kept the sign-in per tab.
        sessionStorage.removeItem(key);
      }
    } catch {
      /* nothing stored */
    }
  }

  /** fetch, but a network failure becomes an ApiError the screens can show
   *  instead of a bare "Failed to fetch". */
  private async send(url: string, init: RequestInit): Promise<Response> {
    try {
      return await fetch(url, init);
    } catch {
      throw {
        detail: "Cannot reach the server. Check your connection and try again.",
        status: 0,
      } as ApiError;
    }
  }

  /** Turn any failed response into the ApiError the screens display. */
  private async failure(
    response: Response,
    path: string,
    fallback: string
  ): Promise<ApiError> {
    let detail = fallback;
    let data: unknown;
    let readable = false;
    try {
      const err = await response.json();
      readable = true;
      if (typeof err.detail === "string") {
        detail = err.detail;
      } else if (err.detail && typeof err.detail === "object") {
        data = err.detail;
        if (typeof err.detail.message === "string") detail = err.detail.message;
      }
    } catch {
      // Not JSON: a proxy or gateway page rather than the app's own answer.
    }
    if (!readable && response.status >= 500) {
      detail = "The server is not responding right now. Please try again in a minute.";
    }
    // The Error ID support needs (the server sends it on every response).
    const errorId = response.headers.get("X-Request-ID");
    if (response.status >= 500 && errorId && !detail.includes(errorId)) {
      detail += ` (Error ID: ${errorId})`;
    }
    // A login lasts a limited time. When the server no longer accepts it,
    // start again at sign-in rather than leaving every screen failing.
    if (response.status === 401 && !path.startsWith("/auth/") && this.getToken()) {
      this.clearToken();
      if (typeof window !== "undefined") {
        // A full page load on purpose: it drops every screen's in-memory
        // state from the expired session (there is no router in this file).
        window.location.assign(withBase("/auth/login?expired=1"));
      }
    }
    return { detail, status: response.status, data };
  }

  private async request<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };

    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await this.send(`${API_BASE}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      throw await this.failure(response, path, "An unexpected error occurred");
    }

    return response.json() as Promise<T>;
  }

  // ---- Auth ----
  /** Which email domains may sign in. Fetched rather than hardcoded so the
      form and the server's own check can never disagree. */
  async authConfig() {
    return this.request<{
      allowed_email_domains: string[];
      allowed_email_domains_text: string;
    }>("/auth/config");
  }

  async signup(data: {
    email: string;
    name: string;
    password: string;
    requested_role: string;
    /** Only when signing up as a Super Admin of a new workspace. */
    workspace_name?: string;
  }) {
    return this.request<{ message: string; otp_sent: boolean }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async login(data: { email: string; password: string }) {
    return this.request<{
      message: string;
      otp_delivered: boolean;
    }>("/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async verifyOtp(data: { email: string; otp: string }) {
    return this.request<SignInResult>("/auth/verify-otp", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  /* Second step for someone in more than one workspace: the selection
     token from verifyOtp is exchanged for real tokens for one workspace. */
  async selectWorkspace(data: {
    selection_token: string;
    workspace_id: string;
  }) {
    return this.request<SignInResult>("/auth/select-workspace", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  /* The reply is the same whether or not the address has an account, so the
     screen must not treat it as confirmation that one exists. */
  async forgotPassword(email: string) {
    return this.request<{ message: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  }

  async resetPassword(data: {
    email: string;
    otp: string;
    new_password: string;
  }) {
    return this.request<{ message: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async logout() {
    try {
      await this.request("/auth/logout", { method: "POST" });
    } finally {
      this.clearToken();
    }
  }

  // ---- CSP ----
  async searchCSP(query: string) {
    return this.request<{
      results: CSPDetail[];
      total: number;
      query: string;
    }>(`/csps/search?q=${encodeURIComponent(query)}`);
  }

  async getCSP(cspId: string) {
    return this.request<CSPDetail>(`/csps/${encodeURIComponent(cspId)}`);
  }

  // ---- Alerts ----
  /** What this user is being asked to fix. An RM sees their own CSPs plus
   *  any that are unassigned; an Admin sees all of them. */
  async alerts() {
    return this.request<{
      alerts: Array<{
        id: string;
        csp_id: string;
        kind: string;
        message: string;
        unassigned: boolean;
        created_at: string;
        details?: {
          csp_id: string;
          csp_name: string;
          fields: Array<{
            field: string;
            label: string;
            type: string;
            blocks: string[];
          }>;
        };
      }>;
      total: number;
    }>("/alerts");
  }

  /** Upload a CSP's photo. Sent as multipart, so the JSON content type the
   *  other calls use must not be set here. */
  async uploadPhoto(cspId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    const token = this.getToken();
    const path = `/documents/upload-photo/${encodeURIComponent(cspId)}`;
    const response = await this.send(`${API_BASE}${path}`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body,
    });
    if (!response.ok) {
      throw await this.failure(response, path, "Photo upload failed");
    }
    return response.json();
  }

  /** Fill in a CSP's missing data. Keys must be real CSP fields — the
   *  backend rejects anything else rather than silently dropping it. */
  async updateCsp(cspId: string, updates: Record<string, string>) {
    return this.request<Record<string, unknown>>(
      `/csps/${encodeURIComponent(cspId)}`,
      { method: "PATCH", body: JSON.stringify(updates) }
    );
  }

  // ---- Documents ----
  async checkMissingData(cspId: string, documentTypes: DocumentTypeKey[]) {
    return this.request<{
      csp_id: string;
      csp_name: string;
      has_missing_data: boolean;
      total_missing_fields: number;
      documents: Array<{
        document_type: DocumentTypeKey;
        document_label: string;
        missing_fields: Array<{ field_name: string; field_label: string; field_type: string }>;
      }>;
    }>(`/documents/check-missing/${encodeURIComponent(cspId)}`, {
      method: "POST",
      body: JSON.stringify({ document_types: documentTypes }),
    });
  }

  // ---- Workflow ----
  async processWorkflow(data: {
    csp_id: string;
    document_types: DocumentTypeKey[];
  }) {
    return this.request<{
      job_id: string;
      csp_id: string;
      status: string;
      message?: string;
      ready_to_send: boolean;
      email_recipient?: string;
      document_types?: DocumentTypeKey[];
      document_labels?: string[];
      /** Set when status is "pending_data": what is missing, read-only. */
      missing_fields?: string[];
      missing_data?: unknown;
      /** Whether the CSP was actually asked for the missing details, and if not, why. */
      csp_asked?: { sent: boolean; via: string; reason: string };
    }>("/workflows/process", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  async getWorkflowStatus(jobId: string) {
    return this.request<{
      job_id: string;
      csp_id: string;
      current_state: string;
      error_message?: string;
      retry_count: number;
    }>(`/workflows/${encodeURIComponent(jobId)}`);
  }

  async confirmAndSend(jobId: string) {
    return this.request<{
      job_id: string;
      csp_id: string;
      status: string;
      message: string;
      email_sent: boolean;
      documents_sent: number;
    }>(`/workflows/${encodeURIComponent(jobId)}/confirm`, { method: "POST" });
  }

  // ---- Admin: CSP metrics ----
  async cspMetrics(filters: Record<string, string> = {}) {
    const query = new URLSearchParams(
      Object.entries(filters).filter(([, v]) => v)
    ).toString();
    return this.request<{
      filters_applied: Record<string, string>;
      totals: {
        csps: number;
        new: number;
        existing: number;
        awaiting_rm: number;
        details_fetched: number;
        details_missing: number;
      };
      documents: Array<{
        document_type: string;
        label: string;
        new: number;
        existing: number;
        /* Stored PDFs. */
        generated: number;
        /* Delivery of this document. The three partition the CSPs in
           scope, so they always sum to the total. */
        mailed: number;
        pending: number;
        failed: number;
      }>;
    }>(`/admin/csp-metrics${query ? `?${query}` : ""}`);
  }

  async cspFilters() {
    return this.request<{ filters: Record<string, string[]> }>(
      "/admin/csp-filters"
    );
  }

  /** One CSP for the admin top-bar search: details, and where each
   *  document stands (No. 101). */
  async cspSummary(cspId: string) {
    return this.request<{
      csp: CSPDetail;
      documents: Array<{
        document_type: string;
        label: string;
        applies: boolean;
        generated: boolean;
        version: number | null;
        generated_at: string | null;
        delivery: "mailed" | "failed" | "pending" | "not_for_this_csp";
      }>;
      /** Where each auto-filled value came from (No. 146); null if unreadable. */
      sources: Record<string, FieldSource> | null;
    }>(`/admin/csp/${encodeURIComponent(cspId)}/summary`);
  }

  async cspList(params: Record<string, string> = {}) {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v)
    ).toString();
    return this.request<{
      total: number;
      page: number;
      page_size: number;
      pages: number;
      csps: Array<{
        csp_id: string;
        name: string;
        origin: string | null;
        district: string | null;
        state: string | null;
        lho: string | null;
        rm_name: string | null;
        rm_resolution: string | null;
        circle_head: string | null;
      }>;
    }>(`/admin/csp-list${query ? `?${query}` : ""}`);
  }

  // ---- Admin ----
  async getDashboard() {
    return this.request<{
      metrics: {
        total_csps: number;
        new_csps_today: number;
        documents_generated_today: number;
        emails_sent_today: number;
        failed_emails_today: number;
        document_validation_failures_today: number;
        email_validation_failures_today: number;
        sms_failures_today: number;
        processing_failures_today: number;
        pending_jobs: number;
        running_jobs: number;
        successful_workflows_today: number;
        failed_workflows_today: number;
        total_retries_today: number;
        last_successful_automation: string | null;
      };
    }>("/admin/dashboard");
  }

  async getJobs(page = 1, pageSize = 20) {
    return this.request<{
      jobs: Array<Record<string, unknown>>;
      total: number;
      page: number;
      page_size: number;
    }>(`/admin/jobs?page=${page}&page_size=${pageSize}`);
  }

  async getAuditLogs(page = 1, pageSize = 50) {
    return this.request<{
      entries: Array<Record<string, unknown>>;
      total: number;
      page: number;
      page_size: number;
    }>(`/admin/audit-logs?page=${page}&page_size=${pageSize}`);
  }

  // ---- Database section (Super Admin, No. 89) ----

  async databaseList(q: string, offset = 0, limit = 50) {
    const params = new URLSearchParams({ q, offset: String(offset), limit: String(limit) });
    return this.request<{ total: number; items: DatabaseRow[] }>(
      `/admin/database?${params.toString()}`
    );
  }

  async databaseRecord(cspId: string) {
    return this.request<DatabaseRecord>(
      `/admin/database/${encodeURIComponent(cspId)}`
    );
  }

  /** A stored photo or PDF, fetched with the login so it can be shown. */
  /** The CSP's photo as every screen shows it — the passport version — or
   *  null when the app has none yet (No. 102). */
  async cspPhoto(cspId: string): Promise<Blob | null> {
    const path = `/csps/${encodeURIComponent(cspId)}/photo`;
    const token = this.getToken();
    const response = await this.send(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (response.status === 404) return null;
    if (!response.ok) {
      throw await this.failure(response, path, "Could not load the photo");
    }
    return response.blob();
  }

  async databaseFile(cspId: string, part: string): Promise<Blob> {
    const path = `/admin/database/${encodeURIComponent(cspId)}/${part}`;
    const token = this.getToken();
    const response = await this.send(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      throw await this.failure(response, path, "Could not open the file");
    }
    return response.blob();
  }

  // ---- Ask-anything chat (No. 114) ----
  async assistantStatus() {
    return this.request<{ available: boolean; provider: string }>(
      "/assistant/status"
    );
  }

  async assistantChat(messages: AssistantTurn[]) {
    return this.request<AssistantAnswer>(
      "/assistant/chat",
      { method: "POST", body: JSON.stringify({ messages }) }
    );
  }

  async assistantSetup() {
    return this.request<AssistantSetupStatus>("/assistant/setup");
  }

  async assistantRunAction(actionId: string) {
    return this.request<AssistantActionResult>(
      `/assistant/actions/${encodeURIComponent(actionId)}/run`,
      { method: "POST" }
    );
  }

  async assistantCancelAction(actionId: string) {
    return this.request<{ cancelled: boolean }>(
      `/assistant/actions/${encodeURIComponent(actionId)}`,
      { method: "DELETE" }
    );
  }

  // ---- Emails (No. 127; Admin + Super Admin) ----
  async emailMessages(filter: { kind?: string; status?: string; q?: string; because?: string }) {
    const params = new URLSearchParams();
    Object.entries(filter).forEach(([k, v]) => v && params.set(k, v));
    const qs = params.toString();
    return this.request<EmailReport>(`/admin/email-messages${qs ? `?${qs}` : ""}`);
  }

  // ---- Data quality (No. 146) ----
  async freshness() {
    return this.request<{ sources: FreshnessBadge[] }>("/quality/freshness");
  }

  async documentsFeedback() {
    return this.request<FeedbackSummary>("/admin/quality/feedback");
  }

  // ---- Replies to CSPs (No. 151) ----
  async cspReplies(status = "") {
    return this.request<{ mode: "off" | "draft" | "auto"; waiting: number; replies: CspReplyRow[] }>(
      `/admin/csp-replies${status ? `?status=${status}` : ""}`
    );
  }

  async replyLearning(days = 30) {
    return this.request<ReplyLearning>(`/admin/csp-replies/learning?days=${days}`);
  }

  async useReplyWording(intent: string, text: string) {
    return this.request<{ entry: string; text: string }>("/admin/csp-replies/learning/use", {
      method: "POST",
      body: JSON.stringify({ intent, text }),
    });
  }

  async sendCspReply(id: string, text: string) {
    return this.request<CspReplyRow>(`/admin/csp-replies/${encodeURIComponent(id)}/send`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  }

  async skipCspReply(id: string) {
    return this.request<CspReplyRow>(`/admin/csp-replies/${encodeURIComponent(id)}/skip`, {
      method: "POST",
    });
  }

  async setCspReplyMode(mode: "off" | "draft" | "auto") {
    return this.request<{ mode: "off" | "draft" | "auto" }>("/admin/csp-replies/mode", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    });
  }

  async qualitySuggestions(status = "") {
    return this.request<{ suggestions: InfoSuggestion[]; min_csps: number }>(
      `/admin/quality/suggestions${status ? `?status=${status}` : ""}`
    );
  }

  async decideSuggestion(id: string, action: "accept" | "dismiss") {
    return this.request<{ id: string; status: InfoSuggestion["status"] }>(
      `/admin/quality/suggestions/${encodeURIComponent(id)}/${action}`,
      { method: "POST" }
    );
  }

  async contactFixes(status = "") {
    return this.request<{ totals: Record<string, number>; fixes: ContactFixRow[] }>(
      `/admin/quality/contact-fixes${status ? `?status=${status}` : ""}`
    );
  }

  async qualityHarness() {
    return this.request<{ checks: HarnessCheck[] }>("/admin/quality/harness");
  }

  async qualityScoreboard(weeks = 8) {
    return this.request<QualityScoreboard>(
      `/admin/quality/scoreboard?weeks=${weeks}`
    );
  }

  async qualityCorrections(params: { limit?: number; offset?: number; field?: string } = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && query.set(k, String(v)));
    const qs = query.toString();
    return this.request<{ total: number; corrections: QualityCorrection[] }>(
      `/admin/quality/corrections${qs ? `?${qs}` : ""}`
    );
  }

  async qualityValues(params: { status?: string; field?: string; q?: string; limit?: number; offset?: number } = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && query.set(k, String(v)));
    const qs = query.toString();
    return this.request<{ total: number; values: QualityValue[] }>(
      `/admin/quality/values${qs ? `?${qs}` : ""}`
    );
  }

  async confirmQualityValue(body: { csp_id: string; field: string; current_value: string }) {
    return this.request<QualityValue>("/admin/quality/values/confirm", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async correctQualityValue(body: {
    csp_id: string;
    field: string;
    current_value: string;
    new_value: string;
  }) {
    return this.request<QualityValue>("/admin/quality/values/correct", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async checkEmailBounces() {
    return this.request<{ checked: boolean; notices?: number; marked?: number; reason?: string }>(
      "/admin/email-messages/refresh",
      { method: "POST" }
    );
  }

  // ---- Workspace Rules (No. 120; read: Admin + Owner, change: Owner) ----
  async workspaceRules() {
    return this.request<WorkspaceRules>("/admin/workspace-rules");
  }

  async saveWorkspaceRules(rules: WorkspaceRulesInput) {
    return this.request<WorkspaceRules>("/admin/workspace-rules", {
      method: "PUT",
      body: JSON.stringify(rules),
    });
  }

  // ---- Knowledge Base (No. 116; Admin + Super Admin) ----
  async knowledgeList() {
    return this.request<{ entries: KnowledgeEntry[] }>("/admin/knowledge");
  }

  async knowledgeAdd(entry: KnowledgeEntryInput) {
    return this.request<KnowledgeEntry>("/admin/knowledge", {
      method: "POST",
      body: JSON.stringify(entry),
    });
  }

  async knowledgeChange(id: string, entry: KnowledgeEntryInput) {
    return this.request<KnowledgeEntry>(`/admin/knowledge/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(entry),
    });
  }

  async knowledgeDelete(id: string) {
    return this.request<{ deleted: boolean }>(`/admin/knowledge/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  async knowledgeTry(question: string) {
    return this.request<KnowledgeTry>("/admin/knowledge/try", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
  }

  async knowledgeMisses() {
    return this.request<{ misses: KnowledgeMiss[] }>("/admin/knowledge/misses");
  }

  async knowledgeDismissMiss(id: string) {
    return this.request<{ dismissed: boolean }>(
      `/admin/knowledge/misses/${encodeURIComponent(id)}`,
      { method: "DELETE" }
    );
  }

  async assistantSend(draftId: string) {
    return this.request<AssistantSendResult>(
      `/assistant/drafts/${encodeURIComponent(draftId)}/send`,
      { method: "POST" }
    );
  }

  async assistantCancel(draftId: string) {
    return this.request<{ cancelled: boolean }>(
      `/assistant/drafts/${encodeURIComponent(draftId)}`,
      { method: "DELETE" }
    );
  }

  /** A PDF the chat offered, fetched with the login so it can be saved. */
  async assistantDocument(documentId: string): Promise<Blob> {
    const path = `/assistant/documents/${encodeURIComponent(documentId)}`;
    const token = this.getToken();
    const response = await this.send(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      throw await this.failure(response, path, "Could not download the document");
    }
    return response.blob();
  }

  // ---- Document templates (admin) ----

  /** Upload a file. Content-Type is deliberately NOT set: the browser has to
   *  add the multipart boundary itself, and setting it breaks the upload. */
  private async upload<T>(path: string, form: FormData): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const response = await this.send(`${API_BASE}${path}`, {
      method: "POST",
      headers,
      body: form,
    });
    if (!response.ok) {
      throw await this.failure(response, path, "Upload failed");
    }
    return response.json() as Promise<T>;
  }

  async listTemplates() {
    return this.request<{ templates: TemplateSummary[]; total: number }>(
      "/admin/templates"
    );
  }

  async getTemplate(code: string) {
    return this.request<TemplateDetail>(
      `/admin/templates/${encodeURIComponent(code)}`
    );
  }

  async uploadTemplate(code: string, name: string, file: File) {
    const form = new FormData();
    form.append("code", code);
    form.append("name", name);
    form.append("file", file);
    return this.upload<TemplateSummary & { message: string; unmapped: string[] }>(
      "/admin/templates",
      form
    );
  }

  async uploadTemplateVersion(code: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    return this.upload<TemplateSummary & { unmapped: string[] }>(
      `/admin/templates/${encodeURIComponent(code)}/version`,
      form
    );
  }

  async updateTemplate(
    code: string,
    settings: {
      name?: string;
      placeholder_map?: Record<string, string>;
      photo_marker?: string;
      active?: boolean;
    }
  ) {
    return this.request<TemplateSummary>(
      `/admin/templates/${encodeURIComponent(code)}`,
      { method: "PATCH", body: JSON.stringify(settings) }
    );
  }

  async editTemplateContent(code: string, edits: Record<string, string>) {
    return this.request<TemplateDetail>(
      `/admin/templates/${encodeURIComponent(code)}/content`,
      { method: "PUT", body: JSON.stringify({ edits }) }
    );
  }

  async deleteTemplate(code: string) {
    return this.request<{ deleted: string }>(
      `/admin/templates/${encodeURIComponent(code)}`,
      { method: "DELETE" }
    );
  }

  /** Ask for a fresh code. The backend rate-limits this; it does not say
   *  whether the address has an account. */
  async resendOtp(email: string) {
    return this.request<{ message: string }>("/auth/resend-otp", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  }

  /** Hand an existing CSP to the automation, so it finishes on its own.
   *  A certificate carries the day it is made, so no date is needed. */
  async autoIssue(cspId: string, certificateDate?: string) {
    return this.request<{
      csp_id: string;
      enrolled: boolean;
      already_enrolled: boolean;
      has_missing_data: boolean;
      missing_fields: string[];
      message: string;
    }>(`/csps/${encodeURIComponent(cspId)}/auto-issue`, {
      method: "POST",
      body: JSON.stringify(
        certificateDate ? { certificate_date: certificateDate } : {}
      ),
    });
  }

  // ---- Agents ----

  async listAgents() {
    return this.request<{ agents: AgentInfo[] }>("/admin/agents");
  }

  async agentFindings() {
    return this.request<{ findings: AgentFinding[]; awaiting_decision: number }>(
      "/admin/agents/findings"
    );
  }

  /** Every run this agent has had, newest first. */
  async agentRuns(key: string) {
    return this.request<{ agent: string; runs: AgentRun[] }>(
      `/admin/agents/${encodeURIComponent(key)}/runs`
    );
  }

  async runAgent(key: string) {
    return this.request<{ agent: string; status: string; summary: string }>(
      `/admin/agents/${encodeURIComponent(key)}/run`,
      { method: "POST" }
    );
  }

  async toggleAgent(key: string, enabled: boolean) {
    return this.request<{ agent: string; enabled: boolean }>(
      `/admin/agents/${encodeURIComponent(key)}`,
      { method: "PATCH", body: JSON.stringify({ enabled }) }
    );
  }

  async acceptFinding(id: string) {
    return this.request<{ id: string; status: string; note?: string }>(
      `/admin/agents/findings/${encodeURIComponent(id)}/accept`,
      { method: "POST", body: JSON.stringify({}) }
    );
  }

  async rejectFinding(id: string) {
    return this.request<{ id: string; status: string }>(
      `/admin/agents/findings/${encodeURIComponent(id)}/reject`,
      { method: "POST", body: JSON.stringify({}) }
    );
  }

  // ---- WhatsApp messages (No. 110) ----

  async whatsappMessages(params: {
    kind?: string;
    stage?: string;
    responded?: boolean;
    days?: number;
    include_tests?: boolean;
    q?: string;
  }) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    }
    return this.request<WhatsAppReport>(`/admin/whatsapp-messages?${qs}`);
  }

  async whatsappMessage(id: string) {
    return this.request<WhatsAppMessageDetail>(
      `/admin/whatsapp-messages/${encodeURIComponent(id)}`);
  }

  async whatsappChat(id: string) {
    return this.request<WhatsAppChat>(
      `/admin/whatsapp-messages/${encodeURIComponent(id)}/conversation`);
  }

  async refreshWhatsappMessages() {
    return this.request<WhatsAppRefreshResult>(
      "/admin/whatsapp-messages/refresh", { method: "POST" });
  }

  // ---- Messaging ----

  async messagingOverview() {
    return this.request<MessagingOverview>("/admin/messaging");
  }

  async sendCandidates() {
    return this.request<{ candidates: SendCandidate[]; total: number }>(
      "/admin/messaging/candidates"
    );
  }

  async addChannel(body: {
    name: string; kind: string; provider: string;
    config: Record<string, unknown>; secret_ref?: string | null;
    is_default: boolean; active: boolean;
  }) {
    return this.request<{ id: string; name: string }>(
      "/admin/messaging/channels",
      { method: "POST", body: JSON.stringify(body) }
    );
  }

  /** Named updateMessageTemplate: updateTemplate above belongs to the
   *  document templates, which are a different thing entirely. */
  async updateMessageTemplate(id: string, body: MessageTemplateInfo) {
    return this.request<{ id: string; name: string }>(
      `/admin/messaging/templates/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          name: body.name, purpose: body.purpose,
          channel_kind: body.channel_kind, subject: body.subject,
          body: body.body, languages: body.languages, active: body.active,
        }),
      }
    );
  }

  /** Reaches real people and cannot be taken back. Recipients are named. */
  async sendDataRequests(cspIds: string[], name?: string) {
    return this.request<SendResult>("/admin/messaging/send", {
      method: "POST",
      body: JSON.stringify({ csp_ids: cspIds, name }),
    });
  }

  // ---- Dashboards ----

  async listDashboards(includeHidden = false) {
    return this.request<{ dashboards: DashboardSummary[] }>(
      `/admin/dashboards${includeHidden ? "?include_hidden=true" : ""}`
    );
  }

  /** Named readDashboard, not getDashboard: the older getDashboard() above
   *  returns the legacy admin metrics and is still in use. */
  async readDashboard(slug: string) {
    return this.request<DashboardDetail>(
      `/admin/dashboards/${encodeURIComponent(slug)}`
    );
  }

  async dashboardMetrics() {
    return this.request<{ groups: MetricGroup[]; widget_kinds: string[] }>(
      "/admin/dashboards/metrics"
    );
  }

  /** The records behind one number on a dashboard.
   *
   *  `field` names the clicked row for a metric that is a table rather
   *  than a single number — which document, for "Documents CSPs hold". */
  async metricRecords(metric: string, field?: string) {
    const query = field ? `?field=${encodeURIComponent(field)}` : "";
    return this.request<MetricRecords>(
      `/admin/dashboards/metrics/${encodeURIComponent(metric)}/records${query}`
    );
  }

  // ---- Sheets (Super Admin) ----

  /** Every registered sheet, with the tabs each spreadsheet has right now. */
  async listSheets() {
    return this.request<{ sheets: SheetSource[] }>("/admin/sheets");
  }

  async readSheetTab(sourceId: string, tab: string) {
    return this.request<SheetTabData>(
      `/admin/sheets/${sourceId}/tabs/${encodeURIComponent(tab)}`
    );
  }

  async updateSheetRow(
    sourceId: string,
    tab: string,
    rowNumber: number,
    cells: Record<string, string>
  ) {
    return this.request<{
      row_number: number;
      written: Record<string, string>;
      unknown_columns: string[];
    }>(
      `/admin/sheets/${sourceId}/tabs/${encodeURIComponent(
        tab
      )}/rows/${rowNumber}`,
      { method: "PATCH", body: JSON.stringify({ cells }) }
    );
  }

  async addSheetRow(
    sourceId: string,
    tab: string,
    cells: Record<string, string>
  ) {
    return this.request<{ row_number: number; unknown_columns: string[] }>(
      `/admin/sheets/${sourceId}/tabs/${encodeURIComponent(tab)}/rows`,
      { method: "POST", body: JSON.stringify({ cells }) }
    );
  }

  /** Irreversible. The response carries what was on the row. */
  async deleteSheetRow(sourceId: string, tab: string, rowNumber: number) {
    return this.request<{
      deleted: Record<string, string>;
      row_number: number;
      note: string;
    }>(
      `/admin/sheets/${sourceId}/tabs/${encodeURIComponent(
        tab
      )}/rows/${rowNumber}`,
      { method: "DELETE" }
    );
  }

  /** Every recorded sign-in for one person. Super Admin only. */
  async loginHistory(email: string) {
    return this.request<{ email: string; logins: LoginEntry[]; note: string }>(
      `/admin/access/logins?email=${encodeURIComponent(email)}`
    );
  }

  async registerSheet(body: {
    name: string;
    spreadsheet_id: string;
    tab: string;
    purpose?: string;
  }) {
    return this.request<SheetSource>("/admin/sheets", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async unregisterSheet(sourceId: string) {
    return this.request<{ removed: string; note: string }>(
      `/admin/sheets/${sourceId}`,
      { method: "DELETE" }
    );
  }

  async addSheetTab(sourceId: string, title: string, columns?: string[]) {
    return this.request<{ tab_id: number; title: string }>(
      `/admin/sheets/${sourceId}/tabs`,
      { method: "POST", body: JSON.stringify({ title, columns }) }
    );
  }

  async createDashboard(body: {
    name: string;
    description?: string;
    icon?: string;
    widgets: WidgetSpec[];
  }) {
    return this.request<DashboardSummary>("/admin/dashboards", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async updateDashboard(
    slug: string,
    body: {
      name?: string;
      description?: string;
      icon?: string;
      active?: boolean;
      widgets?: WidgetSpec[];
    }
  ) {
    return this.request<DashboardSummary>(
      `/admin/dashboards/${encodeURIComponent(slug)}`,
      { method: "PATCH", body: JSON.stringify(body) }
    );
  }

  async deleteDashboard(slug: string) {
    return this.request<{ deleted: string; message: string }>(
      `/admin/dashboards/${encodeURIComponent(slug)}`,
      { method: "DELETE" }
    );
  }

  // ---- Access (Super Admin) ----

  async listAccess() {
    return this.request<AccessListing>("/admin/access");
  }

  async grantAccess(body: {
    email: string;
    name: string;
    mobile: string;
    role: "rm" | "admin" | "super_admin";
  }) {
    return this.request<{
      email: string;
      role: string;
      active: boolean;
      action: string;
      note?: string;
      sheet?: string;
      sheet_note?: string;
    }>("/admin/access/grant", { method: "POST", body: JSON.stringify(body) });
  }

  async revokeAccess(body: { email: string; role: "rm" | "admin" }) {
    return this.request<{ email: string; active: boolean; action: string }>(
      "/admin/access/revoke",
      { method: "POST", body: JSON.stringify(body) }
    );
  }

  async syncAccess() {
    return this.request<{ queued: boolean; task_id: string }>(
      "/admin/access/sync",
      { method: "POST" }
    );
  }

  // ---- Health ----
  async healthCheck() {
    return this.request<{ status: string; service: string; version: string }>(
      "/health"
    );
  }
}

export const api = new ApiClient();
export type { ApiError };
