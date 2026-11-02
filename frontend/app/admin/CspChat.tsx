"use client";

/**
 * One CSP's whole WhatsApp chat (No. 171), opened from their name or a
 * quoted message on the Replies screen. Our messages and what they wrote
 * back, oldest first; the CSP's side is read live from Eko's WhatsApp
 * platform, and a failure to read it is shown, not hidden.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, CspChat as Chat } from "../lib/api";

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function CspChat({
  cspId,
  highlight,
  onClose,
  inline = false,
}: {
  cspId: string;
  /** A message to scroll to and mark — the one that was quoted. */
  highlight?: string;
  onClose: () => void;
  /** Beside a list on a desktop (No. 176) rather than over the page. */
  inline?: boolean;
}) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    api
      // The CSP-side address works for RMs (own CSPs) and Admins (No. 174).
      .cspConversation(cspId)
      .then((c) => current && setChat(c))
      .catch((e) => current && setError((e as ApiError).detail || "Could not load the chat."));
    return () => {
      current = false;
    };
  }, [cspId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Bring the quoted message into view once the chat is there.
  useEffect(() => {
    if (chat && highlight) {
      document.getElementById("csp-chat-highlight")?.scrollIntoView({ block: "center" });
    }
  }, [chat, highlight]);

  // A sent quote may be shortened ("…" dropped), so the start must match.
  const norm = (t: string) => t.trim().replace(/\s+/g, " ");
  const marked = (text: string) =>
    !!highlight && !!norm(highlight) && norm(text).startsWith(norm(highlight));

  const body = (
      <aside className={inline
        ? "w-full h-full overflow-y-auto bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700"
        : "relative w-full max-w-2xl h-full overflow-y-auto bg-white dark:bg-gray-800 shadow-xl pb-[env(safe-area-inset-bottom)]"}>
        <div className={`sticky top-0 z-10 flex items-start justify-between gap-4 px-4 sm:px-6 py-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 ${inline ? "" : "pt-[calc(1rem+env(safe-area-inset-top))] sm:pt-4"}`}>
          <div className="flex items-start min-w-0">
            {!inline && (
              <button onClick={onClose} aria-label="Back" className="sm:hidden -ml-2 mr-1 px-2 text-gray-500 dark:text-gray-300">
              <i className="fas fa-arrow-left"></i>
            </button>
            )}
          <div className="min-w-0">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">
              {cspId} {chat?.csp_name ? `· ${chat.csp_name}` : ""}
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              WhatsApp chat{chat?.phones.length ? ` · ${chat.phones.join(", ")}` : ""}
            </p>
          </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-xl"
          >
            <i className="fas fa-xmark"></i>
          </button>
        </div>

        <div className="px-4 sm:px-6 py-5 space-y-3">
          {error && (
            <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
              {error}
            </div>
          )}
          {!chat && !error && <p className="text-sm text-gray-500">Loading the chat…</p>}
          {chat?.error && <p className="text-sm text-red-600 dark:text-red-400">{chat.error}</p>}
          {chat && !chat.error && chat.items.length === 0 && (
            <p className="text-sm text-gray-500">Nothing in the chat yet.</p>
          )}
          {chat && chat.items.length > 0 && (
            <div className="space-y-2 rounded-lg bg-gray-50 dark:bg-gray-900/40 p-3">
              {chat.items.map((c, i) => {
                const hit = c.from === "csp" && marked(c.text);
                return (
                  <div
                    key={i}
                    id={hit ? "csp-chat-highlight" : undefined}
                    className={`flex ${c.from === "us" ? "justify-end" : "justify-start"}`}
                  >
                    <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                      c.from === "us"
                        ? "bg-green-100 text-gray-900 dark:bg-green-900/40 dark:text-gray-100"
                        : c.automatic
                          ? "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400 border border-dashed border-gray-300 dark:border-gray-600"
                          : "bg-white text-gray-900 dark:bg-gray-700 dark:text-gray-100 border border-gray-200 dark:border-gray-600"
                    } ${hit ? "ring-2 ring-eko" : ""}`}>
                      {c.automatic && (
                        <div className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-1">
                          Automatic reply — not counted as a response
                        </div>
                      )}
                      <div className="whitespace-pre-wrap break-words">
                        {c.text || <span className="italic">({c.type})</span>}
                      </div>
                      <div className="text-xs text-gray-500 mt-1 text-right">
                        {c.from === "us" ? "Sent by us · " : ""}{when(c.at)}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </aside>
  );
  if (inline) return body;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose}></div>
      {body}
    </div>
  );
}
