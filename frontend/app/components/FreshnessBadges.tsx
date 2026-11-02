"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, FreshnessBadge, FreshnessStatus } from "../lib/api";

const LOOK: Record<FreshnessStatus, { dot: string; chip: string; word: string }> = {
  ok: {
    dot: "bg-green-500",
    chip: "bg-green-50 text-green-800 dark:bg-green-900/20 dark:text-green-400",
    word: "",
  },
  stale: {
    dot: "bg-amber-500",
    chip: "bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-400",
    word: "late",
  },
  stuck: {
    dot: "bg-red-500",
    chip: "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400",
    word: "stuck",
  },
  failed: {
    dot: "bg-red-500",
    chip: "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400",
    word: "failed",
  },
  never: {
    dot: "bg-gray-400",
    chip: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300",
    word: "never read",
  },
};

function ago(minutes: number | null) {
  if (minutes === null) return "";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return `${Math.floor(minutes / (24 * 60))} d ago`;
}

function explain(b: FreshnessBadge) {
  const lines = [
    `${b.label}: expected every ${b.expected_every_minutes} min.`,
    b.last_success_at
      ? `Last read fully ${new Date(b.last_success_at).toLocaleString("en-IN")}.`
      : "Never read fully.",
  ];
  if (b.status === "stuck")
    lines.push(`${b.unfinished_runs} run(s) started but never finished.`);
  if (b.status === "failed") lines.push("The newest read failed.");
  if (b.error) lines.push(b.error);
  return lines.join("\n");
}

/**
 * When each sheet the app reads was last read fully (No. 146), as ONE
 * compact indicator in the header (No. 175 — the four chips pushed the tabs
 * and the profile menu off the header): a dot and "All synced", amber when
 * one is late or never read, red when one failed or is stuck. A click opens
 * the list — each sheet and when it was last read, with the reason on hover.
 * Refreshed every minute.
 */
export default function FreshnessBadges() {
  const [badges, setBadges] = useState<FreshnessBadge[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .freshness()
        .then((r) => {
          if (cancelled) return;
          setBadges(r.sources);
          setError("");
        })
        .catch((e) => {
          if (!cancelled) setError((e as ApiError).detail || "Could not load.");
        });
    load();
    const timer = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  // A click anywhere else closes the list.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  if (!badges && !error) return null;

  const red = (badges ?? []).filter((b) => b.status === "failed" || b.status === "stuck");
  const amber = (badges ?? []).filter((b) => b.status === "stale" || b.status === "never");
  const overall: FreshnessStatus = error || red.length ? "failed" : amber.length ? "stale" : "ok";
  const look = LOOK[overall];
  const words = error
    ? "Sync status unavailable"
    : red.length
    ? `${red.length} sheet${red.length === 1 ? "" : "s"} failing`
    : amber.length
    ? `${amber.length} sheet${amber.length === 1 ? "" : "s"} late`
    : "All synced";

  return (
    <div ref={box} className="relative shrink-0">
      <button
        onClick={() => setOpen((o) => !o)}
        title={error || "When each sheet was last read"}
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium whitespace-nowrap ${look.chip}`}
      >
        <span className={`w-2 h-2 rounded-full ${look.dot}`}></span>
        <span className="hidden sm:inline">{words}</span>
        <i className="fas fa-chevron-down text-[9px] opacity-70"></i>
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 w-72 z-50 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg py-1">
          <div className="px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-gray-500">
            Sheets the app reads
          </div>
          {error && <p className="px-3 py-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
          {(badges ?? []).map((b) => {
            const l = LOOK[b.status];
            return (
              <div key={b.source} title={explain(b)} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                <span className={`w-2 h-2 rounded-full shrink-0 ${l.dot}`}></span>
                <span className="flex-1 text-gray-800 dark:text-gray-200">{b.label}</span>
                <span className={`text-xs ${b.status === "ok" ? "text-gray-500" : "font-medium " + l.chip.split(" ").filter((c) => c.startsWith("text-") || c.startsWith("dark:text-")).join(" ")}`}>
                  {l.word ? `${l.word}${b.minutes_since_success !== null ? ` · ${ago(b.minutes_since_success)}` : ""}` : ago(b.minutes_since_success)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
