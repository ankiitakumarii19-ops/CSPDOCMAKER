"use client";

/**
 * Admin — WhatsApp messages (tracker No. 110)
 *
 * For each of the three messages a CSP gets on WhatsApp — please confirm
 * your details, details still missing, your documents — who was sent one,
 * whose was rejected or never arrived, who read it, and who answered.
 *
 * "Answered" means the details form was filled in, or a reply came back on
 * WhatsApp. For the documents message only a WhatsApp reply counts: there
 * is nothing to fill in.
 *
 * Delivered / read / replied are fetched from Eko's WhatsApp platform every
 * few minutes; Refresh fetches them now.
 */

import { useEffect, useMemo, useState } from "react";

import ContactStatusLine from "../components/ContactStatusLine";
import { api } from "../lib/api";
import WhatsAppMessageDetails from "./WhatsAppMessageDetails";
import type {
  ApiError, WhatsAppCounts, WhatsAppMessageRow, WhatsAppRefreshResult,
  WhatsAppReport,
} from "../lib/api";

type Kind = "data_request" | "missing_data" | "documents_ready" | "feedback";
type Tile =
  | "left" | "not_sent" | "not_received" | "delivered" | "read"
  | "responded" | "not_responded";

const KINDS: Array<{ key: Kind; title: string; icon: string; note: string }> = [
  {
    key: "data_request",
    title: "Data verification",
    icon: "fa-user-check",
    note: "“Please confirm your details” — answered by filling in the form or replying.",
  },
  {
    key: "missing_data",
    title: "Data missing",
    icon: "fa-circle-exclamation",
    note: "“These details are still needed” — answered by filling in the form or replying.",
  },
  {
    key: "documents_ready",
    title: "Documents sent",
    icon: "fa-file-pdf",
    note: "“Your documents are ready”, PDF attached — answered by a WhatsApp reply.",
  },
  {
    key: "feedback",
    title: "Feedback question",
    icon: "fa-comment-dots",
    note: "“Did you get your documents? Reply 1 / 2 / 3” — 15 minutes after the documents message.",
  },
];

const KIND_TITLE: Record<string, string> = {
  data_request: "Data verification",
  missing_data: "Data missing",
  documents_ready: "Documents sent",
  other: "Other",
  feedback: "Feedback question",
};

// The tiles, in the order a message travels.
const TILES: Array<{ key: Tile; label: string; tone: string; count: (c: WhatsAppCounts) => number }> = [
  { key: "left", label: "Sent", tone: "text-gray-900 dark:text-white",
    count: (c) => c.total - c.not_sent },
  { key: "not_sent", label: "Rejected / not sent", tone: "text-red-600 dark:text-red-400",
    count: (c) => c.not_sent },
  { key: "not_received", label: "Not received", tone: "text-orange-600 dark:text-orange-400",
    count: (c) => c.not_received },
  { key: "delivered", label: "Delivered, not read", tone: "text-blue-600 dark:text-blue-400",
    count: (c) => c.delivered },
  { key: "read", label: "Read", tone: "text-green-600 dark:text-green-400",
    count: (c) => c.read },
  { key: "responded", label: "Responded", tone: "text-emerald-700 dark:text-emerald-400",
    count: (c) => c.responded },
  { key: "not_responded", label: "Not responded", tone: "text-amber-600 dark:text-amber-400",
    count: (c) => c.not_responded },
];

const STAGE_BADGE: Record<WhatsAppMessageRow["stage"], { label: string; cls: string }> = {
  not_sent: { label: "Rejected / not sent", cls: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  not_received: { label: "Not received", cls: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300" },
  sent: { label: "Sent", cls: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200" },
  delivered: { label: "Delivered", cls: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
  read: { label: "Read", cls: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
};

const PERIODS = [
  [7, "Last 7 days"],
  [30, "Last 30 days"],
  [90, "Last 90 days"],
  [0, "All time"],
] as const;

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function matches(row: WhatsAppMessageRow, tile: Tile): boolean {
  switch (tile) {
    case "left": return row.stage !== "not_sent";
    case "responded": return row.responded === true;
    case "not_responded": return row.responded === false;
    default: return row.stage === tile;
  }
}

export default function WhatsAppMessages() {
  const [data, setData] = useState<WhatsAppReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [days, setDays] = useState<number>(30);
  const [includeTests, setIncludeTests] = useState(true);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [focus, setFocus] = useState<{ kind: Kind; tile: Tile } | null>(null);
  // Why it was sent (No. 156): shows only the messages sent for that reason.
  const [because, setBecause] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshed, setRefreshed] = useState<WhatsAppRefreshResult | null>(null);

  // Bumped to load again with the same filters (after Refresh).
  const [reloads, setReloads] = useState(0);
  // The message whose details are open (No. 111).
  const [opened, setOpened] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    api.whatsappMessages({ days, include_tests: includeTests, q: query })
      .then((d) => {
        if (!current) return;
        setData(d);
        setError("");
      })
      .catch((e) => {
        if (current) {
          setError((e as ApiError).detail || "Could not load the WhatsApp messages.");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [days, includeTests, query, reloads]);

  async function refreshNow() {
    setRefreshing(true);
    setError("");
    try {
      const r = await api.refreshWhatsappMessages();
      setRefreshed(r);
      setReloads((n) => n + 1);
    } catch (e) {
      setError((e as ApiError).detail || "Could not refresh from WhatsApp.");
    } finally {
      setRefreshing(false);
    }
  }

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    if (because) return all.filter((r) => r.sent_because === because);
    if (!focus) return all.filter((r) => r.kind !== "other");
    return all.filter((r) => r.kind === focus.kind && matches(r, focus.tile));
  }, [data, focus, because]);

  const focusLabel = because
    ? `Sent because: ${data?.sent_because.find((b) => b.key === because)?.label ?? because}`
    : focus
    ? `${KIND_TITLE[focus.kind]} — ${TILES.find((t) => t.key === focus.tile)?.label}`
    : "All messages";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">
            WhatsApp messages
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Who was sent each message, whose was rejected or never arrived,
            who read it, and who answered. Click a number to see those CSPs.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            Status last fetched: {when(data?.last_checked_at ?? null)}
          </span>
          <button
            onClick={refreshNow}
            disabled={refreshing}
            className="px-3 py-2 rounded-lg text-sm font-semibold bg-navy-900 text-white hover:bg-navy-800 disabled:opacity-50"
          >
            <i className={`fas fa-rotate mr-2 ${refreshing ? "fa-spin" : ""}`}></i>
            {refreshing ? "Fetching from WhatsApp…" : "Refresh now"}
          </button>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {refreshed && (
        <div className={`px-4 py-3 rounded-lg border text-sm ${
          refreshed.errors.length
            ? "bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200"
            : "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-800 dark:text-green-200"
        }`}>
          Checked {refreshed.checked} message(s): {refreshed.status_changed} changed,{" "}
          {refreshed.responded} newly answered, {refreshed.imported} found in
          WhatsApp&apos;s history.
          {refreshed.errors.length > 0 && (
            <ul className="mt-1 list-disc pl-5">
              {refreshed.errors.map((e) => <li key={e}>{e}</li>)}
            </ul>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-800 dark:text-gray-200"
        >
          {PERIODS.map(([d, label]) => (
            <option key={d} value={d}>{label}</option>
          ))}
        </select>
        <form
          onSubmit={(e) => { e.preventDefault(); setQuery(search); }}
          className="flex items-center gap-2"
        >
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="CSP code, name or mobile"
            className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-sm text-gray-800 dark:text-gray-200 w-64"
          />
          <button className="px-3 py-2 rounded-lg text-sm border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700">
            Search
          </button>
        </form>
        <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
          <input
            type="checkbox"
            checked={includeTests}
            onChange={(e) => setIncludeTests(e.target.checked)}
          />
          Include test messages
        </label>
      </div>

      {loading && !data && <p className="text-sm text-gray-500 py-8">Loading…</p>}

      {/* Why messages were sent, besides the usual flow (No. 156). */}
      {data && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-5 py-3">
          <div className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
            Why messages were sent (besides the usual flow)
          </div>
          {data.sent_because.length === 0 ? (
            <p className="text-xs text-gray-500">
              None yet in this period — messages sent because an email bounced, the CSP asked, an
              alternate number, or a reply will show here.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {data.sent_because.map((b) => (
                <button
                  key={b.key}
                  onClick={() => {
                    setFocus(null);
                    setBecause(because === b.key ? "" : b.key);
                  }}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${
                    because === b.key
                      ? "bg-eko/10 text-eko border-eko"
                      : "border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                  }`}
                >
                  {b.label} <span className="font-bold tabular-nums ml-1">{b.count}</span>
                </button>
              ))}
            </div>
          )}
          <ContactStatusLine status={data.contact_fixes} />
        </div>
      )}

      {/* One card per message */}
      {data && (
        <div className="space-y-4">
          {KINDS.map((k) => {
            const counts = data.summary[k.key];
            return (
              <section
                key={k.key}
                className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
                  <h3 className="text-base font-bold text-gray-900 dark:text-white">
                    <i className={`fas ${k.icon} mr-2 text-gray-400`}></i>
                    {k.title}
                    <span className="ml-2 text-sm font-normal text-gray-500">
                      {counts.total} message{counts.total === 1 ? "" : "s"}
                    </span>
                  </h3>
                  <span className="text-xs text-gray-500 dark:text-gray-400">{k.note}</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
                  {TILES.map((t) => {
                    const active = focus?.kind === k.key && focus.tile === t.key;
                    return (
                      <button
                        key={t.key}
                        onClick={() => {
                          setBecause("");
                          setFocus(active ? null : { kind: k.key, tile: t.key });
                        }}
                        className={`text-left rounded-lg border px-3 py-2 transition-colors ${
                          active
                            ? "border-eko bg-gray-50 dark:bg-gray-700"
                            : "border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                        }`}
                      >
                        <div className={`text-2xl font-bold tabular-nums ${t.tone}`}>
                          {t.count(counts)}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">{t.label}</div>
                      </button>
                    );
                  })}
                </div>
                {k.key === "feedback" && data.feedback_answers && (
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    <span className="text-gray-500">Answers:</span>
                    <span className="px-2 py-1 rounded bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300">
                      1 · got them, all correct <b className="ml-1">{data.feedback_answers.answers["1"]}</b>
                    </span>
                    <span className="px-2 py-1 rounded bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300">
                      2 · did not get them <b className="ml-1">{data.feedback_answers.answers["2"]}</b>
                    </span>
                    <span className="px-2 py-1 rounded bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                      3 · something is wrong <b className="ml-1">{data.feedback_answers.answers["3"]}</b>
                    </span>
                    <span className="px-2 py-1 rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                      no answer yet <b className="ml-1">{data.feedback_answers.no_answer}</b>
                    </span>
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      {/* The messages themselves */}
      {data && (
        <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
          <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-bold text-gray-900 dark:text-white">
              {focusLabel}
              <span className="ml-2 font-normal text-gray-500">{rows.length}</span>
              <span className="ml-3 text-xs font-normal text-gray-400">
                Click a message to see what the CSP changed
              </span>
            </h3>
            {(focus || because) && (
              <button
                onClick={() => {
                  setFocus(null);
                  setBecause("");
                }}
                className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                Show all
              </button>
            )}
          </div>
          {data.truncated && (
            <p className="px-5 py-2 text-xs text-amber-700 dark:text-amber-300">
              Showing the latest {data.rows.length} of {data.total_rows}. Choose a shorter
              period or search to see the rest.
            </p>
          )}
          {rows.length === 0 ? (
            <p className="px-5 py-8 text-sm text-gray-500 text-center">
              No messages here.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="text-xs uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-gray-700">
                    <th className="px-4 py-2">CSP</th>
                    <th className="px-4 py-2">Mobile</th>
                    <th className="px-4 py-2">Message</th>
                    <th className="px-4 py-2">Sent</th>
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2">Responded</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const badge = STAGE_BADGE[r.stage];
                    return (
                      <tr
                        key={r.id}
                        onClick={() => setOpened(r.id)}
                        title="Open this message"
                        className="border-b border-gray-100 dark:border-gray-700/60 align-top cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/40"
                      >
                        <td className="px-4 py-2">
                          <div className="font-semibold text-gray-900 dark:text-white">
                            {r.csp_id || "—"}
                            {r.is_test && (
                              <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-bold bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300">
                                TEST
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-gray-500">{r.csp_name || ""}</div>
                        </td>
                        <td className="px-4 py-2 tabular-nums text-gray-700 dark:text-gray-300">
                          {r.phone || "—"}
                        </td>
                        <td className="px-4 py-2 text-gray-700 dark:text-gray-300">
                          {KIND_TITLE[r.kind] ?? "Message"}
                          {r.sent_because && (
                            <div className="mt-1">
                              <span className="px-1.5 py-0.5 rounded text-[11px] bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                                {r.sent_because_label}
                              </span>
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-2 whitespace-nowrap text-gray-700 dark:text-gray-300">
                          {when(r.sent_at)}
                        </td>
                        <td className="px-4 py-2">
                          <span className={`px-2 py-0.5 rounded text-xs font-semibold ${badge.cls}`}>
                            {badge.label}
                          </span>
                          {r.stage !== "not_sent" && r.delivery_updated_at && (
                            <div className="text-xs text-gray-500 mt-1">
                              {when(r.delivery_updated_at)}
                            </div>
                          )}
                          {r.reason && (
                            <div className="text-xs text-gray-500 mt-1 max-w-xs">{r.reason}</div>
                          )}
                          {r.check_error && (
                            <div className="text-xs text-amber-700 dark:text-amber-300 mt-1 max-w-xs">
                              Last status check failed: {r.check_error}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-2">
                          {r.responded === null && <span className="text-gray-400">—</span>}
                          {r.responded === false && (
                            <div>
                              <span className="text-amber-600 dark:text-amber-400 font-semibold">No</span>
                              {r.auto_reply_at && (
                                <div className="text-xs text-gray-500">
                                  only an automatic greeting came back
                                </div>
                              )}
                            </div>
                          )}
                          {r.responded === true && (
                            <div>
                              <span className="text-emerald-700 dark:text-emerald-400 font-semibold">
                                {r.response_kind === "form" ? "Filled the form" : "Replied on WhatsApp"}
                              </span>
                              <div className="text-xs text-gray-500">{when(r.responded_at)}</div>
                              {r.response_text && (
                                <div className="text-xs text-gray-600 dark:text-gray-300 mt-1 max-w-xs italic">
                                  “{r.response_text}”
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      {opened && (
        <WhatsAppMessageDetails key={opened} id={opened} onClose={() => setOpened(null)} />
      )}
    </div>
  );
}
