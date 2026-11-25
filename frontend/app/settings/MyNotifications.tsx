"use client";

/**
 * Settings → Notifications (No. 240, SaaS upgrade Stage 3)
 *
 * What the app tells THIS person, and how. Only staff notifications: the
 * messages to CSPs follow the workspace's rules and are not here. Must-have
 * ones (sign-in codes, failure alerts, the Action Required bell) show as
 * locked on; channels the app does not use for staff say so.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, NotificationKind } from "../lib/api";

export default function MyNotifications() {
  const [kinds, setKinds] = useState<NotificationKind[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .myNotifications()
      .then((v) => alive && setKinds(v.notifications))
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load your notifications."));
    return () => {
      alive = false;
    };
  }, []);

  async function flip(kind: string, channel: string, on: boolean) {
    if (!kinds) return;
    const off: Record<string, Record<string, boolean>> = {};
    for (const k of kinds) {
      for (const c of k.channels) {
        const value = k.key === kind && c.key === channel ? on : c.on;
        if (c.available && !c.locked && value === false) (off[k.key] ||= {})[c.key] = false;
      }
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const v = await api.saveNotifications(off);
      setKinds(v.notifications);
      setMessage("Saved. Only your own notifications changed.");
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Your notifications</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          What the app tells you, and how. Messages to CSPs are not here — they follow your workspace&apos;s rules.
        </p>
      </div>
      {error && (
        <div role="alert" className="text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
          {error}
        </div>
      )}
      {message && (
        <div role="status" className="text-sm text-eko-dark dark:text-eko bg-eko-light dark:bg-eko/10 rounded-lg px-3 py-2">
          {message}
        </div>
      )}
      {!kinds && !error && (
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 animate-pulse" />
          ))}
        </div>
      )}
      {kinds?.map((k) => (
        <section key={k.key} className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-bold text-gray-900 dark:text-white">{k.label}</h3>
            {k.mandatory && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                <i className="fas fa-lock mr-1"></i>Always on
              </span>
            )}
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-300">{k.about}</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Who gets it: {k.who}
            {k.mandatory && k.why_mandatory ? ` · ${k.why_mandatory}` : ""}
          </p>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {k.channels.map((c) => (
              <div
                key={c.key}
                className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 ${
                  c.available ? "border-gray-200 dark:border-gray-600" : "border-dashed border-gray-200 dark:border-gray-700"}`}
              >
                <div className="min-w-0">
                  <div className={`text-sm ${c.available ? "text-gray-800 dark:text-gray-100" : "text-gray-400"}`}>{c.name}</div>
                  {!c.available && <div className="text-xs text-gray-400">{c.why}</div>}
                </div>
                {c.available && (
                  <button
                    type="button"
                    role="switch"
                    aria-checked={Boolean(c.on)}
                    aria-label={`${k.label} by ${c.name}`}
                    disabled={busy || c.locked}
                    onClick={() => flip(k.key, c.key, !c.on)}
                    className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-60 ${
                      c.on ? "bg-eko" : "bg-gray-300 dark:bg-gray-600"}`}
                  >
                    <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${
                      c.on ? "translate-x-5" : "translate-x-0.5"}`} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
