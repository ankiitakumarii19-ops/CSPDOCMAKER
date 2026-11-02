"use client";

/**
 * One Action Required card, opened (No. 174): the CSP, what is still
 * missing, when it was flagged, every time they were asked (when, how,
 * what), what they wrote back, what people sent them, and — once filled —
 * how and when. From here: message the CSP, or open their WhatsApp chat.
 *
 * RMs see and message their own CSPs (and unowned ones); the server checks.
 */

import { useCallback, useEffect, useState } from "react";

import CspChat from "../admin/CspChat";
import { api } from "../lib/api";
import type { ActionDetail, ApiError, CspSendResult } from "../lib/api";

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/** {name}, {csp_id}, {missing_items} as the server fills them. */
export function fillPlaceholders(text: string, name: string, cspId: string, missing: string[]) {
  return text
    .split("{name}").join(name || "CSP")
    .split("{csp_id}").join(cspId)
    .split("{missing_items}").join(missing.join(", ") || "nothing");
}

const box = "rounded-lg border border-gray-200 dark:border-gray-700 p-3";
const h4 = "text-xs font-bold uppercase tracking-wider text-gray-500 mb-2";

export default function ActionRequiredDetail({
  id,
  onClose,
  onWorkOn,
}: {
  id: string;
  onClose: () => void;
  /** Open the CSP in the RM's documents flow (what a click used to do). */
  onWorkOn?: (cspId: string) => void;
}) {
  const [data, setData] = useState<ActionDetail | null>(null);
  const [error, setError] = useState("");
  const [chat, setChat] = useState(false);
  const [kind, setKind] = useState<"custom" | "details_form">("custom");
  const [channel, setChannel] = useState("whatsapp");
  const [text, setText] = useState(
    "Namaste {name}, please send us your {missing_items} so we can make your documents."
  );
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<CspSendResult | null>(null);

  const load = useCallback(() => {
    api
      .alertDetail(id)
      .then((d) => {
        setData(d);
        setError("");
        const first = d.channels.find((c) => c.can_send);
        if (first) setChannel(first.kind);
      })
      .catch((e) => setError((e as ApiError).detail || "Could not open this item."));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !chat && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, chat]);

  const send = async () => {
    if (!data) return;
    setSending(true);
    setSent(null);
    try {
      setSent(await api.messageCsp(data.csp_id, { kind, channel, text }));
      load();
    } catch (e) {
      setSent({
        csp_id: data.csp_id, sent: false, channel, kind, text: "",
        reason: (e as ApiError).detail || "Could not send.",
      });
    } finally {
      setSending(false);
    }
  };

  const usable = data?.channels.filter((c) => c.can_send) ?? [];
  const preview = data ? fillPlaceholders(text, data.name, data.csp_id, data.missing) : "";
  const blocked =
    data?.on_hold
      ? `On hold — nothing is sent: ${data.on_hold}`
      : kind === "details_form" && data?.existing
      ? "An existing CSP is never sent the details form. Send a custom message instead."
      : "";

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose}></div>
      <aside className="relative w-full max-w-2xl h-full overflow-y-auto bg-white dark:bg-gray-800 shadow-xl pb-[env(safe-area-inset-bottom)]">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 px-4 sm:px-6 py-4 pt-[calc(1rem+env(safe-area-inset-top))] sm:pt-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">
              {data?.name ?? "…"} <span className="text-sm font-mono text-gray-500">{data?.csp_id}</span>
            </h3>
            {data && (
              <p className="text-sm text-gray-500">
                Flagged {when(data.flagged_at)}
                {data.status === "fixed" && <> · Fixed {when(data.fixed_at)}</>}
              </p>
            )}
          </div>
          <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-xl">
            <i className="fas fa-xmark"></i>
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          {!data && !error && <p className="text-sm text-gray-500">Loading…</p>}

          {data && (
            <>
              <section className={box}>
                <h4 className={h4}>{data.status === "fixed" ? "Was missing" : "Missing"}</h4>
                <div className="flex flex-wrap gap-1.5">
                  {data.missing.map((m) => (
                    <span key={m} className={`px-2 py-0.5 rounded text-xs ${
                      data.status === "fixed"
                        ? "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                        : "bg-orange-50 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300"}`}>
                      {m}
                    </span>
                  ))}
                </div>
                {data.status === "fixed" && (
                  <p className="text-sm text-green-700 dark:text-green-400 mt-2">
                    <i className="fas fa-check-circle mr-1"></i>
                    Fixed {when(data.fixed_at)} — {data.fixed_note || data.fixed_via_label}
                  </p>
                )}
                <div className="flex flex-wrap gap-2 mt-3">
                  <button onClick={() => setChat(true)} className="px-3 py-1.5 rounded-lg text-sm bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-100 hover:bg-gray-200">
                    <i className="fas fa-comments mr-1 text-eko"></i> Open chat
                  </button>
                  {onWorkOn && (
                    <button onClick={() => onWorkOn(data.csp_id)} className="px-3 py-1.5 rounded-lg text-sm bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-100 hover:bg-gray-200">
                      <i className="fas fa-file-lines mr-1"></i> Work on this CSP
                    </button>
                  )}
                </div>
              </section>

              <section className={box}>
                <h4 className={h4}>Asked for their details</h4>
                {data.asked.length === 0 ? (
                  <p className="text-sm text-gray-500">Not asked yet.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.asked.map((a, i) => (
                      <li key={i} className="text-gray-700 dark:text-gray-300">
                        <span className="font-medium">{when(a.at)}</span> · {a.channel || "—"}
                        {a.to && <> to {a.to}</>} · asked for {a.fields.join(", ") || "their details"} ·{" "}
                        <span className={a.status === "answered" ? "text-green-700 dark:text-green-400" : ""}>
                          {a.status === "answered" ? `answered ${when(a.answered_at)}` : a.status}
                        </span>
                        {a.error && <div className="text-xs text-red-600">{a.error}</div>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className={box}>
                <h4 className={h4}>Messages sent</h4>
                {data.whatsapp.length === 0 && data.emails.length === 0 ? (
                  <p className="text-sm text-gray-500">Nothing sent yet.</p>
                ) : (
                  <ul className="space-y-1.5 text-sm">
                    {data.whatsapp.map((m, i) => (
                      <li key={`w${i}`} className="text-gray-700 dark:text-gray-300">
                        <i className="fab fa-whatsapp text-green-600 mr-1"></i>
                        <span className="font-medium">{when(m.at)}</span> · {m.what}
                        <span className="text-xs text-gray-500"> · {m.stage}{m.sent_by ? ` · by ${m.sent_by}` : ""} · {m.why}</span>
                        {m.error && <div className="text-xs text-red-600">{m.error}</div>}
                      </li>
                    ))}
                    {data.emails.map((m, i) => (
                      <li key={`e${i}`} className="text-gray-700 dark:text-gray-300">
                        <i className="fas fa-envelope text-blue-500 mr-1"></i>
                        <span className="font-medium">{when(m.at)}</span> · {m.subject}
                        <span className="text-xs text-gray-500"> · {m.status}{m.bounced ? " · bounced" : m.opened_at ? " · opened" : ""}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className={box}>
                <h4 className={h4}>Their replies</h4>
                {data.replies.length === 0 ? (
                  <p className="text-sm text-gray-500">No reply yet.</p>
                ) : (
                  <div className="space-y-2">
                    {data.replies.map((r, i) => (
                      <div key={i} className="space-y-1">
                        {r.messages.map((m, j) => (
                          <div key={j} className="px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-900/50 text-sm text-gray-800 dark:text-gray-200">
                            {m.text || `(${m.type})`}
                            <span className="ml-2 text-xs text-gray-400">{when(m.at)}</span>
                          </div>
                        ))}
                        {r.answer && r.status === "sent" && (
                          <div className="ml-6 px-3 py-1.5 rounded-lg bg-green-50 dark:bg-green-900/20 text-sm text-gray-800 dark:text-gray-200">
                            {r.answer}
                            <span className="ml-2 text-xs text-gray-400">{when(r.sent_at)}{r.by ? ` · ${r.by}` : ""}</span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {data.status === "pending" && (
                <section className={box}>
                  <h4 className={h4}>Message this CSP</h4>
                  <div className="flex flex-wrap gap-3 text-sm mb-2">
                    <label className="flex items-center gap-1">
                      <input type="radio" className="accent-eko" checked={kind === "custom"} onChange={() => setKind("custom")} />
                      Your own message
                    </label>
                    <label className="flex items-center gap-1">
                      <input type="radio" className="accent-eko" checked={kind === "details_form"} onChange={() => setKind("details_form")} />
                      Details form (usual message + link)
                    </label>
                  </div>
                  {kind === "custom" && (
                    <>
                      <textarea
                        rows={3}
                        value={text}
                        maxLength={900}
                        onChange={(e) => setText(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white"
                      />
                      <p className="text-xs text-gray-500">
                        {"{name}"}, {"{csp_id}"} and {"{missing_items}"} are filled in. Preview:{" "}
                        <span className="text-gray-700 dark:text-gray-300">{preview}</span>
                      </p>
                    </>
                  )}
                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    <select
                      value={channel}
                      onChange={(e) => setChannel(e.target.value)}
                      className="px-2 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm dark:text-white"
                    >
                      {data.channels.map((c) => (
                        <option key={c.kind} value={c.kind} disabled={!c.can_send}>
                          {c.label}{c.can_send ? "" : " — not available"}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={send}
                      disabled={sending || !!blocked || usable.length === 0 || (kind === "custom" && !text.trim())}
                      className="px-4 py-1.5 rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm"
                    >
                      {sending ? "Sending…" : "Send"}
                    </button>
                  </div>
                  {blocked && <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">{blocked}</p>}
                  {usable.length === 0 && (
                    <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                      No channel can send right now: {data.channels.map((c) => `${c.label} — ${c.why_not}`).join(" · ")}
                    </p>
                  )}
                  {sent && (
                    <p className={`text-sm mt-2 ${sent.sent ? "text-green-700 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                      {sent.sent ? "Sent." : `Not sent: ${sent.reason}`}
                    </p>
                  )}
                </section>
              )}

              {data.sent_by_people.length > 0 && (
                <section className={box}>
                  <h4 className={h4}>Sent by people</h4>
                  <ul className="space-y-1 text-sm">
                    {data.sent_by_people.map((m, i) => (
                      <li key={i} className="text-gray-700 dark:text-gray-300">
                        <span className="font-medium">{when(m.at)}</span> · {m.channel} · {m.by}:{" "}
                        {m.text}{" "}
                        <span className={m.sent ? "text-green-700 dark:text-green-400" : "text-red-600"}>
                          {m.sent ? "sent" : `not sent (${m.reason})`}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </div>
      </aside>
      {chat && data && <CspChat cspId={data.csp_id} onClose={() => setChat(false)} />}
    </div>
  );
}
