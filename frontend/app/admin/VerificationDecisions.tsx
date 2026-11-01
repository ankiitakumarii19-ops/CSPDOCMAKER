"use client";

/**
 * Agents → "Decided automatically" (No. 171). The verification agent no
 * longer asks: when what a CSP sent differs from the record, the newest
 * value wins. Every decision is listed here with the CSP's answer, the old
 * and new value, why and when — to check later, nothing to approve.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, VerificationDecision } from "../lib/api";

const KIND: Record<string, { label: string; cls: string }> = {
  wrote_answer: {
    label: "CSP's answer written to the sheet",
    cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300",
  },
  kept_sheet: {
    label: "Sheet's newer value kept",
    cls: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
  },
};

export default function VerificationDecisions({ version = 0 }: { version?: number }) {
  const [rows, setRows] = useState<VerificationDecision[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .verificationDecisions()
      .then((r) => {
        setRows(r.decisions);
        setError("");
      })
      .catch((e) => setError((e as ApiError).detail || "Could not load the decisions."));
  }, [version]);

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
        <h3 className="font-semibold text-gray-900 dark:text-white">
          Decided automatically — verification agent
        </h3>
        <p className="text-xs text-gray-500">
          When what a CSP sent differs from the record, the newest value wins. A difference only in
          capitals, spaces or leading zeros is not counted. Nothing waits for you; this is the log.
        </p>
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {rows?.length === 0 && (
        <p className="px-5 py-4 text-sm text-gray-500">Nothing decided yet.</p>
      )}
      {rows && rows.length > 0 && (
        <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-gray-500 sticky top-0 bg-white dark:bg-gray-800">
              <tr>
                <th className="px-5 py-2">When</th>
                <th className="px-5 py-2">CSP</th>
                <th className="px-5 py-2">Field</th>
                <th className="px-5 py-2">CSP sent</th>
                <th className="px-5 py-2">Old value</th>
                <th className="px-5 py-2">New value</th>
                <th className="px-5 py-2">Decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {rows.map((r, i) => (
                <tr key={i} className="align-top" title={r.why ?? ""}>
                  <td className="px-5 py-2 text-gray-500 whitespace-nowrap">
                    {r.at ? new Date(r.at).toLocaleString("en-IN", {
                      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
                    }) : "—"}
                  </td>
                  <td className="px-5 py-2 font-mono text-gray-900 dark:text-white">{r.csp_id}</td>
                  <td className="px-5 py-2 text-gray-700 dark:text-gray-300">{r.label ?? r.field}</td>
                  <td className="px-5 py-2 text-gray-600 dark:text-gray-300 break-all">{r.csp_answered}</td>
                  <td className="px-5 py-2 text-gray-600 dark:text-gray-300 break-all">{r.old_value}</td>
                  <td className="px-5 py-2 text-gray-900 dark:text-white break-all">{r.new_value}</td>
                  <td className="px-5 py-2">
                    {r.decision && KIND[r.decision] && (
                      <span className={`px-2 py-0.5 rounded-full text-xs whitespace-nowrap ${KIND[r.decision].cls}`}>
                        {KIND[r.decision].label}
                      </span>
                    )}
                    {r.why && <div className="text-xs text-gray-500 mt-1 max-w-xs">{r.why}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
