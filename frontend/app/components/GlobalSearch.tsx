"use client";

/**
 * The header's search, on every page (No. 175). Ctrl+K (⌘K) or a click
 * opens it; it searches CSP name, code, phone, email, district, state and
 * RM the one way every search box matches, and shows the results grouped:
 * CSPs, documents, chats, action items. A click opens the item itself — the
 * CSP (onOpenCsp, by the page), the PDF, the WhatsApp chat, the card.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import ActionRequiredDetail from "./ActionRequiredDetail";
import CspChat from "../admin/CspChat";
import { api } from "../lib/api";
import type { ApiError, GlobalSearchResult } from "../lib/api";

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "";
}

export default function GlobalSearch({
  onOpenCsp,
}: {
  /** Open this CSP the way the page does (admin: summary; RM: the card). */
  onOpenCsp: (cspId: string, canAct: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [result, setResult] = useState<GlobalSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [chat, setChat] = useState<string | null>(null);
  const [card, setCard] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Ctrl+K / ⌘K from anywhere; Escape closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  // A moment after the last key; only the newest answer is shown.
  useEffect(() => {
    const text = q.trim();
    if (text.length < 2) return;
    let current = true;
    const timer = setTimeout(() => {
      setSearching(true);
      api
        .globalSearch(text)
        .then((r) => current && (setResult(r), setError("")))
        .catch((e) => current && setError((e as ApiError).detail || "Search failed."))
        .finally(() => current && setSearching(false));
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [q]);

  const openPdf = useCallback(async (cspId: string, id: string) => {
    try {
      const blob = await api.databaseFile(cspId, `documents/${id}`);
      window.open(URL.createObjectURL(blob), "_blank", "noopener");
    } catch (e) {
      setError((e as ApiError).detail || "Could not open the document.");
    }
  }, []);

  const go = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  const short = q.trim().length < 2;
  const empty = result && !short &&
    !result.csps.length && !result.documents.length && !result.chats.length && !result.action_items.length;
  const head = "px-4 pt-3 pb-1 text-xs font-bold uppercase tracking-wider text-gray-500";
  const item = "w-full text-left px-4 py-2 hover:bg-gray-50 dark:hover:bg-gray-700/50";

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 w-full max-w-xs px-3 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-900 text-sm text-gray-400 hover:border-eko"
        title="Search everything (Ctrl+K)"
      >
        <i className="fas fa-search text-xs"></i>
        <span className="flex-1 text-left truncate hidden sm:inline">Search CSPs, documents, chats…</span>
        <kbd className="hidden md:inline text-xs px-1.5 py-0.5 rounded border border-gray-300 dark:border-gray-600">Ctrl K</kbd>
      </button>

      {/* On <body>, not inside the header (No. 176): the header is its own
          layer, so a panel opened inside it sat under the chat button. */}
      {open && createPortal(
        <div
          className="fixed inset-0 z-[60] bg-black/40 flex items-start justify-center sm:p-4"
          onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}
          role="dialog"
          aria-modal="true"
        >
          {/* Full screen on a phone (No. 176), a box from sm up. */}
          <div className="w-full max-w-2xl h-dvh sm:h-auto sm:mt-16 flex flex-col bg-white dark:bg-gray-800 sm:rounded-xl shadow-xl sm:border border-gray-200 dark:border-gray-700 overflow-hidden pt-[env(safe-area-inset-top)] sm:pt-0">
            <div className="flex items-center gap-3 px-4 border-b border-gray-200 dark:border-gray-700 shrink-0">
              <button onClick={() => setOpen(false)} className="sm:hidden -ml-2 px-2 text-gray-500" aria-label="Back">
                <i className="fas fa-arrow-left"></i>
              </button>
              <i className="fas fa-search text-gray-400"></i>
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Name, CSP code, phone, email, district, state or RM"
                type="search"
                enterKeyHint="search"
                className="flex-1 min-w-0 py-3 bg-transparent outline-none text-gray-900 dark:text-white"
              />
              {searching && <i className="fas fa-circle-notch fa-spin text-gray-400"></i>}
              <button onClick={() => setOpen(false)} className="hidden sm:block text-xs text-gray-500 hover:underline">Esc</button>
            </div>
            <div className="flex-1 sm:flex-none sm:max-h-[60vh] overflow-y-auto pb-[calc(0.5rem+env(safe-area-inset-bottom))]">
              {error && <p className="px-4 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
              {short && <p className="px-4 py-3 text-sm text-gray-500">Type at least two letters or digits.</p>}
              {empty && <p className="px-4 py-3 text-sm text-gray-500">No CSP found for &quot;{q.trim()}&quot;.</p>}
              {result && !short && (
                <>
                  {result.csps.length > 0 && <div className={head}>CSPs</div>}
                  {result.csps.map((c) => (
                    <button key={c.csp_id} className={item} onClick={() => go(() => onOpenCsp(c.csp_id, c.can_act))}>
                      <div className="flex justify-between gap-3 text-sm">
                        <span className="font-medium text-gray-900 dark:text-white truncate">{c.name || c.csp_id}</span>
                        <span className="font-mono text-xs text-gray-500">{c.csp_id}</span>
                      </div>
                      <div className="text-xs text-gray-500 truncate">
                        {[c.district, c.state, c.mobile, c.rm_name && `RM ${c.rm_name}`].filter(Boolean).join(" · ")}
                        {!c.can_act && " · view only"}
                      </div>
                    </button>
                  ))}
                  {result.documents.length > 0 && <div className={head}>Documents</div>}
                  {result.documents.map((d) => (
                    <button key={d.id} className={item} onClick={() => go(() => openPdf(d.csp_id, d.id))}>
                      <span className="text-sm text-gray-900 dark:text-white">
                        <i className="fas fa-file-pdf text-red-500 mr-2"></i>
                        {d.label}{d.version > 1 ? ` (v${d.version})` : ""} — {d.name || d.csp_id}
                      </span>
                      <span className="ml-2 text-xs text-gray-500">{d.csp_id} · {when(d.created_at)}</span>
                    </button>
                  ))}
                  {result.chats.length > 0 && <div className={head}>Chats</div>}
                  {result.chats.map((c) => (
                    <button key={c.csp_id} className={item} onClick={() => go(() => setChat(c.csp_id))}>
                      <div className="text-sm text-gray-900 dark:text-white">
                        <i className="fab fa-whatsapp text-green-600 mr-2"></i>{c.name || c.csp_id}
                        <span className="ml-2 font-mono text-xs text-gray-500">{c.csp_id}</span>
                      </div>
                      <div className="text-xs text-gray-500 truncate">{c.snippet}</div>
                    </button>
                  ))}
                  {result.action_items.length > 0 && <div className={head}>Action items</div>}
                  {result.action_items.map((a) => (
                    <button key={a.id} className={item} onClick={() => go(() => setCard(a.id))}>
                      <div className="text-sm text-gray-900 dark:text-white">
                        <i className={`fas ${a.status === "fixed" ? "fa-check-circle text-green-600" : "fa-exclamation-triangle text-orange-500"} mr-2`}></i>
                        {a.name} <span className="ml-1 font-mono text-xs text-gray-500">{a.csp_id}</span>
                      </div>
                      <div className="text-xs text-gray-500 truncate">
                        {a.status === "fixed" ? "Fixed — was missing" : "Missing"}: {a.missing.join(", ")}
                      </div>
                    </button>
                  ))}
                </>
              )}
            </div>
          </div>
        </div>
      , document.body)}
      {chat && createPortal(<CspChat cspId={chat} onClose={() => setChat(null)} />, document.body)}
      {card && createPortal(<ActionRequiredDetail id={card} onClose={() => setCard(null)} />, document.body)}
    </>
  );
}
