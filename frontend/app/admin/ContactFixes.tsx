"use client";

/**
 * Data quality → Loop 2: contact fixes (tracker No. 150).
 *
 * A WhatsApp that did not reach the phone, or an email that bounced: the
 * CSP is asked for the right number / address on the other channel (once),
 * and what failed is sent again when it is corrected. Read-only: the
 * contact-loop job does the work every 30 minutes, 8 am – 8 pm.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, ContactFixRow } from "../lib/api";

const STATUS: Record<ContactFixRow["status"], { label: string; cls: string }> = {
  open: { label: "Not asked yet", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  asked: { label: "Asked — waiting", cls: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
  corrected: { label: "Corrected — sending again", cls: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
  resent: { label: "Fixed and sent again", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  done: { label: "Fixed", cls: "bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
  stopped: { label: "Stopped", cls: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
};

const FAILED: Record<string, string> = {
  documents: "Documents email",
  documents_ready: "'Documents ready' WhatsApp",
  data_request: "Details request",
  missing_data: "'Details still needed'",
  details_request: "Details request (email)",
  chat: "Chat message",
};

function when(iso: string | null) {
  return iso
    ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "";
}

export default function ContactFixes({ version }: { version: number }) {
  const [rows, setRows] = useState<ContactFixRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .contactFixes()
      .then((r) => {
        setRows(r.fixes);
        setError("");
      })
      .catch((e) => setError((e as ApiError).detail || "Could not load the contact fixes."));
  }, [version]);

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
        <h3 className="font-semibold text-gray-900 dark:text-white">
          Loop 2 — contact fixes{" "}
          <span className="text-sm font-normal text-gray-500">({rows?.length ?? 0})</span>
        </h3>
        <p className="text-xs text-gray-500">
          A WhatsApp that did not reach the phone, or an email that bounced. The CSP is asked for
          the right number or email on the other channel — once — and what failed is sent again when
          it is corrected. Checked every 30 minutes, 8 am – 8 pm; nothing goes to a CSP on hold, and
          emails wait while they are paused.
        </p>
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-5 py-2">CSP</th>
              <th className="px-5 py-2">Problem</th>
              <th className="px-5 py-2">What did not arrive</th>
              <th className="px-5 py-2">State</th>
              <th className="px-5 py-2">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {rows?.map((f) => (
              <tr key={`${f.csp_id}:${f.problem}:${f.bad_value}`} className="align-top">
                <td className="px-5 py-2">
                  <div className="text-gray-900 dark:text-white">{f.csp_name || "—"}</div>
                  <div className="text-xs font-mono text-gray-500">{f.csp_id}</div>
                </td>
                <td className="px-5 py-2">
                  <div className="text-gray-900 dark:text-white">{f.problem_label}</div>
                  <div className="text-xs font-mono text-gray-500 break-all">{f.bad_value}</div>
                </td>
                <td className="px-5 py-2 text-gray-600 dark:text-gray-300">
                  {FAILED[f.failed_kind] ?? f.failed_kind}
                </td>
                <td className="px-5 py-2 whitespace-nowrap">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${STATUS[f.status].cls}`}>
                    {STATUS[f.status].label}
                  </span>
                </td>
                <td className="px-5 py-2 text-xs text-gray-500">
                  {f.asked_via && (
                    <div>
                      Asked by {f.asked_via} {when(f.asked_at)}
                    </div>
                  )}
                  {f.corrected_value && <div>Corrected to {f.corrected_value}</div>}
                  {f.resent_at && <div>Sent again {when(f.resent_at)}</div>}
                  {f.note && <div>{f.note}</div>}
                </td>
              </tr>
            ))}
            {rows && rows.length === 0 && !error && (
              <tr>
                <td colSpan={5} className="px-5 py-6 text-sm text-gray-500">
                  No bad numbers or bounced emails found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
