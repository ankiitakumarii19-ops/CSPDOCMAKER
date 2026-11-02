"use client";

/**
 * Action Required → History (No. 174): every card, pending or fixed. A
 * fixed one says when and how its details were filled (the CSP's reply, a
 * sheet edit, the verification agent…). Filter Fixed / Pending / All and
 * search by name, CSP code, phone or email; a row opens the card.
 */

import { useEffect, useState } from "react";

import ActionRequiredDetail from "./ActionRequiredDetail";
import { api } from "../lib/api";
import type { ActionItem, ApiError } from "../lib/api";

function when(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : "—";
}

export default function ActionHistory({
  onClose,
  onWorkOn,
}: {
  onClose: () => void;
  onWorkOn?: (cspId: string) => void;
}) {
  const [show, setShow] = useState<"all" | "fixed" | "pending">("fixed");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ActionItem[] | null>(null);
  const [error, setError] = useState("");
  const [opened, setOpened] = useState<string | null>(null);

  // Searching as you type, a moment after the last key.
  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    let current = true;
    api
      .alertHistory(show, query)
      .then((r) => current && (setItems(r.items), setError("")))
      .catch((e) => current && setError((e as ApiError).detail || "Could not load the history."));
    return () => {
      current = false;
    };
  }, [show, query]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !opened && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, opened]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose}></div>
      <aside className="relative w-full max-w-2xl h-full overflow-y-auto bg-white dark:bg-gray-800 shadow-xl pb-[env(safe-area-inset-bottom)]">
        <div className="sticky top-0 z-10 px-4 sm:px-6 py-4 pt-[calc(1rem+env(safe-area-inset-top))] sm:pt-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 space-y-3">
          <div className="flex items-start justify-between">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">Action Required — History</h3>
            <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-xl">
              <i className="fas fa-xmark"></i>
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {(["fixed", "pending", "all"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setShow(s)}
                className={`px-3 py-1 rounded-lg text-xs font-medium ${
                  show === s ? "bg-eko/10 text-eko" : "text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700"}`}
              >
                {s === "fixed" ? "Fixed" : s === "pending" ? "Pending" : "All"}
              </button>
            ))}
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name, CSP code, phone or email"
              className="flex-1 min-w-[12rem] px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm dark:text-white"
            />
          </div>
        </div>

        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {error && <p className="px-6 py-4 text-sm text-red-600 dark:text-red-400">{error}</p>}
          {!items && !error && <p className="px-6 py-4 text-sm text-gray-500">Loading…</p>}
          {items?.length === 0 && <p className="px-6 py-6 text-sm text-gray-500">Nothing here.</p>}
          {items?.map((it) => (
            <button
              key={it.id}
              onClick={() => setOpened(it.id)}
              className="w-full text-left px-6 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/40"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-sm text-gray-900 dark:text-white">{it.name}</span>
                <span className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${
                    it.status === "fixed"
                      ? "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                      : "bg-orange-50 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300"}`}>
                    {it.status === "fixed" ? "Fixed" : "Pending"}
                  </span>
                  <span className="text-xs font-mono text-gray-500">{it.csp_id}</span>
                </span>
              </div>
              <div className="text-xs text-gray-500 mt-0.5">
                {it.status === "fixed" ? "Was missing" : "Missing"}: {it.missing.join(", ") || "—"}
              </div>
              <div className="text-xs text-gray-500">
                Flagged {when(it.flagged_at)}
                {it.status === "fixed" && (
                  <> · Fixed {when(it.fixed_at)} by <span className="text-gray-700 dark:text-gray-300">{it.fixed_note || it.fixed_via_label}</span></>
                )}
              </div>
            </button>
          ))}
        </div>
      </aside>
      {opened && (
        <ActionRequiredDetail id={opened} onClose={() => setOpened(null)} onWorkOn={onWorkOn} />
      )}
    </div>
  );
}
