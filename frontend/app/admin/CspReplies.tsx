"use client";

/**
 * WhatsApp messages → Replies to CSPs (tracker No. 151).
 *
 * What CSPs wrote back on WhatsApp, what the reply agent understood, and
 * the reply it wrote (rules + the Knowledge Base's "CSP replies" wordings;
 * not understood → "contact your RM <name> (<number>)"). No AI.
 *
 * Draft mode: each reply waits here — edit it if needed, then Send or Skip.
 * Auto mode: replies go out by themselves (8 am – 8 pm, max 3 a day per
 * CSP). Only the Super Admin changes the mode.
 */

import { useCallback, useEffect, useState } from "react";

import ReplyLearning from "./ReplyLearning";
import { api } from "../lib/api";
import type { ApiError, CspReplyRow } from "../lib/api";

const MODES: { key: "off" | "draft" | "auto"; label: string; hint: string }[] = [
  { key: "draft", label: "Drafts", hint: "A person sends each reply" },
  { key: "auto", label: "Automatic", hint: "Replies go out by themselves, 8 am – 8 pm" },
  { key: "off", label: "Off", hint: "Messages are not read or answered" },
];

const STATUS: Record<CspReplyRow["status"], { label: string; cls: string }> = {
  draft: { label: "Waiting", cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" },
  sent: { label: "Sent", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  skipped: { label: "Skipped", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  failed: { label: "Failed", cls: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  expired: { label: "Too old", cls: "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400" },
};

function when(iso: string | null) {
  return iso
    ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "";
}

export default function CspReplies({ canSwitch }: { canSwitch: boolean }) {
  const [rows, setRows] = useState<CspReplyRow[] | null>(null);
  const [mode, setMode] = useState<"off" | "draft" | "auto">("draft");
  const [showAll, setShowAll] = useState(false);
  const [texts, setTexts] = useState<Record<string, string>>({});
  // No. 161: whether the data verification link goes with the reply.
  const [links, setLinks] = useState<Record<string, boolean>>({});
  const plansLink = (r: CspReplyRow) => (r.action || "").includes("fresh_link");
  // No. 165: "1 — got them, all correct" and nothing else: no link button.
  const allGood = (r: CspReplyRow) =>
    !plansLink(r) && r.intents.length > 0 && r.intents.every((i) => i.key === "feedback_1");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [rowError, setRowError] = useState<{ id: string; text: string } | null>(null);

  const load = useCallback(
    () =>
      api
        .cspReplies(showAll ? "" : "draft")
        .then((r) => {
          setRows(r.replies);
          setMode(r.mode);
          setError("");
        })
        .catch((e) => setError((e as ApiError).detail || "Could not load the replies.")),
    [showAll]
  );

  useEffect(() => {
    load();
  }, [load]);

  async function act(r: CspReplyRow, what: "send" | "skip" | "link") {
    setBusy(r.id);
    setRowError(null);
    try {
      if (what === "send")
        await api.sendCspReply(r.id, texts[r.id] ?? r.reply_text, links[r.id] ?? plansLink(r));
      else if (what === "link") await api.linkCspReply(r.id);
      else await api.skipCspReply(r.id);
      await load();
    } catch (e) {
      setRowError({ id: r.id, text: (e as ApiError).detail || "Could not do that." });
    } finally {
      setBusy("");
    }
  }

  async function switchMode(next: "off" | "draft" | "auto") {
    if (next === "auto" && !window.confirm(
      "Replies will go out to CSPs by themselves (8 am – 8 pm, max 3 a day each). Switch to automatic?"
    )) return;
    try {
      setMode((await api.setCspReplyMode(next)).mode);
    } catch (e) {
      setError((e as ApiError).detail || "Could not change the mode.");
    }
  }

  const button = "px-2.5 py-1 rounded text-xs font-semibold disabled:opacity-50";
  const waiting = rows?.filter((r) => r.status === "draft").length ?? 0;

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[16rem]">
          <h3 className="font-semibold text-gray-900 dark:text-white">
            Replies to CSPs{" "}
            {waiting > 0 && (
              <span className="ml-1 px-2 py-0.5 rounded-full text-xs bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                {waiting} waiting
              </span>
            )}
          </h3>
          <p className="text-xs text-gray-500">
            What CSPs wrote back, and the reply the agent wrote from fixed rules and the Knowledge
            Base (category &quot;CSP replies&quot; — edit the wordings there). Anything it does not
            understand: &quot;contact your RM&quot; with their name and number.
          </p>
        </div>
        <div className="flex items-center gap-1" title={canSwitch ? "" : "Only the Super Admin changes this"}>
          {MODES.map((m) => (
            <button
              key={m.key}
              disabled={!canSwitch}
              onClick={() => mode !== m.key && switchMode(m.key)}
              title={m.hint}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium disabled:cursor-not-allowed ${
                mode === m.key
                  ? "bg-eko/10 text-eko"
                  : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:hover:bg-transparent"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <button onClick={() => setShowAll(!showAll)} className="text-xs text-eko hover:underline">
          {showAll ? "Only waiting" : "Show all"}
        </button>
      </div>
      <ReplyLearning version={rows?.length ?? 0} />
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="divide-y divide-gray-100 dark:divide-gray-700">
        {rows?.map((r) => (
          <div key={r.id} className="px-5 py-3 grid gap-3 md:grid-cols-2 text-sm">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-gray-900 dark:text-white font-medium">{r.csp_name || "—"}</span>
                <span className="text-xs font-mono text-gray-500">{r.csp_id}</span>
                <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS[r.status].cls}`}>
                  {STATUS[r.status].label}
                </span>
              </div>
              <div className="mt-2 space-y-1">
                {r.messages.map((m, i) => (
                  <div key={i} className="px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-900/50 text-gray-800 dark:text-gray-200">
                    {m.text || `(${m.type})`}
                    <span className="ml-2 text-[11px] text-gray-400">{when(m.at)}</span>
                  </div>
                ))}
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {r.intents.map((i) => (
                  <span key={i.key} className="px-2 py-0.5 rounded text-[11px] bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                    {i.label}
                  </span>
                ))}
              </div>
            </div>
            <div>
              {r.status === "draft" || r.status === "failed" ? (
                <>
                  <textarea
                    rows={4}
                    value={texts[r.id] ?? r.reply_text}
                    onChange={(e) => setTexts({ ...texts, [r.id]: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white"
                  />
                  <label className="mt-1 flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
                    <input
                      type="checkbox"
                      checked={links[r.id] ?? plansLink(r)}
                      onChange={(e) => setLinks({ ...links, [r.id]: e.target.checked })}
                    />
                    Also send the data verification link (the old link is closed)
                  </label>
                  <div className="mt-2 flex gap-1">
                    <button
                      disabled={busy === r.id || !(texts[r.id] ?? r.reply_text).trim()}
                      onClick={() => act(r, "send")}
                      className={`${button} bg-navy-900 text-white hover:bg-navy-800`}
                    >
                      <i className="fab fa-whatsapp mr-1"></i>
                      {busy === r.id ? "Sending…" : "Send"}
                    </button>
                    {r.status === "draft" && (
                      <button
                        disabled={busy === r.id}
                        onClick={() => act(r, "skip")}
                        className={`${button} text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700`}
                      >
                        Skip
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="px-3 py-2 rounded-lg bg-green-50/50 dark:bg-green-900/10 text-gray-800 dark:text-gray-200">
                    {r.reply_text || <span className="text-gray-400">No reply</span>}
                    {r.status === "sent" && r.edited !== null && (
                      <span className={`ml-2 px-1.5 py-0.5 rounded text-[11px] ${
                        r.edited ? "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                                 : "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300"}`}>
                        {r.edited ? "changed from the draft" : "sent as drafted"}
                      </span>
                    )}
                  </div>
                  {r.status === "sent" && r.edited && r.draft_text && (
                    <div className="text-xs text-gray-400 mt-1">Agent&apos;s draft: {r.draft_text}</div>
                  )}
                  {r.status === "sent" && !allGood(r) && (
                    <button
                      disabled={busy === r.id}
                      onClick={() => act(r, "link")}
                      className="mt-1 px-2.5 py-1 rounded text-xs font-semibold text-eko hover:bg-eko/10 disabled:opacity-50"
                    >
                      <i className="fas fa-link mr-1"></i>
                      {plansLink(r) ? "Send the data verification link again" : "Send data verification link"}
                    </button>
                  )}
                </>
              )}
              <div className="text-xs text-gray-500 mt-1">
                {r.sent_at && `Sent ${when(r.sent_at)} by ${r.decided_by}. `}
                {r.note}
              </div>
              {rowError?.id === r.id && (
                <div className="text-xs text-red-600 dark:text-red-400 mt-1">{rowError.text}</div>
              )}
            </div>
          </div>
        ))}
        {rows && rows.length === 0 && !error && (
          <p className="px-5 py-6 text-sm text-gray-500">
            {showAll ? "No CSP has written back yet." : "No replies waiting."}
          </p>
        )}
      </div>
    </section>
  );
}
