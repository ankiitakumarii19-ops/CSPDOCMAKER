"use client";

/**
 * Setup — Connections (No. 210, Stage 3 of the configurable product plan)
 *
 * The workspace's own Google Sheets, email account, WhatsApp platform and
 * CRM, each with a Test button. Passwords and keys are typed into their own
 * box, kept locked on the server and never shown again. A workspace that is
 * not Eko's starts with nothing connected — it never uses Eko's.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, ConnectionItem, ConnectionsView } from "../lib/api";

const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800";
const input =
  "w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-eko disabled:opacity-60";
const btn = "px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50";

function Field({
  item,
  busy,
  onSave,
  onClear,
}: {
  item: ConnectionItem;
  busy: boolean;
  onSave: (key: string, value: string) => void;
  onClear: (key: string) => void;
}) {
  const shown = item.kind === "secret" ? "" : String(item.value ?? "");
  const [draft, setDraft] = useState(shown);
  const edited = item.kind === "secret" ? draft.length > 0 : draft !== shown;
  return (
    <div className="py-3 border-t border-gray-100 dark:border-gray-700 first:border-t-0">
      <div className="flex flex-col md:flex-row md:items-start gap-2">
        <div className="md:w-2/5 min-w-0">
          <div className="text-sm font-semibold text-gray-900 dark:text-white">{item.label}</div>
          <div className="text-xs text-gray-500 dark:text-gray-400">{item.help}</div>
          {item.from_server && (
            <div className="text-[11px] text-gray-500 mt-0.5">Using the server&apos;s (Eko&apos;s)</div>
          )}
          {item.own && item.changed_by && (
            <div className="text-[11px] text-gray-500 mt-0.5">
              Set by {item.changed_by}
              {item.changed_at ? ` on ${new Date(item.changed_at).toLocaleDateString("en-IN")}` : ""}
            </div>
          )}
        </div>
        <div className="md:w-3/5 flex flex-col sm:flex-row gap-2 sm:items-center">
          {item.kind === "choice" ? (
            <select className={input} value={draft} disabled={busy} onChange={(e) => setDraft(e.target.value)}>
              {item.choices.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          ) : (
            <input
              className={input}
              type={item.kind === "secret" ? "password" : item.kind === "int" ? "number" : "text"}
              autoComplete={item.kind === "secret" ? "new-password" : "off"}
              placeholder={
                item.kind === "secret" ? (item.secret_set ? "•••••••• (set — type to replace)" : "Not set") : ""
              }
              value={draft}
              disabled={busy}
              onChange={(e) => setDraft(e.target.value)}
            />
          )}
          <div className="flex gap-2 shrink-0">
            {edited && (
              <button
                className={`${btn} bg-eko hover:bg-eko-dark text-white`}
                disabled={busy}
                onClick={() => {
                  onSave(item.key, draft);
                  if (item.kind === "secret") setDraft("");
                }}
              >
                Save
              </button>
            )}
            {item.own && !edited && (
              <button
                className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}
                disabled={busy}
                onClick={() => onClear(item.key)}
              >
                Remove
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Connections() {
  const [view, setView] = useState<ConnectionsView | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [tests, setTests] = useState<Record<string, { ok: boolean; message: string } | "running">>({});

  useEffect(() => {
    let alive = true;
    api
      .connections()
      .then((v) => alive && setView(v))
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load the connections."));
    return () => {
      alive = false;
    };
  }, []);

  async function save(key: string, value: string) {
    setBusy(true);
    setError("");
    try {
      setView(await api.setConnection(key, value));
      setMessage("Saved. Press Test to check it works.");
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function clear(key: string) {
    setBusy(true);
    try {
      setView(await api.clearConnection(key));
      setMessage("Removed.");
    } catch (e) {
      setError((e as ApiError).detail || "Could not remove.");
    } finally {
      setBusy(false);
    }
  }

  async function test(group: string) {
    setTests((t) => ({ ...t, [group]: "running" }));
    try {
      const out = await api.testConnection(group);
      setTests((t) => ({ ...t, [group]: out }));
    } catch (e) {
      setTests((t) => ({ ...t, [group]: { ok: false, message: (e as ApiError).detail || "Test failed." } }));
    }
  }

  if (!view) {
    return (
      <div className="text-sm text-gray-500">
        {error ? (
          <span className="text-red-600 dark:text-red-400">{error}</span>
        ) : (
          <>
            <i className="fas fa-circle-notch fa-spin mr-2"></i>Loading…
          </>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Connections</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Where <strong>{view.workspace.name}</strong> reads its records and how it sends. {view.note}
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          In the chat: <em>set csp sheet to &lt;link&gt;</em>, <em>test my sheet</em>,{" "}
          <em>test connections</em>. Passwords only here, never in the chat.
        </p>
      </div>
      {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {message && <div className="text-sm text-eko-dark dark:text-eko">{message}</div>}

      {view.groups.map((g) => {
        const items = view.connections.filter((c) => c.group === g.key);
        const t = tests[g.key];
        return (
          <section key={g.key} className={card}>
            <div className="px-5 pt-4 pb-2 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
              <div>
                <h3 className="text-base font-bold text-gray-900 dark:text-white flex items-center gap-2">
                  {g.title}
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full ${
                      view.connected[g.key]
                        ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
                        : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
                    }`}
                  >
                    {view.connected[g.key] ? "Connected" : "Not connected"}
                  </span>
                </h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">{g.about}</p>
                {g.key === "sheets" && view.robot_email && (
                  <p className="text-xs text-gray-700 dark:text-gray-200 mt-1">
                    Robot address: <code className="select-all">{view.robot_email}</code>
                  </p>
                )}
              </div>
              <button
                className={`${btn} border border-eko text-eko-dark dark:text-eko shrink-0`}
                disabled={t === "running"}
                onClick={() => test(g.key)}
              >
                {t === "running" ? "Testing…" : g.key === "email" ? "Send a test email to me" : "Test"}
              </button>
            </div>
            {t && t !== "running" && (
              <div
                className={`mx-5 mb-2 rounded-lg p-2 text-sm ${
                  t.ok
                    ? "bg-green-50 text-green-800 dark:bg-green-900/20 dark:text-green-300"
                    : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                }`}
              >
                {t.ok ? "✅ " : "❌ "}
                {t.message}
              </div>
            )}
            <div className="px-5 pb-2">
              {items.map((item) => (
                <Field
                  key={`${item.key}:${String(item.value)}:${String(item.secret_set)}`}
                  item={item}
                  busy={busy}
                  onSave={save}
                  onClear={clear}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
