"use client";

/**
 * Data quality → Context (tracker No. 146): every sheet the app reads, when
 * it was last read fully, how often it should be, and — for Admins and
 * Super Admins — why the newest read failed. The same data as the header
 * chips, in full.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, FreshnessBadge, FreshnessStatus } from "../lib/api";

const STATE: Record<FreshnessStatus, { label: string; cls: string }> = {
  ok: { label: "On time", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  stale: { label: "Late", cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" },
  stuck: { label: "Stuck", cls: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  failed: { label: "Failed", cls: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
  never: { label: "Never read", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
};

const USED_FOR: Record<string, string> = {
  csp: "Every CSP's details; INFO fills the blanks (AO, RBO, DC, ASM, LHO, State, RM)",
  authorization: "Who may sign in, and as which role",
  source_sheets: "Old CSPs (Calling sheet) and new ones going live (Lead raw data); holds",
  address: "Addresses of old CSPs (temporary tab)",
};

export default function ContextSources() {
  const [badges, setBadges] = useState<FreshnessBadge[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .freshness()
      .then((r) => setBadges(r.sources))
      .catch((e) => setError((e as ApiError).detail || "Could not load the sheets."));
  }, []);

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
        <h3 className="font-semibold text-gray-900 dark:text-white">Context — what the app reads</h3>
        <p className="text-xs text-gray-500">
          The sheets every decision is made from, and when each was last read in full.
        </p>
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-5 py-2">Sheet</th>
              <th className="px-5 py-2">Used for</th>
              <th className="px-5 py-2">Last read in full</th>
              <th className="px-5 py-2">Expected</th>
              <th className="px-5 py-2">State</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {badges?.map((b) => (
              <tr key={b.source}>
                <td className="px-5 py-2 text-gray-900 dark:text-white whitespace-nowrap">{b.label}</td>
                <td className="px-5 py-2 text-gray-600 dark:text-gray-300">{USED_FOR[b.source] ?? ""}</td>
                <td className="px-5 py-2 text-gray-600 dark:text-gray-300 whitespace-nowrap">
                  {b.last_success_at ? new Date(b.last_success_at).toLocaleString("en-IN") : "Never"}
                </td>
                <td className="px-5 py-2 text-gray-500 whitespace-nowrap">
                  every {b.expected_every_minutes} min
                </td>
                <td className="px-5 py-2">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${STATE[b.status].cls}`}>
                    {STATE[b.status].label}
                  </span>
                  {b.status === "stuck" && (
                    <div className="text-xs text-gray-500 mt-1">
                      {b.unfinished_runs} run(s) started but never finished
                    </div>
                  )}
                  {b.error && <div className="text-xs text-red-600 dark:text-red-400 mt-1">{b.error}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
