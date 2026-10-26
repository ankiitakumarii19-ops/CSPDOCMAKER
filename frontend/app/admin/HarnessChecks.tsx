"use client";

/**
 * Data quality → Harness (tracker No. 149): every way the app checks its
 * own work — the auto-fill record, corrections, kept rate, freshness,
 * sending failures, unanswered chat questions, golden cases, tests — and
 * where each stands now. The same list is in the Knowledge Base ("How does
 * the app check itself?").
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, HarnessCheck } from "../lib/api";

const STATE: Record<HarnessCheck["state"], { label: string; cls: string }> = {
  ok: { label: "Working", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  attention: { label: "Needs a look", cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" },
  empty: { label: "No data yet", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  laptop: { label: "Checked before each push", cls: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
};

export default function HarnessChecks({ version }: { version: number }) {
  const [checks, setChecks] = useState<HarnessCheck[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .qualityHarness()
      .then((r) => {
        setChecks(r.checks);
        setError("");
      })
      .catch((e) => setError((e as ApiError).detail || "Could not load the checks."));
  }, [version]);

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
        <h3 className="font-semibold text-gray-900 dark:text-white">Harness — how the app checks itself</h3>
        <p className="text-xs text-gray-500">
          Every check on the app&apos;s own work, and where it stands now.
        </p>
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-5 py-2">Check</th>
              <th className="px-5 py-2">What it watches</th>
              <th className="px-5 py-2">How</th>
              <th className="px-5 py-2">Now</th>
              <th className="px-5 py-2">State</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {checks?.map((c) => (
              <tr key={c.key} className="align-top">
                <td className="px-5 py-2 text-gray-900 dark:text-white whitespace-nowrap">{c.name}</td>
                <td className="px-5 py-2 text-gray-600 dark:text-gray-300">{c.watches}</td>
                <td className="px-5 py-2 text-gray-500">{c.how}</td>
                <td className="px-5 py-2 text-gray-900 dark:text-white">{c.now}</td>
                <td className="px-5 py-2 whitespace-nowrap">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${STATE[c.state].cls}`}>
                    {STATE[c.state].label}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
