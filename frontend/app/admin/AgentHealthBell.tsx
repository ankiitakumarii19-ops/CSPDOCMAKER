"use client";

/**
 * The Admin header's bell (No. 252): open Agent health issues.
 *
 * A count on the bell (with the word "issues" for screen readers), a short
 * list when opened, and a link to Agent health. Refreshed every 2 minutes.
 * Shown only to people with the Agents feature (the Super Admin by default).
 */

import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type { AgentIssue } from "../lib/api";

export default function AgentHealthBell({ onOpen }: { onOpen: () => void }) {
  const [issues, setIssues] = useState<AgentIssue[]>([]);
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .agentHealthIssues("open")
        .then((r) => {
          if (!alive) return;
          setIssues(r.issues);
          setFailed(false);
        })
        // Shown on the bell as "could not check", never hidden.
        .catch(() => alive && setFailed(true));
    tick();
    const t = setInterval(tick, 120_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const critical = issues.some((i) => i.severity === "critical");
  const n = issues.length;

  return (
    <div className="relative" ref={box}>
      <button
        onClick={() => setOpen(!open)}
        className="relative text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 p-1"
        aria-label={failed ? "Agent health: could not check" : `Agent health: ${n} open issue${n === 1 ? "" : "s"}`}
        title="Agent health"
      >
        <i className="far fa-bell text-lg"></i>
        {n > 0 && (
          <span
            className={`absolute -top-1 -right-1 min-w-[1.1rem] h-[1.1rem] px-1 rounded-full text-[0.7rem] leading-[1.1rem] font-bold text-white text-center ${
              critical ? "bg-red-600" : "bg-amber-500"
            }`}
          >
            {n > 9 ? "9+" : n}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-9 w-80 max-w-[calc(100vw-2rem)] bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 z-50">
          <div className="px-4 py-2 border-b border-gray-100 dark:border-gray-700 text-sm font-semibold text-gray-900 dark:text-white">
            Agent health
          </div>
          <div className="max-h-80 overflow-y-auto">
            {failed && <p className="px-4 py-3 text-sm text-red-600">Could not check just now.</p>}
            {!failed && n === 0 && (
              <p className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
                <i className="fas fa-check-circle text-green-600 mr-2" aria-hidden="true"></i>
                No open issues.
              </p>
            )}
            {issues.slice(0, 8).map((i) => (
              <div key={i.id} className="px-4 py-2 border-b border-gray-50 dark:border-gray-700/50 text-sm">
                <span className={i.severity === "critical" ? "text-red-700 dark:text-red-300" : "text-amber-700 dark:text-amber-300"}>
                  <i className={`fas ${i.severity === "critical" ? "fa-times-circle" : "fa-exclamation-triangle"} mr-1`} aria-hidden="true"></i>
                  {i.severity === "critical" ? "Critical" : "Warning"}:
                </span>{" "}
                <span className="text-gray-800 dark:text-gray-200">{i.title}</span>
              </div>
            ))}
          </div>
          <button
            onClick={() => {
              setOpen(false);
              onOpen();
            }}
            className="w-full text-left px-4 py-2 text-sm text-eko hover:bg-gray-50 dark:hover:bg-gray-700 rounded-b-lg"
          >
            Open Agent health →
          </button>
        </div>
      )}
    </div>
  );
}
