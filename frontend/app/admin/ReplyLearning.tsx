"use client";

/**
 * WhatsApp messages → Replies to CSPs → "What the agent learned" (No. 154).
 *
 * For the week of drafts before going automatic: per kind of reply, how
 * often the agent's draft was sent as it was, changed or skipped, and the
 * changes people made most — "Use this wording" makes one the agent's
 * wording from then on (its Knowledge Base entry).
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, ReplyLearning as Learning } from "../lib/api";

export default function ReplyLearning({ version }: { version: number }) {
  const [data, setData] = useState<Learning | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => {
    api
      .replyLearning()
      .then((r) => {
        setData(r);
        setError("");
      })
      .catch((e) => setError((e as ApiError).detail || "Could not load what the agent learned."));
  }, [version, done]);

  async function use(intent: string, text: string) {
    try {
      await api.useReplyWording(intent, text);
      setDone(`${intent}:${text}`);
    } catch (e) {
      setError((e as ApiError).detail || "Could not change the wording.");
    }
  }

  const pct = (v: number | null) => (v === null ? "—" : `${v}%`);

  return (
    <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-900/30">
      <button onClick={() => setOpen(!open)} className="text-sm text-gray-700 dark:text-gray-200 font-medium">
        <i className={`fas fa-chevron-${open ? "down" : "right"} mr-2 text-xs`}></i>
        What the agent learned (last {data?.days ?? 30} days):{" "}
        <span className="font-normal text-gray-500">
          {data
            ? `${data.sent} sent — ${pct(data.unchanged_rate)} exactly as drafted, ${data.edited} changed, ${data.skipped} skipped`
            : "…"}
        </span>
      </button>
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {open && data && (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="py-1 pr-4">Kind of message</th>
                <th className="py-1 pr-4 text-right">Sent as drafted</th>
                <th className="py-1 pr-4 text-right">Changed</th>
                <th className="py-1 pr-4 text-right">Skipped</th>
                <th className="py-1">Your most common changes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {data.kinds.map((k) => (
                <tr key={k.key} className="align-top">
                  <td className="py-2 pr-4 text-gray-900 dark:text-white">{k.label || k.key}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {k.unchanged} <span className="text-gray-400">({pct(k.unchanged_rate)})</span>
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {k.edited}
                    {k.avg_distance !== null && (
                      <div className="text-[11px] text-gray-400">~{k.avg_distance} chars</div>
                    )}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">{k.skipped}</td>
                  <td className="py-2">
                    {k.suggested.length === 0 && <span className="text-gray-400">—</span>}
                    {k.suggested.map((s, i) => (
                      <div key={i} className="mb-1">
                        <span className="text-gray-700 dark:text-gray-300">&ldquo;{s.text}&rdquo;</span>
                        <span className="text-xs text-gray-400"> ×{s.times}</span>
                        {k.can_use && k.intents.length === 1 && (
                          <button
                            onClick={() => use(k.intents[0], s.text)}
                            className="ml-2 px-2 py-0.5 rounded text-xs font-semibold text-eko hover:bg-eko/10"
                          >
                            Use this wording
                          </button>
                        )}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
              {data.kinds.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-3 text-gray-500">
                    Nothing sent or skipped yet — this fills in as you handle the drafts.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-gray-500">
            {"{rm}"}, {"{email}"} and {"{date}"} in a wording are filled in for each CSP. When most kinds
            are sent as drafted, it is safe to switch to Automatic.
          </p>
        </div>
      )}
    </div>
  );
}
