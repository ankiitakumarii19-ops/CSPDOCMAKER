"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import CspPhoto from "../components/CspPhoto";
import { api } from "../lib/api";
import type { ApiError, CSPDetail } from "../lib/api";

type Summary = Awaited<ReturnType<typeof api.cspSummary>>;

const DELIVERY: Record<string, { text: string; className: string }> = {
  mailed: {
    text: "Mailed",
    className: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
  },
  failed: {
    text: "Failed",
    className: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  },
  pending: {
    text: "Pending",
    className: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
  },
  not_for_this_csp: {
    text: "Not for this CSP",
    className: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300",
  },
};

function day(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/**
 * The admin top-bar search (No. 101). It used to keep what was typed and
 * search nothing. Now: matching CSPs drop down as you type (or on Enter),
 * and choosing one opens a read-only panel — the CSP's details and where
 * each document stands, counted the way the dashboard counts.
 */
export default function CspSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CSPDetail[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  const [selected, setSelected] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryError, setSummaryError] = useState("");

  const boxRef = useRef<HTMLDivElement | null>(null);
  // Only the newest search may fill the list: typing fires several, and an
  // older answer arriving last must not replace a newer one.
  const latest = useRef(0);

  const run = useCallback(async (text: string) => {
    const mine = ++latest.current;
    setSearching(true);
    setError("");
    setOpen(true);
    try {
      const res = await api.searchCSP(text);
      if (mine === latest.current) setResults(res.results);
    } catch (e) {
      if (mine === latest.current) {
        setResults(null);
        setError((e as ApiError).detail || "Search failed.");
      }
    } finally {
      if (mine === latest.current) setSearching(false);
    }
  }, []);

  // Search as they type, once there is enough to narrow it down.
  useEffect(() => {
    const text = query.trim();
    if (text.length < 3) return;
    const timer = setTimeout(() => run(text), 300);
    return () => clearTimeout(timer);
  }, [query, run]);

  // A click anywhere else closes the list.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const close = () => {
    setSelected(null);
    setSummary(null);
    setSummaryError("");
  };

  const choose = async (cspId: string) => {
    setOpen(false);
    setSelected(cspId);
    setSummary(null);
    setSummaryError("");
    try {
      setSummary(await api.cspSummary(cspId));
    } catch (e) {
      setSummaryError((e as ApiError).detail || "Could not open this CSP.");
    }
  };

  const text = query.trim();
  const csp = summary?.csp;

  return (
    <>
      <div ref={boxRef} className="relative w-full hidden sm:block">
        <i className="fas fa-search absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 text-sm"></i>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => text && (results || error) && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && text) run(text);
            if (e.key === "Escape") setOpen(false);
          }}
          className="w-full pl-9 pr-4 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-900 focus:ring-1 focus:ring-eko dark:text-white outline-none text-sm"
          placeholder="Global search CSP ID..."
        />

        {open && text && (
          <div className="absolute left-0 right-0 top-full mt-1 z-40 max-h-80 overflow-y-auto bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg">
            {searching && !results && (
              <p className="px-4 py-3 text-sm text-gray-500">Searching…</p>
            )}
            {error && (
              <p className="px-4 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>
            )}
            {!error && results && results.length === 0 && !searching && (
              <p className="px-4 py-3 text-sm text-gray-500">
                No CSP found for &quot;{text}&quot;. Try the code or part of the name.
              </p>
            )}
            {!error &&
              results?.map((r) => (
                <button
                  key={r.csp_id}
                  type="button"
                  onClick={() => choose(r.csp_id)}
                  className="w-full text-left px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-700/50 border-b last:border-b-0 border-gray-100 dark:border-gray-700"
                >
                  <div className="flex justify-between gap-3">
                    <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {r.name}
                    </span>
                    <span className="text-xs text-gray-500 shrink-0">{r.csp_id}</span>
                  </div>
                  <div className="text-xs text-gray-500 truncate">
                    {[r.district, r.state].filter(Boolean).join(", ") || "—"}
                    {" · RM "}
                    {r.rm_name || "unassigned"}
                  </div>
                </button>
              ))}
          </div>
        )}
      </div>

      {selected && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-4 overflow-y-auto"
          onMouseDown={(e) => e.target === e.currentTarget && close()}
          onKeyDown={(e) => e.key === "Escape" && close()}
        >
          <div className="w-full max-w-2xl mt-12 bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
              <h2 className="font-bold text-gray-900 dark:text-white">
                {csp ? csp.name : selected}
                <span className="ml-2 text-sm font-normal text-gray-500">{selected}</span>
                {csp && (
                  <span className="ml-2 px-2 py-0.5 text-[10px] uppercase tracking-wider rounded font-bold bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                    {csp.origin === "new" ? "New" : "Existing"}
                  </span>
                )}
              </h2>
              <button
                autoFocus
                onClick={close}
                className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              >
                <i className="fas fa-xmark"></i> Close
              </button>
            </div>

            {summaryError && (
              <p className="px-5 py-4 text-sm text-red-600 dark:text-red-400">
                <i className="fas fa-circle-exclamation mr-2"></i>
                {summaryError}
              </p>
            )}
            {!summary && !summaryError && (
              <p className="px-5 py-8 text-center text-sm text-gray-500">Loading…</p>
            )}

            {csp && summary && (
              <>
                <div className="px-5 pt-4 flex items-center gap-4">
                  <CspPhoto cspId={csp.csp_id} />
                  <p className="text-xs text-gray-500">
                    Passport-size photo, as printed on the documents.
                  </p>
                </div>
                <dl className="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
                  {[
                    ["Branch", [csp.branch_name, csp.branch_code].filter(Boolean).join(", ")],
                    ["Location", [csp.district, csp.state].filter(Boolean).join(", ")],
                    ["LHO", csp.lho],
                    ["AO", csp.ao],
                    ["Mobile", csp.mobile],
                    ["Email", csp.email],
                    ["DC", csp.dc],
                    ["ASM", csp.asm_name],
                    ["Assigned RM", csp.rm_name],
                  ].map(([label, value]) => (
                    <div key={label as string} className="flex justify-between gap-3">
                      <dt className="text-gray-500">{label}</dt>
                      <dd className="text-gray-900 dark:text-white text-right break-all">
                        {value || <span className="text-gray-400">—</span>}
                      </dd>
                    </div>
                  ))}
                </dl>

                <table className="w-full text-left border-collapse border-t border-gray-200 dark:border-gray-700">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-900/50 text-gray-500 text-xs uppercase tracking-wider">
                      <th className="px-5 py-2.5 font-semibold">Document</th>
                      <th className="px-5 py-2.5 font-semibold">Made</th>
                      <th className="px-5 py-2.5 font-semibold">Delivery</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {summary.documents.map((d) => (
                      <tr key={d.document_type}>
                        <td className="px-5 py-2.5 text-sm font-medium text-gray-900 dark:text-white">
                          {d.label}
                        </td>
                        <td className="px-5 py-2.5 text-sm text-gray-600 dark:text-gray-300">
                          {d.generated
                            ? `${day(d.generated_at)}${d.version && d.version > 1 ? ` (v${d.version})` : ""}`
                            : d.applies
                            ? "Not yet"
                            : "—"}
                        </td>
                        <td className="px-5 py-2.5">
                          <span
                            className={`px-2 py-0.5 text-xs rounded font-medium ${DELIVERY[d.delivery].className}`}
                          >
                            {DELIVERY[d.delivery].text}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
