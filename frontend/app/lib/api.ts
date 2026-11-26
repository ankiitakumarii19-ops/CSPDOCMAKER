/**
 * CSP DocMaker — API Client
 *
 * Centralized HTTP client for all backend API calls.
 * Handles authentication tokens, error responses, and type safety.
 */

import { BASE_PATH, withBase } from "./basePath";
import type { Appearance, AppearanceView } from "./myLook";

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
  /** Risk class (No. 173): low / medium / high / critical, and why. */
  risk?: "low" | "medium" | "high" | "critical";
  risk_why?: string;
  implemented: boolean;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_summary: string | null;
  consecutive_failures: number;
}

/** Agent health (No. 252): one agent's numbers, score and colour. */
export interface AgentHealthAgent {
  key: string;
  name: string;
  owns: string;
  every_minutes: number | null;
  risk: string;
  enabled: boolean;
  score: number | null;
  status: "green" | "amber" | "red" | "grey" | "off";
  open_issues: number;
  run: {
    runs: number;
    ok: number;
    failed: number;
    skipped: number;
    success_rate: number | null;
    expected_runs: number | null;
    on_schedule: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    findings: number;
    critical: number;
    warnings: number;
    findings_per_run: number | null;
    quieted: number;
    last_question_at?: string | null;
  };
  result: { label: string; good: number; total: number; rate: number | null; note: string; basis: string };
  decisions: {
    accepted: number;
    rejected: number;
    acceptance_rate: number | null;
    waiting: number;
    oldest_waiting_hours: number | null;
  };
  last_run_at: string | null;
  minutes_since_last_run: number | null;
  consecutive_failures: number;
  baseline_p95_ms: number | null;
  trend: { day: string; score: number | null }[];
}

export interface AgentIssue {
  id: string;
  agent: string;
  agent_name: string;
  check: string;
  severity: "warning" | "critical";
  status: "open" | "resolved";
  title: string;
  detail: string;
  value: number | null;
  limit: number | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  resolved_at: string | null;
}

export interface AgentImprovement {
  id: string;
  agent: string;
  agent_name: string;
  kind: string;
  title: string;
  evidence: string;
  change: Record<string, unknown>;
  status: "applied" | "proposed" | "dismissed" | "undone" | "closed";
  automatic: boolean;
  created_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  note: string | null;
  can_undo: boolean;
}

export interface AgentHealth {
  now: string;
  checked_at: string | null;
  overall: number | null;
  agents: AgentHealthAgent[];
  issues: AgentIssue[];
  improvements: { waiting: AgentImprovement[]; history: AgentImprovement[]; in_force: number };
  unanswered: { question: string; times_asked: number }[];
  bars: { success: number; result: number; chat: number; acceptance: number; agent_failures: number };
  auto_improve: boolean;
}

export interface AgentHealthDay {
  agent: string;
  day: string;
  score: number | null;
  success_rate?: number | null;
  on_schedule?: number | null;
  p95_ms?: number | null;
  runs?: number | null;
  failed?: number | null;
  result_rate?: number | null;
  acceptance_rate?: number | null;
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
  /** No. 194: who sent it — email of the person, or null = the app. */
  sent_by: string | null;
  /** "automatic", "person" (by hand, not recorded) or the sender's email. */
  sender_key: string;
  /** "Automatic", "You", or the person's name. */
  sender_label: string;
  sender_role: string;
}

/** Who sent the messages, with how many each (No. 194). */
export interface WhatsAppSender {
  key: string;
  label: string;
  role: string;
  me: boolean;
  count: number;
}

/** Contact fixes (bounced emails / unreachable WhatsApp) in one line (No. 158). */
export interface ContactStatus {
  found: number;
  in_progress: number;
  fixed: number;
  stopped: number;
  waiting: { note: string; count: number }[];
}

/** How many messages were sent for each reason other than the usual flow. */
export interface SentBecause {
  key: string;
  label: string;
  count: number;
}

export interface WhatsAppReport {
  summary: Record<"data_request" | "missing_data" | "documents_ready" | "feedback", WhatsAppCounts>;
  /** No. 160: how CSPs answered the feedback question. */
  feedback_answers: { answers: { "1": number; "2": number; "3": number }; no_answer: number };
  /** No. 194: Automatic, You, and each person who sent messages. */
  senders: WhatsAppSender[];
  rows: WhatsAppMessageRow[];
  total_rows: number;
  truncated: boolean;
  last_checked_at: string | null;
  status_days: number;
  sent_because: SentBecause[];
  contact_fixes: ContactStatus;
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

/** The header's search, grouped (No. 175). */
export interface GlobalSearchResult {
  query: string;
  csps: Array<{
    csp_id: string; name: string; district: string; state: string;
    mobile: string; rm_name: string; can_act: boolean;
  }>;
  documents: Array<{
    id: string; csp_id: string; name: string; label: string; version: number;
    created_at: string | null;
  }>;
  chats: Array<{ csp_id: string; name: string; snippet: string; at: string | null }>;
  action_items: ActionItem[];
}

/** An Action Required card, in a list or in History (No. 174). */
export interface ActionItem {
  id: string;
  csp_id: string;
  name: string;
  missing: string[];
  status: "pending" | "fixed";
  flagged_at: string | null;
  fixed_at: string | null;
  fixed_via: string | null;
  fixed_via_label: string;
  fixed_note: string | null;
}

/** A way to message a CSP, and whether it can send now (No. 174). */
export interface SendChannel {
  kind: "whatsapp" | "email" | "sms" | "in_app";
  label: string;
  can_send: boolean;
  why_not: string;
}

/** One card opened: everything needed to act (No. 174). */
export interface ActionDetail extends ActionItem {
  rm_name: string;
  mobile: string;
  email: string;
  on_hold: string;
  existing: boolean;
  asked: Array<{
    at: string | null; channel: string; to: string; status: string;
    fields: string[]; answered_at: string | null; expires_at: string | null;
    error: string;
  }>;
  whatsapp: Array<{
    at: string | null; what: string; stage: string; why: string;
    sent_by: string | null; error: string;
  }>;
  emails: Array<{
    at: string | null; kind: string; subject: string; status: string;
    to: string; opened_at: string | null; bounced: boolean;
  }>;
  replies: Array<{
    messages: { at: string; text: string; type: string }[];
    status: string; answer: string; sent_at: string | null; by: string | null;
  }>;
  sent_by_people: Array<{
    at: string | null; by: string | null; channel: string | null;
    kind: string | null; text: string | null; sent: boolean; reason: string | null;
  }>;
  channels: SendChannel[];
}

/** One verification / details link sent to a CSP (No. 192). */
export interface VerificationLink {
  sent_at: string | null;
  valid_until: string | null;
  answered_at: string | null;
  via: string;
  to: string;
  error: string;
  /** waiting | filled | ran out | replaced | not delivered */
  state: string;
}

/** RM portal → Messages: one CSP and every link sent to them (No. 192). */
export interface VerificationLinks {
  csp_id: string;
  name: string;
  mobile: string;
  email: string;
  on_hold: string;
  existing: boolean;
  valid_days: number;
  channels: SendChannel[];
  /** Why the link cannot be sent to this CSP, or "". */
  refusal: string;
  links: VerificationLink[];
}

/** What one send to one CSP did (No. 174). */
export interface CspSendResult {
  csp_id: string;
  sent: boolean;
  reason: string;
  channel: string;
  kind: string;
  text: string;
}

/** One CSP's whole WhatsApp chat (No. 171). */
export interface CspChat {
  csp_id: string;
  csp_name: string;
  phones: string[];
  items: WhatsAppChat["items"];
  error: string | null;
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
  /** What a person can send through now, and why not (No. 174). */
  send_channels?: SendChannel[];
}

export interface SendCandidate {
  csp_id: string;
  name: string;
  missing: string[];
  email: string;
  mobile: string;
  already_asked: boolean;
  /** When they were last asked (No. 174). */
  asked_at?: string | null;
  reachable: boolean;
  /** Why nothing may be sent to them now; "" = not on hold. */
  on_hold?: string;
  /** In CSPDATA before the import: never the details form. */
  existing?: boolean;
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

/** No. 240 (Stage 5): one person's own arrangement of a dashboard. */
export interface DashboardLayout {
  order: string[];
  hidden: string[];
  columns?: number;
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
  /** The account's address (needed after Log in with Google, No. 171). */
  email?: string;
  /** Signed in: the sign-in is now in a protected cookie (No. 173). */
  signed_in?: boolean;
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
  /** No. 240 (Stage 5): optional group name. */
  category?: string | null;
  /** No. 240: every mapped field must have a value or the document is not made. */
  required_fields?: string[];
}

/** No. 240 (Stage 5): an earlier version of a template. */
export interface TemplateVersion {
  id: string;
  version: number;
  name: string;
  filename: string | null;
  file_size: number;
  was_active: boolean;
  reason: "new_upload" | "wording_edit" | "restore";
  saved_by: string | null;
  saved_at: string | null;
  mapped: number;
}

export interface TemplatePlaceholder {
  text: string;
  field: string;
  guessed: boolean;
  /** No. 212 (ZU-05): what it probably means, for the admin to accept. */
  suggestion?: { field: string; how: string } | null;
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

/** One column of a CSP's sheet row, in the edit form (No. 175). */
export interface CspEditColumn {
  column: string;
  field: string | null;
  value: string;
  kind: "phone" | "email" | "text";
  required: boolean;
  locked: boolean;
}

/** One change to a CSP, in its edit history (No. 175). */
export interface CspEdit {
  at: string | null;
  by: string | null;
  via: string | null;
  column: string | null;
  field: string | null;
  old: string | null;
  new: string | null;
}

export interface DatabaseRecord {
  csp_id: string;
  name: string | null;
  level: string;
  /** This person may edit it (No. 175: RMs their own CSPs). */
  can_edit?: boolean;
  edit_history?: CspEdit[];
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
  /** May this person act on it (No. 175: an RM only on their own). */
  can_act?: boolean | null;
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
  contact_fixes: ContactStatus;
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
  /** Its words were changed on the page (No. 171). */
  edited?: boolean;
}

/** One difference the verification agent settled by itself (No. 171). */
export interface VerificationDecision {
  at: string | null;
  csp_id: string | null;
  field: string | null;
  label: string | null;
  decision: "kept_sheet" | "wrote_answer" | null;
  csp_answered: string | null;
  old_value: string | null;
  new_value: string | null;
  why: string | null;
  result: string;
  error?: string | null;
}

/** The words on Data quality, editable (No. 171). */
export interface ContextText {
  key: string;
  label: string;
  used_for: string;
  edited?: boolean;
}

export interface Guardrail {
  title: string;
  detail: string;
}

export type TextSection = "context" | "harness" | "guardrails";

/** What an uploaded file says for each section — for review, not saved. */
export interface ExtractedTexts {
  file: string;
  context: ContextText[];
  harness: Pick<HarnessCheck, "key" | "name" | "watches" | "how">[];
  guardrails: Guardrail[];
  knowledge: { question: string; answer: string; category: string }[];
  unplaced: string[];
  headings_found: boolean;
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

// ---- Settings centre (No. 204, Stage 1) ----

export type SettingValue = number | boolean | string;

export interface WorkspaceSettingItem {
  key: string;
  group: string;
  label: string;
  help: string;
  /** What changing it does — shown before saving. */
  effect: string;
  kind: "int" | "bool" | "text" | "choice" | "list";
  unit: string;
  min: number | null;
  max: number | null;
  choices: string[];
  value: SettingValue;
  value_text: string;
  /** The server's value: Eko's value, every workspace's starting point. */
  standard: SettingValue;
  standard_text: string;
  changed: boolean;
  own: boolean;
  changed_by: string | null;
  changed_at: string | null;
  can_change: boolean;
  unchanged?: boolean;
}

export interface SettingsGroup {
  key: string;
  title: string;
  about: string;
  admins_may_change: boolean;
}

export interface WorkspaceSettingsView {
  workspace: { id: string; name: string } | null;
  groups: SettingsGroup[];
  settings: WorkspaceSettingItem[];
  is_owner: boolean;
  note: string;
}

export interface SettingsSheetChange {
  key: string;
  label: string;
  now: string;
  new: string;
  problem: string | null;
}

export interface SettingChange {
  id: number;
  key: string;
  label: string;
  before: string;
  after: string;
  by: string;
  via: string;
  note: string | null;
  at: string | null;
  can_undo: boolean;
}

// ---- Setup guide (No. 215, Stage 8) ----

export interface SetupGuideStep {
  key: string;
  title: string;
  status: string;
  label: string;
  detail: string;
  how: string;
  where: string | null;
  essential: boolean;
}

export interface SetupGuideView {
  steps: SetupGuideStep[];
  live: boolean;
  test_mode: boolean;
  test_mode_phone: string;
  test_mode_email: string;
  pause_all: boolean;
  ready_to_go_live: boolean;
}

export interface DryRun {
  records: {
    code: string;
    name: string | null;
    type: string;
    documents: string[];
    missing: string[];
    on_hold: string;
    would_happen: string;
  }[];
  sent: number;
  note: string;
}

// ---- Columns (No. 211, Stage 4) ----

export interface ColumnsView {
  fields: { field: string; eko_header: string; label: string; header: string; own: boolean }[];
  own: Record<string, string>;
}

export interface ColumnsGuess {
  headers: string[];
  guess: Record<string, { header: string; score: number; how: string }>;
  not_found: string[];
}

// ---- Connections (No. 210, Stage 3) ----

export interface ConnectionItem {
  key: string;
  group: string;
  label: string;
  help: string;
  kind: "text" | "int" | "bool" | "secret" | "choice";
  choices: string[];
  /** Never sent for a secret. */
  value: string | number | boolean | null;
  secret_set?: boolean;
  own: boolean;
  from_server: boolean;
  changed_by: string | null;
  changed_at: string | null;
}

export interface ConnectionsView {
  workspace: { id: string; name: string; eko: boolean };
  groups: { key: string; title: string; about: string }[];
  connections: ConnectionItem[];
  robot_email: string;
  connected: Record<string, boolean>;
  note: string;
}

// ---- Feature access (No. 206, Stage 2) ----

export interface MyAccess {
  role: string;
  own_role: string | null;
  role_name: string;
  /** Feature keys this person may use. */
  features: string[];
  record_scope: "own" | "all";
  /** No. 214: the workspace's own app name and main colour. */
  look: {
    name: string;
    color: string;
    theme?: string;
    style?: string;
    /** No. 240 (Stage 3): second colour ("" = none). */
    color_2?: string;
    /** No. 240: may people pick their own colours and font. */
    own_colours?: boolean;
    /** No. 240: the organisation's logo version, or null = the app's own. */
    logo?: string | null;
    /** No. 240: the organisation's name. */
    org_name?: string;
    /** No. 247: whose name CSP messages carry, in full and short. */
    sender_org?: string;
    sender_short?: string;
  };
  /** May open the Admin pages (always for Admins; for an RM given an Admin screen). */
  admin_area: boolean;
}

/** No. 240 (Stage 6): the Supreme Owner's console. Counts and health only. */
export interface PlatformUsage {
  documents: number;
  documents_this_month: number;
  storage_bytes: number;
  people: number;
  records: number;
}

export interface PlatformPlan {
  key: string;
  name: string;
  description: string | null;
  price_monthly_paise: number | null;
  currency: string;
  max_documents_month: number | null;
  max_storage_mb: number | null;
  max_users: number | null;
  trial_days: number | null;
  active: boolean;
}

export interface PlatformWorkspace {
  id: string;
  name: string;
  slug: string;
  active: boolean;
  is_eko: boolean;
  owner_email: string;
  created_at: string | null;
  usage: Partial<PlatformUsage>;
  health: {
    last_sheet_read?: string;
    whatsapp_failed_24h?: number;
    whatsapp_24h?: number;
    email_failed_24h?: number;
    failed_generations?: number;
  };
  subscription: null | {
    plan_key: string;
    plan_name: string;
    status: string;
    trial_ends_at: string | null;
    current_period_end: string | null;
    payment_provider: string;
    white_label: boolean;
    custom_domain: string | null;
    notes: string | null;
    limits: null | { max_documents_month: number | null; max_storage_mb: number | null; max_users: number | null };
  };
}

export interface PlatformOverview {
  workspaces: number;
  active_workspaces: number;
  inactive_workspaces: number;
  people: number;
  documents: number;
  documents_this_month: number;
  failed_generations: number;
  storage_bytes: number;
  whatsapp_failed_24h: number;
  email_failed_24h: number;
  health: Record<string, string>;
}

export interface PlatformAnnouncement {
  id: string;
  message: string;
  level: "info" | "warning";
  workspace_id: string | null;
  starts_at: string | null;
  ends_at: string | null;
  active: boolean;
  created_by: string | null;
  created_at: string | null;
}

/** No. 240 (Stage 3): one staff notification and its channels, for this person. */
export interface NotificationKind {
  key: string;
  label: string;
  about: string;
  mandatory: boolean;
  why_mandatory: string;
  who: string;
  channels: {
    key: string;
    name: string;
    available: boolean;
    on?: boolean;
    locked?: boolean;
    why?: string;
  }[];
}

export interface AccessFeature {
  key: string;
  group: string;
  title: string;
  about: string;
  default: string[];
  can_give_to: string[];
  locked: boolean;
  all_csps: boolean;
  owner: boolean;
}

export interface AccessRoleItem {
  key: string;
  name: string;
  base_role: "rm" | "admin";
  record_scope: "own" | "all";
  built_in: boolean;
  members: number;
}

export interface AccessCell {
  allowed: boolean;
  /** Changed from today's access on this page. */
  set: boolean;
  can_change: boolean;
}

export interface FeatureAccessPerson {
  email: string;
  name: string | null;
  role: "rm" | "admin";
  own_role: string | null;
  overrides: Record<string, boolean>;
  features: string[];
}

export interface FeatureAccessView {
  groups: { key: string; title: string }[];
  features: AccessFeature[];
  roles: AccessRoleItem[];
  grid: Record<string, Record<string, AccessCell>>;
  people: FeatureAccessPerson[];
  note: string;
}

export interface AccessChange {
  id: number;
  what: string;
  before: string;
  after: string;
  by: string;
  via: string;
  at: string | null;
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
  // The sign-in itself is a protected cookie the server sets (No. 173):
  // HttpOnly, so no script on the page can read it, and every request
  // carries it by itself. Only the person's name, email and role are kept
  // in localStorage ("user"), for the screens. A sign-in from before this
  // ("access_token" in localStorage) is no longer sent: the first request
  // answers 401 and the person signs in once more.
  getToken(): string | null {
    return null;
  }

  /** Someone is signed in, as far as this browser knows. */
  private signedIn(): boolean {
    if (typeof window === "undefined") return false;
    try {
      return localStorage.getItem("user") !== null;
    } catch {
      return false;
    }
  }

  clearToken() {
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
    // Every request says it is the app's own (the server refuses a change
    // signed in by the cookie without it — another site cannot add it) and
    // asks for the sign-in as a cookie (No. 173).
    const headers = new Headers(init.headers);
    headers.set("X-Requested-With", "CSPDocMaker");
    headers.set("X-Session-Cookie", "1");
    try {
      return await fetch(url, { ...init, headers, credentials: "same-origin" });
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
    if (response.status === 401 && !path.startsWith("/auth/") && this.signedIn()) {
      this.clearToken();
      if (typeof window !== "undefined") {
        // A full page load on purpose: it drops every screen's in-memory
        // state from the expired session (there is no router in this file).
        // Where they were, so signing in again brings them back (No. 171).
        const here = window.location.pathname.slice(BASE_PATH.length) + window.location.search;
        window.location.assign(
          withBase(`/auth/login?expired=1&next=${encodeURIComponent(here)}`)
        );
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
      /** Blank = no "Log in with Google" button (No. 171). */
      google_client_id?: string;
      /** A test copy of the app: every screen says so (No. 173). */
      test_copy?: boolean;
    }>("/auth/config");
  }

  /** Log in with Google (No. 171): the ID token from Google's button. */
  async googleSignIn(credential: string) {
    return this.request<SignInResult>("/auth/google", {
      method: "POST",
      body: JSON.stringify({ credential }),
    });
  }

  async signup(data: {
    email: string;
    name: string;
    password: string;
    requested_role: string;
    /** Only when signing up as a Super Admin of a new workspace. */
    workspace_name?: string;
    /** No. 215 (ZU-08): start like Eko, or blank. */
    starter?: "eko" | "blank";
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
      // No. 240: nothing of this person's own look stays on the page.
      if (typeof document !== "undefined") {
        document.getElementById("my-look")?.remove();
        document.getElementById("my-look-font")?.remove();
      }
    }
  }

  // ---- Your own look (No. 240) — always and only your own ----
  async myAppearance() {
    return this.request<AppearanceView>("/profile/appearance");
  }

  async saveAppearance(appearance: Appearance) {
    return this.request<AppearanceView>("/profile/appearance", {
      method: "PUT",
      body: JSON.stringify({ appearance }),
    });
  }

  /** Change some choices; null = as the workspace has it. */
  async changeAppearance(appearance: Record<string, unknown>) {
    return this.request<AppearanceView>("/profile/appearance", {
      method: "PATCH",
      body: JSON.stringify({ appearance }),
    });
  }

  // ---- Your own dashboard arrangement (No. 240, Stage 5) ----
  async myDashboardLayout(slug: string) {
    return this.request<{ layout: DashboardLayout | null }>(`/profile/dashboards/${encodeURIComponent(slug)}`);
  }

  async saveDashboardLayout(slug: string, layout: DashboardLayout) {
    return this.request<{ layout: DashboardLayout }>(`/profile/dashboards/${encodeURIComponent(slug)}`, {
      method: "PUT",
      body: JSON.stringify(layout),
    });
  }

  async resetDashboardLayout(slug: string) {
    return this.request<{ layout: null }>(`/profile/dashboards/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    });
  }

  async resetAppearance() {
    return this.request<AppearanceView>("/profile/appearance", { method: "DELETE" });
  }

  // ---- The Supreme Owner's console (No. 240, Stage 6) ----
  async mePlatform() {
    return this.request<{ supreme_owner: boolean }>("/me/platform");
  }

  async myAnnouncements() {
    return this.request<{ announcements: { id: string; message: string; level: "info" | "warning" }[] }>(
      "/me/announcements"
    );
  }

  async platformOverview() {
    return this.request<PlatformOverview>("/platform/overview");
  }

  async platformWorkspaces() {
    return this.request<{ workspaces: PlatformWorkspace[] }>("/platform/workspaces");
  }

  async platformSuspend(id: string, on: boolean) {
    return this.request<{ id: string; active: boolean }>(
      `/platform/workspaces/${encodeURIComponent(id)}/${on ? "reactivate" : "suspend"}`,
      { method: "POST" }
    );
  }

  async platformSetSubscription(
    id: string,
    body: { plan_key: string; status: string; trial_ends_at?: string | null; white_label?: boolean; custom_domain?: string | null; notes?: string | null }
  ) {
    return this.request<{ workspaces: PlatformWorkspace[] }>(
      `/platform/workspaces/${encodeURIComponent(id)}/subscription`,
      { method: "PUT", body: JSON.stringify(body) }
    );
  }

  async platformPlans() {
    return this.request<{ plans: PlatformPlan[]; payment_gateway: string }>("/platform/plans");
  }

  async platformSavePlan(plan: Partial<PlatformPlan> & { name: string }, existingKey?: string) {
    return this.request<PlatformPlan>(
      existingKey ? `/platform/plans/${encodeURIComponent(existingKey)}` : "/platform/plans",
      { method: existingKey ? "PUT" : "POST", body: JSON.stringify(plan) }
    );
  }

  async platformAnnouncements() {
    return this.request<{ announcements: PlatformAnnouncement[] }>("/platform/announcements");
  }

  async platformAnnounce(body: { message: string; level: string; workspace_id?: string | null }) {
    return this.request<PlatformAnnouncement>("/platform/announcements", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  async platformEndAnnouncement(id: string) {
    return this.request<PlatformAnnouncement>(`/platform/announcements/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  // ---- Your notifications (No. 240, Stage 3) ----
  async myNotifications() {
    return this.request<{ notifications: NotificationKind[] }>("/profile/notifications");
  }

  async saveNotifications(notifications: Record<string, Record<string, boolean>>) {
    return this.request<{ notifications: NotificationKind[] }>("/profile/notifications", {
      method: "PUT",
      body: JSON.stringify({ notifications }),
    });
  }

  // ---- The organisation's logo (No. 240, Stage 3; Super Admin) ----
  async uploadLogo(file: File) {
    const body = new FormData();
    body.append("file", file);
    const path = "/admin/branding/logo";
    const response = await this.send(`${API_BASE}${path}`, { method: "PUT", body });
    if (!response.ok) throw await this.failure(response, path, "Could not upload the logo");
    return response.json() as Promise<{ logo: string; bytes: number }>;
  }

  async removeLogo() {
    return this.request<{ logo: null; removed: boolean }>("/admin/branding/logo", {
      method: "DELETE",
    });
  }

  // ---- CSP ----
  /** Part of a code, name, phone, email, district, state or RM (No. 175). */
  async searchCSP(query: string, limit = 20) {
    return this.request<{
      results: CSPDetail[];
      total: number;
      query: string;
    }>(`/csps/search?q=${encodeURIComponent(query)}&limit=${limit}`);
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

  /** The header's search across the app (No. 175), grouped. */
  async globalSearch(q: string, limit = 6) {
    return this.request<GlobalSearchResult>(
      `/search?q=${encodeURIComponent(q)}&limit=${limit}`
    );
  }

  // ---- Action Required (No. 174) ----
  async alertHistory(show: "all" | "fixed" | "pending" = "all", q = "") {
    return this.request<{ items: ActionItem[]; total: number }>(
      `/alerts/history?show=${show}&q=${encodeURIComponent(q)}`
    );
  }

  async alertDetail(id: string) {
    return this.request<ActionDetail>(`/alerts/${encodeURIComponent(id)}`);
  }

  // ---- RM dashboard: CSPs still waiting for documents (No. 234) ----
  /** Every CSP not yet sent all its documents, times contacted, counts,
   *  a per-RM / DC / state / district table and each filter's values. */
  async documentsLeft(params: DocumentsLeftParams) {
    return this.request<DocumentsLeft>(`/rm-dashboard/pending?${documentsLeftQuery(params)}`);
  }

  /** The same list, every row, as a CSV file. */
  async documentsLeftCsv(params: DocumentsLeftParams): Promise<Blob> {
    const path = `/rm-dashboard/pending.csv?${documentsLeftQuery(params)}`;
    const token = this.getToken();
    const response = await this.send(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      throw await this.failure(response, path, "Could not download the list");
    }
    return response.blob();
  }

  /** Message one CSP now (No. 234: any RM, any CSP, unless the workspace
   *  keeps RMs to their own). */
  async messageCsp(
    cspId: string,
    body: { kind: "custom" | "details_form"; channel: string; text?: string }
  ) {
    return this.request<CspSendResult>(`/csps/${encodeURIComponent(cspId)}/message`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  /** Every verification link sent to one CSP (RMs: their own CSPs). */
  async cspVerificationLinks(cspId: string) {
    return this.request<VerificationLinks>(
      `/csps/${encodeURIComponent(cspId)}/verification-links`
    );
  }

  /** One CSP's WhatsApp chat — works for RMs (own CSPs) and Admins. */
  async cspConversation(cspId: string) {
    return this.request<CspChat>(`/csps/${encodeURIComponent(cspId)}/conversation`);
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

  /** The CSP's whole sheet row, read now, for the edit form (No. 175). */
  async databaseEditForm(cspId: string) {
    return this.request<{ csp_id: string; level: string; tab: string; row_number: number; columns: CspEditColumn[] }>(
      `/admin/database/${encodeURIComponent(cspId)}/edit`
    );
  }

  /** Write the changed columns; `seen` = what the form showed for them. */
  async databaseSave(cspId: string, body: { changes: Record<string, string>; seen: Record<string, string> }) {
    return this.request<{ saved: string[] }>(`/admin/database/${encodeURIComponent(cspId)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  }

  /** A stored photo or PDF, fetched with the login so it can be shown. */
  /** The CSP's photo as every screen shows it — the passport version — or
   *  null when the app has none yet (No. 102). */
  // ---- Profile pictures (No. 171) ----
  /** A person's picture, or null when they have none (show initials). */
  async profilePhoto(email: string): Promise<Blob | null> {
    const path = `/profile/photo/${encodeURIComponent(email.toLowerCase())}`;
    const token = this.getToken();
    const response = await this.send(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (response.status === 404) return null;
    if (!response.ok) {
      throw await this.failure(response, path, "Could not load the picture");
    }
    return response.blob();
  }

  async setProfilePhoto(file: File) {
    const body = new FormData();
    body.append("file", file);
    const token = this.getToken();
    const path = "/profile/photo";
    const response = await this.send(`${API_BASE}${path}`, {
      method: "PUT",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body,
    });
    if (!response.ok) {
      throw await this.failure(response, path, "The picture could not be saved");
    }
    return (await response.json()) as { email: string; version: string };
  }

  async removeProfilePhoto() {
    return this.request<{ email: string; removed: boolean }>("/profile/photo", {
      method: "DELETE",
    });
  }

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

  /** quote (No. 171): the CSP's message this answers, put in front. */
  async sendCspReply(id: string, text: string, sendLink?: boolean, quote?: string) {
    return this.request<CspReplyRow>(`/admin/csp-replies/${encodeURIComponent(id)}/send`, {
      method: "POST",
      body: JSON.stringify({ text, send_link: sendLink, quote: quote || null }),
    });
  }

  /** No. 161: the data verification link for a reply already sent without it. */
  async linkCspReply(id: string) {
    return this.request<CspReplyRow>(`/admin/csp-replies/${encodeURIComponent(id)}/link`, {
      method: "POST",
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

  async qualityTexts() {
    return this.request<{ context: ContextText[]; guardrails: Guardrail[] }>(
      "/admin/quality/texts"
    );
  }

  async saveQualityTexts(section: TextSection, items: object[]) {
    return this.request<{ saved: TextSection; context: ContextText[]; guardrails: Guardrail[] }>(
      `/admin/quality/texts/${section}`,
      { method: "PUT", body: JSON.stringify({ items }) }
    );
  }

  /** Read a PDF / Word / text file into the sections; nothing is saved. */
  async extractQualityTexts(file: File) {
    const body = new FormData();
    body.append("file", file);
    const token = this.getToken();
    const path = "/admin/quality/texts/extract";
    const response = await this.send(`${API_BASE}${path}`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body,
    });
    if (!response.ok) {
      throw await this.failure(response, path, "The file could not be read");
    }
    return (await response.json()) as ExtractedTexts;
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

  // ---- Settings centre (No. 204; see: Admin + Owner, change: Owner, or
  // Admins in the groups the Owner handed to them) ----
  async workspaceSettings() {
    return this.request<WorkspaceSettingsView>("/admin/settings");
  }

  async changeSetting(key: string, value: SettingValue) {
    return this.request<WorkspaceSettingItem>(`/admin/settings/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    });
  }

  async settingToStandard(key: string) {
    return this.request<WorkspaceSettingItem>(`/admin/settings/${encodeURIComponent(key)}`, {
      method: "DELETE",
    });
  }

  /** ZU-07 (No. 215): every setting as one Excel file. */
  async settingsSheet(): Promise<Blob> {
    const path = "/admin/settings/sheet";
    const token = this.getToken();
    const response = await this.send(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      throw await this.failure(response, path, "Could not download the settings");
    }
    return response.blob();
  }

  /** ZU-07: what an uploaded settings sheet would change (apply=false), or save it. */
  async uploadSettingsSheet(file: File, apply: boolean) {
    const form = new FormData();
    form.append("file", file);
    return this.upload<{ changes: SettingsSheetChange[]; applied: string[] }>(
      `/admin/settings/sheet?apply=${apply ? "true" : "false"}`,
      form
    );
  }

  async settingHistory(key?: string) {
    const qs = key ? `?key=${encodeURIComponent(key)}` : "";
    return this.request<{ changes: SettingChange[] }>(`/admin/settings/history${qs}`);
  }

  async undoSettingChange(id: number) {
    return this.request<WorkspaceSettingItem>(`/admin/settings/history/${id}/undo`, {
      method: "POST",
    });
  }

  async setSettingsAdminGroups(groups: string[]) {
    return this.request<{ admin_groups: string[] }>("/admin/settings/admin-groups", {
      method: "PUT",
      body: JSON.stringify({ groups }),
    });
  }

  // ---- Setup guide (No. 215; the Super Admin's) ----
  async setupGuide() {
    return this.request<SetupGuideView>("/admin/setup-guide");
  }

  async goLive() {
    return this.request<SetupGuideView>("/admin/setup-guide/go-live", { method: "POST" });
  }

  async dryRun() {
    return this.request<DryRun>("/admin/setup-guide/dry-run", { method: "POST" });
  }

  /** No. 216: all this workspace's data as a .zip of CSV files. */
  async exportWorkspace(): Promise<Blob> {
    const path = "/admin/workspace/export";
    const token = this.getToken();
    const response = await this.send(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      throw await this.failure(response, path, "Could not export");
    }
    return response.blob();
  }

  async closeWorkspace(confirm: string) {
    return this.request<{ closed: boolean; note: string }>("/admin/workspace/close", {
      method: "POST",
      body: JSON.stringify({ confirm }),
    });
  }

  // ---- Columns (No. 211; the Super Admin's) ----
  async columns() {
    return this.request<ColumnsView>("/admin/columns");
  }

  async guessColumns() {
    return this.request<ColumnsGuess>("/admin/columns/guess", { method: "POST" });
  }

  async saveColumns(columns: Record<string, string>) {
    return this.request<ColumnsView>("/admin/columns", {
      method: "PUT",
      body: JSON.stringify({ columns }),
    });
  }

  // ---- Connections (No. 210; the Super Admin's) ----
  async connections() {
    return this.request<ConnectionsView>("/admin/connections");
  }

  async setConnection(key: string, value: string) {
    return this.request<ConnectionsView>(`/admin/connections/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    });
  }

  async clearConnection(key: string) {
    return this.request<ConnectionsView>(`/admin/connections/${encodeURIComponent(key)}`, {
      method: "DELETE",
    });
  }

  async testConnection(group: string) {
    return this.request<{ ok: boolean; message: string }>(
      `/admin/connections/test/${encodeURIComponent(group)}`,
      { method: "POST" }
    );
  }

  // ---- Feature access (No. 206; the page is the Super Admin's) ----
  async myAccess() {
    return this.request<MyAccess>("/me/access");
  }

  async featureAccess() {
    return this.request<FeatureAccessView>("/admin/feature-access");
  }

  async setRoleFeature(role: string, feature: string, allowed: boolean | null) {
    return this.request<FeatureAccessView>(
      `/admin/feature-access/roles/${encodeURIComponent(role)}/${encodeURIComponent(feature)}`,
      { method: "PUT", body: JSON.stringify({ allowed }) }
    );
  }

  async setPersonFeature(email: string, feature: string, allowed: boolean | null) {
    return this.request<FeatureAccessView>(
      `/admin/feature-access/people/${encodeURIComponent(email)}/${encodeURIComponent(feature)}`,
      { method: "PUT", body: JSON.stringify({ allowed }) }
    );
  }

  /** No. 240 (Stage 4): Manager, Employee, Reviewer, Viewer (those missing). */
  async addStarterRoles() {
    return this.request<FeatureAccessView & { added: string[] }>("/admin/feature-access/starter-roles", {
      method: "POST",
    });
  }

  async createAccessRole(name: string, copyFrom: string) {
    return this.request<FeatureAccessView & { role: AccessRoleItem }>("/admin/feature-access/roles", {
      method: "POST",
      body: JSON.stringify({ name, copy_from: copyFrom }),
    });
  }

  async changeAccessRole(key: string, change: { name?: string; record_scope?: "own" | "all" }) {
    return this.request<FeatureAccessView>(`/admin/feature-access/roles/${encodeURIComponent(key)}`, {
      method: "PATCH",
      body: JSON.stringify(change),
    });
  }

  async deleteAccessRole(key: string) {
    return this.request<FeatureAccessView>(`/admin/feature-access/roles/${encodeURIComponent(key)}`, {
      method: "DELETE",
    });
  }

  async setMemberAccessRole(email: string, role: string | null) {
    return this.request<FeatureAccessView>(
      `/admin/feature-access/members/${encodeURIComponent(email)}/role`,
      { method: "PUT", body: JSON.stringify({ role }) }
    );
  }

  async featureAccessHistory() {
    return this.request<{ changes: AccessChange[] }>("/admin/feature-access/history");
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

  // ---- Template versions and test (No. 240, Stage 5) ----
  async templateVersions(code: string) {
    return this.request<{ code: string; current_version: number; versions: TemplateVersion[] }>(
      `/admin/templates/${encodeURIComponent(code)}/versions`
    );
  }

  async restoreTemplateVersion(code: string, id: string) {
    return this.request<TemplateSummary & { restored_version: number; unmapped: string[] }>(
      `/admin/templates/${encodeURIComponent(code)}/versions/${encodeURIComponent(id)}/restore`,
      { method: "POST" }
    );
  }

  /** A file the server sends back (a kept version, a test document). */
  private async fileFrom(path: string, init: RequestInit, fallback: string): Promise<{ blob: Blob; name: string }> {
    const response = await this.send(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers as Record<string, string>) },
    });
    if (!response.ok) throw await this.failure(response, path, fallback);
    const disposition = response.headers.get("content-disposition") || "";
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] || "document.docx";
    return { blob: await response.blob(), name };
  }

  async templateVersionFile(code: string, id: string) {
    return this.fileFrom(
      `/admin/templates/${encodeURIComponent(code)}/versions/${encodeURIComponent(id)}/file`,
      {},
      "Could not download that version"
    );
  }

  /** Makes the document for one CSP; nothing is stored or sent. */
  async testTemplate(code: string, cspId: string) {
    return this.fileFrom(
      `/admin/templates/${encodeURIComponent(code)}/test`,
      { method: "POST", body: JSON.stringify({ csp_id: cspId }) },
      "Could not make the test document"
    );
  }

  // ---- Signatures chosen by rule (No. 247) ----
  async signatures() {
    return this.request<SignatureOverview>("/admin/signatures");
  }

  async uploadSignature(name: string, file: File) {
    const body = new FormData();
    body.append("name", name);
    body.append("file", file);
    const path = "/admin/signatures";
    const response = await this.send(`${API_BASE}${path}`, { method: "POST", body });
    if (!response.ok) throw await this.failure(response, path, "Could not upload the signature");
    return response.json() as Promise<SignaturePicture>;
  }

  async renameSignature(id: string, name: string) {
    return this.request<{ ok: boolean }>(`/admin/signatures/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
  }

  async removeSignature(id: string) {
    return this.request<{ ok: boolean }>(`/admin/signatures/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  /** A picture behind sign-in, as a URL an <img> can show. */
  async pictureUrl(path: string) {
    const { blob } = await this.fileFrom(path, {}, "Could not load the picture");
    return URL.createObjectURL(blob);
  }

  signaturePicturePath(id: string) {
    return `/admin/signatures/${encodeURIComponent(id)}/picture`;
  }

  documentPicturePath(code: string, checksum: string) {
    return `/admin/signatures/documents/${encodeURIComponent(code)}/pictures/${encodeURIComponent(checksum)}`;
  }

  async addSignatureRule(rule: SignatureRuleInput) {
    return this.request<{ id: string }>("/admin/signatures/rules", {
      method: "POST",
      body: JSON.stringify(rule),
    });
  }

  async changeSignatureRule(id: string, rule: SignatureRuleInput) {
    return this.request<{ ok: boolean }>(`/admin/signatures/rules/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(rule),
    });
  }

  async removeSignatureRule(id: string) {
    return this.request<{ ok: boolean }>(`/admin/signatures/rules/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }

  async orderSignatureRules(ids: string[]) {
    return this.request<{ ok: boolean }>("/admin/signatures/rules/order", {
      method: "PUT",
      body: JSON.stringify({ ids }),
    });
  }

  async signatureColumnValues(column: string) {
    return this.request<{ column: string; values: { value: string; count: number }[] }>(
      `/admin/signatures/values?column=${encodeURIComponent(column)}`
    );
  }

  async signatureSpot(code: string) {
    return this.request<SignatureSpot>(`/admin/signatures/documents/${encodeURIComponent(code)}`);
  }

  async setSignatureSpot(code: string, spot: string | null) {
    return this.request<{ ok: boolean; spot: string | null }>(
      `/admin/signatures/documents/${encodeURIComponent(code)}/spot`,
      { method: "PUT", body: JSON.stringify({ spot }) }
    );
  }

  async whichSignature(code: string, cspId: string) {
    return this.request<{ signature: string | null; rule_id: string | null; why: string }>(
      `/admin/signatures/which?code=${encodeURIComponent(code)}&csp_id=${encodeURIComponent(cspId)}`
    );
  }

  async updateTemplate(
    code: string,
    settings: {
      name?: string;
      placeholder_map?: Record<string, string>;
      photo_marker?: string;
      active?: boolean;
      category?: string;
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

  /** What the verification agent decided by itself (No. 171). */
  async verificationDecisions(limit = 100) {
    return this.request<{ decisions: VerificationDecision[] }>(
      `/admin/agents/verification/decisions?limit=${limit}`
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

  // ---- Agent health (No. 252) ----

  async agentHealth() {
    return this.request<AgentHealth>("/admin/agents/evaluation");
  }

  async agentHealthHistory(days = 30, agent?: string) {
    const q = `days=${days}${agent ? `&agent=${encodeURIComponent(agent)}` : ""}`;
    return this.request<{ days: number; rows: AgentHealthDay[] }>(
      `/admin/agents/evaluation/history?${q}`
    );
  }

  async agentHealthIssues(status: "open" | "resolved" | "all" = "open") {
    return this.request<{ issues: AgentIssue[] }>(
      `/admin/agents/evaluation/issues?status=${status}`
    );
  }

  async agentHealthCheck() {
    return this.request<{ agents: number; issues: { opened: number; resolved: number; open: number }; improvements: { applied: number; proposed: number; closed: number } }>(
      "/admin/agents/evaluation/check",
      { method: "POST" }
    );
  }

  async agentImprovement(id: string, action: "apply" | "dismiss" | "undo") {
    return this.request<AgentImprovement>(
      `/admin/agents/evaluation/improvements/${encodeURIComponent(id)}/${action}`,
      { method: "POST" }
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

  /** One CSP's whole WhatsApp chat, by their code (No. 171). */
  async cspChat(cspId: string) {
    return this.request<CspChat>(
      `/admin/whatsapp-messages/csp/${encodeURIComponent(cspId)}/conversation`);
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

  /** A saved message (No. 174): purpose "custom". */
  async addMessageTemplate(body: { name: string; body: string; purpose?: string; channel_kind?: string }) {
    return this.request<{ id: string; name: string }>("/admin/messaging/templates", {
      method: "POST",
      body: JSON.stringify({
        name: body.name, purpose: body.purpose ?? "custom",
        channel_kind: body.channel_kind ?? "whatsapp", body: body.body,
        languages: [], active: true,
      }),
    });
  }

  async deleteMessageTemplate(id: string) {
    return this.request<{ deleted: boolean }>(
      `/admin/messaging/templates/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  /** At most 50 CSPs a call — the screen sends a big selection in parts. */
  async sendMessage(body: {
    csp_ids: string[];
    kind: "custom" | "details_form";
    channel: string;
    text?: string;
    template_id?: string | null;
    name?: string;
  }) {
    return this.request<{ asked: number; sent: number; failed: number; results: CspSendResult[] }>(
      "/admin/messaging/send-message", { method: "POST", body: JSON.stringify(body) });
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

// ---- Signatures chosen by rule (No. 247) ----
export interface SignaturePicture {
  id: string;
  name: string;
  width: number;
  height: number;
  checksum: string;
  used_by: number;
  created_by: string | null;
  created_at: string | null;
}

export interface SignatureRule {
  id: string;
  document_code: string | null;
  column: string;
  values: string[];
  signature_id: string;
  signature_name: string;
  position: number;
  active: boolean;
  words: string;
}

export interface SignatureRuleInput {
  document_code: string | null;
  column: string;
  values: string[];
  signature_id: string;
  active: boolean;
}

export interface SignatureOverview {
  signatures: SignaturePicture[];
  rules: SignatureRule[];
  columns: { key: string; label: string }[];
  documents: { code: string; name: string }[];
}

export interface SignatureSpot {
  code: string;
  name: string;
  spot: string | null;
  chosen: boolean;
  found: boolean;
  pictures: { checksum: string; width: number; height: number; count: number }[];
  paragraphs: { text: string }[];
}

export const api = new ApiClient();
export type { ApiError };


// ---- RM dashboard: CSPs still waiting for documents (No. 234) ----

export interface DocumentsLeftParams {
  rm?: string;
  dc?: string;
  state?: string;
  district?: string;
  /** "" | "never" | "1-2" | "3+" */
  contacted?: string;
  /** "" (all) | "hide" (not on hold) | "only" (on hold only) */
  hold?: string;
  q?: string;
  /** "contacts" | "-contacts" | "last_contacted" | "name" */
  sort?: string;
  /** "rm" | "dc" | "state" | "district" */
  group_by?: string;
  page?: number;
  page_size?: number;
}

export interface DocumentsLeftRow {
  csp_id: string;
  csp_code: string | null;
  name: string;
  mobile: string | null;
  rm: string;
  dc: string;
  state: string;
  district: string;
  origin: string;
  on_hold: string;
  documents_left: string[];
  documents_sent: number;
  documents_due: number;
  whatsapp: number;
  email: number;
  contacts: number;
  last_contacted: string | null;
}

export interface DocumentsLeft {
  summary: {
    left: number;
    never: number;
    once_or_twice: number;
    three_plus: number;
    on_hold: number;
    contacts: number;
  };
  all_left: number;
  old_not_listed: number;
  groups: { name: string; left: number; never: number; contacts: number; average: number }[];
  group_by: string;
  options: { rm: string[]; dc: string[]; state: string[]; district: string[] };
  total: number;
  page: number;
  page_size: number;
  pages: number;
  csps: DocumentsLeftRow[];
}

function documentsLeftQuery(params: DocumentsLeftParams): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  }
  return q.toString();
}
