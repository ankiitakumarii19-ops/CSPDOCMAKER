"use client";

/**
 * Data quality → Loop 5: feedback after the documents (tracker No. 152).
 *
 * 15 minutes after a CSP's documents WhatsApp they are asked (No. 159): "did you get
 * them? 1 = got them, all correct · 2 = did not get them · 3 = something
 * is wrong". 2 → the documents email again; 3 → the data verification
 * message. The reply goes through "Replies to CSPs" on the WhatsApp page.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, FeedbackSummary } from "../lib/api";

const TILES: [keyof FeedbackSummary["answers"] | "no_answer", string, string][] = [
  ["1", "Got them, all correct", "text-green-700 dark:text-green-400"],
  ["2", "Did not get them", "text-red-600 dark:text-red-400"],
  ["3", "Something is wrong", "text-amber-600 dark:text-amber-400"],
  ["no_answer", "No answer yet", "text-gray-500"],
];

function when(iso: string | null) {
  return iso
    ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "";
}

export default function FeedbackAnswers({ version }: { version: number }) {
  const [data, setData] = useState<FeedbackSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .documentsFeedback()
      .then((r) => {
        setData(r);
        setError("");
      })
      .catch((e) => setError((e as ApiError).detail || "Could not load the feedback."));
  }, [version]);

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700">
        <h3 className="font-semibold text-gray-900 dark:text-white">
          Loop 5 — did CSPs get their documents?{" "}
          <span className="text-sm font-normal text-gray-500">({data?.asked ?? 0} asked)</span>
        </h3>
        <p className="text-xs text-gray-500">
          15 minutes after the documents message, each CSP is asked to reply 1 (got them, all correct),
          2 (did not get them — the documents email is sent again) or 3 (something is wrong — the
          data verification message is sent). The reply to them waits in &quot;Replies to CSPs&quot;
          on the WhatsApp messages page.
        </p>
      </div>
      {error && <p className="px-5 py-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {data && (
        <div className="px-5 py-3 grid grid-cols-2 md:grid-cols-4 gap-3">
          {TILES.map(([key, label, tone]) => (
            <div key={key}>
              <div className={`text-2xl font-bold tabular-nums ${tone}`}>
                {key === "no_answer" ? data.no_answer : data.answers[key]}
              </div>
              <div className="text-xs text-gray-500">{label}</div>
            </div>
          ))}
        </div>
      )}
      {data && data.rows.length > 0 && (
        <div className="overflow-x-auto border-t border-gray-100 dark:border-gray-700">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="px-5 py-2">CSP</th>
                <th className="px-5 py-2">Asked</th>
                <th className="px-5 py-2">Answer</th>
                <th className="px-5 py-2">Note</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {data.rows.map((f, i) => (
                <tr key={`${f.csp_id}:${i}`}>
                  <td className="px-5 py-2">
                    <div className="text-gray-900 dark:text-white">{f.csp_name || "—"}</div>
                    <div className="text-xs font-mono text-gray-500">{f.csp_id}</div>
                  </td>
                  <td className="px-5 py-2 text-gray-500 whitespace-nowrap">
                    {f.ask_status === "sent" ? when(f.asked_at) : f.ask_status}
                  </td>
                  <td className="px-5 py-2 text-gray-900 dark:text-white">
                    {f.answer ? `${f.answer} — ${f.answer_label}` : <span className="text-gray-400">—</span>}
                    {f.answer_text && f.answer_text !== f.answer && (
                      <div className="text-xs text-gray-500">“{f.answer_text}”</div>
                    )}
                  </td>
                  <td className="px-5 py-2 text-xs text-gray-500">{f.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
