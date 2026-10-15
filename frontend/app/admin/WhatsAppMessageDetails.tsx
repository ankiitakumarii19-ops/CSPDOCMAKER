"use client";

/**
 * Admin — one WhatsApp message, opened (tracker No. 111)
 *
 * Its journey (sent, delivered, read, answered), and for a details message
 * what the CSP did with each field they were asked about: changed it, added
 * it, confirmed what was there, or left it blank. Whether the answer reached
 * the sheet is shown too, since the sheet is the source of truth.
 *
 * Answers given before 15 Oct 2026 kept only the new values, so for those
 * the earlier value is shown as not recorded rather than guessed.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError, WhatsAppChat, WhatsAppFieldChange, WhatsAppMessageDetail,
} from "../lib/api";

const KIND_TITLE: Record<string, string> = {
  data_request: "Data verification",
  missing_data: "Data missing",
  documents_ready: "Documents sent",
  other: "Other",
};

const OUTCOME: Record<WhatsAppFieldChange["outcome"], { label: string; cls: string }> = {
  changed: { label: "Changed", cls: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300" },
  added: { label: "Added", cls: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
  confirmed: { label: "Confirmed, no change", cls: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  blank: { label: "Left blank", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  given: { label: "Answered", cls: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
};

const REQUEST_STATUS: Record<string, string> = {
  open: "Link still open — not answered yet",
  answered: "Answered",
  expired: "Link expired without an answer",
  cancelled: "Link closed (sent again, or not delivered)",
};

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function WhatsAppMessageDetails({
  id, onClose,
}: { id: string; onClose: () => void }) {
  const [data, setData] = useState<WhatsAppMessageDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    api.whatsappMessage(id)
      .then((d) => { if (current) setData(d); })
      .catch((e) => {
        if (current) setError((e as ApiError).detail || "Could not open this message.");
      });
    return () => { current = false; };
  }, [id]);

  // The chat is read live from the WhatsApp platform, so it loads on its
  // own and a failure there does not hide the rest of the panel.
  const [chat, setChat] = useState<WhatsAppChat | null>(null);
  const [chatError, setChatError] = useState("");

  useEffect(() => {
    let current = true;
    api.whatsappChat(id)
      .then((c) => { if (current) setChat(c); })
      .catch((e) => {
        if (current) setChatError((e as ApiError).detail || "Could not load the chat.");
      });
    return () => { current = false; };
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const m = data?.message;
  const req = data?.request;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose}></div>
      <aside className="relative w-full max-w-2xl h-full overflow-y-auto bg-white dark:bg-gray-800 shadow-xl">
        <div className="sticky top-0 flex items-start justify-between gap-4 px-6 py-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
          <div>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">
              {m ? `${m.csp_id || "—"} ${m.csp_name ? `· ${m.csp_name}` : ""}` : "Message"}
            </h3>
            {m && (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {KIND_TITLE[m.kind]} · {m.phone || "no number"}
                {m.is_test && " · TEST"}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-xl"
          >
            <i className="fas fa-xmark"></i>
          </button>
        </div>

        <div className="px-6 py-5 space-y-6">
          {error && (
            <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}
          {!data && !error && <p className="text-sm text-gray-500">Loading…</p>}

          {data && (
            <section>
              <h4 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-2">
                What happened
              </h4>
              <ol className="space-y-2">
                {data.timeline.map((t, i) => (
                  <li key={i} className="flex gap-3 text-sm">
                    <span className="w-40 shrink-0 text-gray-500 tabular-nums">{when(t.at)}</span>
                    <span className="text-gray-900 dark:text-gray-100">{t.what}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          {data && (
            <section>
              <h4 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-2">
                WhatsApp chat
              </h4>
              {!chat && !chatError && <p className="text-sm text-gray-500">Loading the chat…</p>}
              {(chatError || chat?.error) && (
                <p className="text-sm text-red-600 dark:text-red-400">{chatError || chat?.error}</p>
              )}
              {chat && !chat.error && chat.items.length === 0 && (
                <p className="text-sm text-gray-500">Nothing in the chat yet.</p>
              )}
              {chat && chat.items.length > 0 && (
                <div className="space-y-2 rounded-lg bg-gray-50 dark:bg-gray-900/40 p-3">
                  {chat.items.map((c, i) => (
                    <div key={i} className={`flex ${c.from === "us" ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                        c.from === "us"
                          ? "bg-green-100 text-gray-900 dark:bg-green-900/40 dark:text-gray-100"
                          : c.automatic
                            ? "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400 border border-dashed border-gray-300 dark:border-gray-600"
                            : "bg-white text-gray-900 dark:bg-gray-700 dark:text-gray-100 border border-gray-200 dark:border-gray-600"
                      }`}>
                        {c.automatic && (
                          <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-1">
                            Automatic reply — not counted as a response
                          </div>
                        )}
                        <div className="whitespace-pre-wrap break-words">
                          {c.text || <span className="italic">({c.type})</span>}
                        </div>
                        <div className="text-[10px] text-gray-500 mt-1 text-right">
                          {c.from === "us" ? "Sent by us · " : ""}{when(c.at)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          {data && !req && m?.kind !== "documents_ready" && (
            <p className="text-sm text-gray-500">
              This message is not linked to a details form, so there are no
              changes to show.
            </p>
          )}

          {req && (
            <section>
              <h4 className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">
                What the CSP changed
              </h4>
              <p className="text-sm text-gray-700 dark:text-gray-300 mb-3">
                {REQUEST_STATUS[req.status] || req.status}
                {req.answered && ` — ${when(req.answered_at)}`}
                {req.status === "open" && ` · link open until ${when(req.expires_at)}`}
              </p>

              {req.answered && (
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                  {req.counts.changed} changed · {req.counts.added} added ·{" "}
                  {req.counts.confirmed} confirmed · {req.counts.blank} left blank
                </p>
              )}
              {req.answered && !req.before_known && (
                <p className="mb-3 px-3 py-2 rounded bg-amber-50 dark:bg-amber-900/20 text-xs text-amber-800 dark:text-amber-200">
                  This was answered before earlier values were kept, so only
                  what the CSP sent is shown.
                </p>
              )}

              <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
                <table className="w-full text-left text-sm border-collapse">
                  <thead>
                    <tr className="text-xs uppercase tracking-wider text-gray-500 border-b border-gray-200 dark:border-gray-700">
                      <th className="px-3 py-2">Detail</th>
                      <th className="px-3 py-2">Before</th>
                      <th className="px-3 py-2">After</th>
                      <th className="px-3 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {req.fields.map((f) => {
                      const o = OUTCOME[f.outcome];
                      return (
                        <tr key={f.field} className="border-b border-gray-100 dark:border-gray-700/60 align-top">
                          <td className="px-3 py-2 font-medium text-gray-900 dark:text-white">{f.label}</td>
                          <td className="px-3 py-2 text-gray-600 dark:text-gray-400">
                            {f.before === null
                              ? <span className="italic">not recorded</span>
                              : f.before || <span className="text-gray-400">empty</span>}
                          </td>
                          <td className={`px-3 py-2 ${f.outcome === "changed" || f.outcome === "added" ? "font-semibold text-gray-900 dark:text-white" : "text-gray-600 dark:text-gray-400"}`}>
                            {req.answered ? (f.after || <span className="text-gray-400">—</span>) : <span className="text-gray-400">waiting</span>}
                          </td>
                          <td className="px-3 py-2">
                            {req.answered && (
                              <span className={`px-2 py-0.5 rounded text-xs font-semibold whitespace-nowrap ${o.cls}`}>
                                {o.label}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {req.photo_asked && (
                      <tr className="align-top">
                        <td className="px-3 py-2 font-medium text-gray-900 dark:text-white">Photo</td>
                        <td className="px-3 py-2 text-gray-400" colSpan={2}>
                          {req.photo_sent_at ? `New photo sent ${when(req.photo_sent_at)}` : "No photo sent"}
                        </td>
                        <td className="px-3 py-2">
                          {req.photo_sent_at && (
                            <span className={`px-2 py-0.5 rounded text-xs font-semibold ${OUTCOME.changed.cls}`}>
                              Changed
                            </span>
                          )}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {req.answered && (req.sheet_saved !== null || req.sheet_error) && (
                <p className={`mt-3 text-xs ${req.sheet_error ? "text-red-600 dark:text-red-400" : "text-gray-500"}`}>
                  {req.sheet_error
                    ? `Not yet written to the sheet: ${req.sheet_error}`
                    : `Written to the sheet: ${req.sheet_saved?.length ?? 0} detail(s).`}
                </p>
              )}
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
