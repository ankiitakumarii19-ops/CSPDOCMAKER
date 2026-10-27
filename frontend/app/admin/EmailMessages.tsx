"use client";

/**
 * Admin — Emails (tracker No. 127)
 *
 * Every email the app sends to a CSP — their documents, details requests,
 * chat messages — with what became of it: sent or failed (and why), opened
 * (a 1-pixel picture in the email loaded), bounced (Gmail returned it as
 * undeliverable). "Opened" is reliable; "not opened" is not proof it was not
 * read, because many mail apps block pictures.
 */

import { useCallback, useEffect, useState } from "react";

import ContactStatusLine from "../components/ContactStatusLine";
import { api } from "../lib/api";
import type { ApiError, EmailReport } from "../lib/api";

const TILES: { key: string; label: string; tone: string }[] = [
  { key: "sent", label: "Sent", tone: "text-gray-900 dark:text-white" },
  { key: "failed", label: "Failed", tone: "text-red-600 dark:text-red-400" },
  { key: "bounced", label: "Bounced", tone: "text-red-600 dark:text-red-400" },
  { key: "opened", label: "Opened", tone: "text-eko-dark dark:text-eko" },
  { key: "not_opened", label: "Not opened", tone: "text-amber-600 dark:text-amber-400" },
];
// The boxes shown at the top (asked 26 Oct 2026): documents and details
// requests only. Chat and other emails are still recorded and listed below.
const SHOWN_KINDS = ["documents", "details_request"];

const STATUS: Record<string, { label: string; cls: string }> = {
  failed: { label: "Failed", cls: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  bounced: { label: "Bounced", cls: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  opened: { label: "Opened", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  not_opened: { label: "Not opened", cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" },
};

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export default function EmailMessages() {
  const [data, setData] = useState<EmailReport | null>(null);
  const [error, setError] = useState("");
  const [focus, setFocus] = useState<{ kind?: string; status?: string; because?: string }>({});
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await api.emailMessages({ ...focus, q: q.trim() || undefined }));
    } catch (e) {
      setError((e as ApiError).detail || "Could not load the emails.");
    }
  }, [focus, q]);

  useEffect(() => {
    load();
  }, [load]);

  async function checkBounces() {
    setBusy(true);
    setNote("");
    try {
      const r = await api.checkEmailBounces();
      setNote(
        r.checked
          ? `Checked the inbox: ${r.notices} bounce notice(s), ${r.marked} newly marked.`
          : `Not checked: ${r.reason}`
      );
      await load();
    } catch (e) {
      setNote((e as ApiError).detail || "Could not check for bounces.");
    } finally {
      setBusy(false);
    }
  }

  const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Emails</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 max-w-2xl">
            Every email sent to a CSP and what became of it. Click a number to see those emails.
            {data?.note ? ` ${data.note}` : ""}
          </p>
        </div>
        <button
          onClick={checkBounces}
          disabled={busy}
          className="px-3 py-2 rounded-lg text-sm font-semibold bg-navy-900 text-white hover:bg-navy-800 disabled:opacity-50"
        >
          <i className={`fas fa-rotate mr-2 ${busy ? "fa-spin" : ""}`}></i>
          {busy ? "Checking…" : "Check bounces now"}
        </button>
      </div>

      {note && <div className="text-sm text-gray-600 dark:text-gray-300">{note}</div>}
      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Why emails were sent, besides the usual flow (No. 156). */}
      {data && (
        <section className={`${card} px-5 py-3`}>
          <div className="text-sm font-semibold text-gray-900 dark:text-white mb-2">
            Why emails were sent (besides the usual flow)
          </div>
          {data.sent_because.length === 0 ? (
            <p className="text-xs text-gray-500">
              None yet — emails sent because WhatsApp could not reach the CSP, or sent again after
              a correction or a &quot;did not get them&quot; answer, will show here.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {data.sent_because.map((b) => (
                <button
                  key={b.key}
                  onClick={() => setFocus(focus.because === b.key ? {} : { because: b.key })}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${
                    focus.because === b.key
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
        </section>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {data &&
          Object.entries(data.counts)
            .filter(([kind]) => SHOWN_KINDS.includes(kind))
            .map(([kind, c]) => (
            <section key={kind} className={`${card} p-5`}>
              <h3 className="font-semibold text-gray-900 dark:text-white mb-3">{c.title}</h3>
              <div className="grid grid-cols-5 gap-2">
                {TILES.map((t) => (
                  <button
                    key={t.key}
                    onClick={() => setFocus({ kind, status: t.key })}
                    className={`text-left rounded-lg p-2 hover:bg-gray-50 dark:hover:bg-gray-700 ${
                      focus.kind === kind && focus.status === t.key ? "ring-2 ring-eko" : ""
                    }`}
                  >
                    <div className={`text-2xl font-bold tabular-nums ${t.tone}`}>
                      {(c as unknown as Record<string, number>)[t.key] ?? 0}
                    </div>
                    <div className="text-xs text-gray-500">{t.label}</div>
                  </button>
                ))}
              </div>
            </section>
          ))}
      </div>

      <section className={card}>
        <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 flex flex-wrap items-center gap-3">
          <h3 className="font-semibold text-gray-900 dark:text-white flex-1">
            {focus.because
              ? `Sent because: ${data?.sent_because.find((b) => b.key === focus.because)?.label ?? focus.because}`
              : focus.kind
              ? `${data?.counts[focus.kind]?.title ?? focus.kind} — ${
                  TILES.find((t) => t.key === focus.status)?.label ?? "all"
                }`
              : "All emails"}{" "}
            <span className="text-sm font-normal text-gray-500">({data?.total ?? 0})</span>
          </h3>
          {(focus.kind || focus.status || focus.because) && (
            <button onClick={() => setFocus({})} className="text-sm text-eko hover:underline">
              Show all
            </button>
          )}
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="CSP code, name or email…"
            className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-5 py-2">CSP</th>
                <th className="px-5 py-2">To</th>
                <th className="px-5 py-2">Email</th>
                <th className="px-5 py-2">Sent</th>
                <th className="px-5 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {data?.messages.map((m) => (
                <tr key={m.id}>
                  <td className="px-5 py-2">
                    <div className="text-gray-900 dark:text-white">{m.csp_name || "—"}</div>
                    <div className="text-xs font-mono text-gray-500">{m.csp_id || ""}</div>
                  </td>
                  <td className="px-5 py-2 text-gray-700 dark:text-gray-300">{m.to}</td>
                  <td className="px-5 py-2 text-gray-700 dark:text-gray-300">
                    <div>{m.subject}</div>
                    <div className="text-xs text-gray-500">{data.counts[m.kind]?.title ?? m.kind}</div>
                    {m.sent_because && (
                      <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[11px] bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                        {m.sent_because_label}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-2 text-gray-500 whitespace-nowrap">{when(m.sent_at)}</td>
                  <td className="px-5 py-2">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS[m.status]?.cls ?? ""}`}>
                      {STATUS[m.status]?.label ?? m.status}
                    </span>
                    <div className="text-xs text-gray-500 mt-1">
                      {m.status === "opened" &&
                        `${when(m.opened_at)}${m.open_count > 1 ? ` · ${m.open_count}×` : ""}`}
                      {m.status === "failed" && m.error}
                      {m.status === "bounced" && m.bounce_reason}
                    </div>
                  </td>
                </tr>
              ))}
              {data && data.messages.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-5 py-6 text-sm text-gray-500">
                    No emails here yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
