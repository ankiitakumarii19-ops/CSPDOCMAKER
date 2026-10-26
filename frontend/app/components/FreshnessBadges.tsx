"use client";

import { useEffect, useState } from "react";

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
 * When each sheet the app reads was last read fully, as small chips in the
 * header (No. 146): green on time, amber late, red failed or stuck (runs
 * that start but never finish — the 22–23 Oct sync, No. 144), grey never.
 * Hover for the details. Refreshed every minute.
 */
export default function FreshnessBadges() {
  const [badges, setBadges] = useState<FreshnessBadge[] | null>(null);
  const [error, setError] = useState("");

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

  if (error)
    return (
      <span
        className="hidden lg:inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
        title={error}
      >
        <i className="fas fa-circle-exclamation"></i> Sync status unavailable
      </span>
    );
  if (!badges) return null;

  return (
    <div className="hidden lg:flex items-center gap-2">
      {badges.map((b) => {
        const look = LOOK[b.status];
        return (
          <span
            key={b.source}
            title={explain(b)}
            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium whitespace-nowrap ${look.chip}`}
          >
            <span className={`w-2 h-2 rounded-full ${look.dot}`}></span>
            {b.label}
            <span className="font-normal opacity-80">
              {look.word || ago(b.minutes_since_success)}
            </span>
          </span>
        );
      })}
    </div>
  );
}
