"use client";

/**
 * Setup — Setup guide (No. 215, Stage 8 of the configurable product plan)
 *
 * Every setup step, Done / To do / Problem, each with a button to the screen
 * where it is done; then: try it in test mode (everything goes only to you),
 * see a dry run on 5 records (nothing sent), and go live — refused until the
 * essential steps are done. One switch pauses everything.
 * The same steps the chat walks through ("setup status").
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, DryRun, SetupGuideView } from "../lib/api";

const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5";
const btn = "px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50";
const input =
  "px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white";

const BADGE: Record<string, string> = {
  done: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  todo: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  problem: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
  blocked: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  optional: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
};

export default function SetupGuide({ onOpen }: { onOpen: (section: string) => void }) {
  const [view, setView] = useState<SetupGuideView | null>(null);
  const [dry, setDry] = useState<DryRun | null>(null);
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const take = (v: SetupGuideView) => {
    setView(v);
    setPhone(v.test_mode_phone || "");
    setEmail(v.test_mode_email || "");
  };

  useEffect(() => {
    let alive = true;
    api
      .setupGuide()
      .then((v) => alive && take(v))
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load the guide."));
    return () => {
      alive = false;
    };
  }, []);

  const act = useCallback(async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      take(await api.setupGuide());
      setMessage(msg);
    } catch (e) {
      setError((e as ApiError).detail || "Could not do that.");
    } finally {
      setBusy(false);
    }
  }, []);

  if (!view) {
    return (
      <div className="text-sm text-gray-500">
        {error ? <span className="text-red-600 dark:text-red-400">{error}</span> : "Loading…"}
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Setup guide</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          {view.live
            ? "This workspace is live: messages go to real people."
            : "This workspace is not live yet: nothing goes to real people. Finish the steps, try it in test mode, then go live."}
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          The chat walks you through the same steps — ask it “setup status”.
        </p>
      </div>
      {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {message && <div className="text-sm text-eko-dark dark:text-eko">{message}</div>}

      <section className={card}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white mb-2">Steps</h3>
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {view.steps.map((s) => (
            <div key={s.key} className="py-3 flex flex-col sm:flex-row sm:items-start gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold text-gray-900 dark:text-white">{s.title}</span>
                  <span className={`text-[11px] px-2 py-0.5 rounded-full ${BADGE[s.status] ?? BADGE.todo}`}>
                    {s.label}
                  </span>
                  {s.essential && <span className="text-[11px] text-gray-500">essential</span>}
                </div>
                <div className="text-xs text-gray-600 dark:text-gray-300 mt-0.5">{s.detail}</div>
                {s.how && s.status !== "done" && (
                  <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{s.how}</div>
                )}
              </div>
              {s.where && s.status !== "done" && (
                <button
                  className={`${btn} border border-eko text-eko-dark dark:text-eko shrink-0`}
                  onClick={() => onOpen(s.where as string)}
                >
                  Open
                </button>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className={card}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">Test mode</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          Everything the app sends goes only to your own number and email, marked as a test.
        </p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input className={input} placeholder="Your WhatsApp number" value={phone} onChange={(e) => setPhone(e.target.value)} />
          <input className={input} placeholder="Your email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button
            className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}
            disabled={busy}
            onClick={() =>
              act(async () => {
                await api.changeSetting("test_mode_phone", phone.trim());
                await api.changeSetting("test_mode_email", email.trim());
              }, "Saved your test number and email.")
            }
          >
            Save
          </button>
        </div>
        <label className="mt-3 inline-flex items-center gap-2 text-sm text-gray-800 dark:text-gray-100">
          <input
            type="checkbox"
            checked={view.test_mode}
            disabled={busy}
            onChange={(e) =>
              act(
                () => api.changeSetting("test_mode", e.target.checked),
                e.target.checked ? "Test mode is on." : "Test mode is off."
              )
            }
          />
          Test mode {view.test_mode ? "on" : "off"}
        </label>
      </section>

      <section className={card}>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div>
            <h3 className="text-base font-bold text-gray-900 dark:text-white">Dry run</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              What would happen for your 5 newest records. Nothing is sent.
            </p>
          </div>
          <button
            className={`${btn} border border-eko text-eko-dark dark:text-eko`}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                setDry(await api.dryRun());
              } catch (e) {
                setError((e as ApiError).detail || "Could not run it.");
              } finally {
                setBusy(false);
              }
            }}
          >
            Run the dry run
          </button>
        </div>
        {dry && (
          <div className="mt-3 space-y-2">
            {dry.records.length === 0 && <div className="text-sm text-gray-500">No records yet.</div>}
            {dry.records.map((r) => (
              <div key={r.code} className="text-sm border-t border-gray-100 dark:border-gray-700 pt-2">
                <strong>{r.name || r.code}</strong> <span className="text-gray-500">({r.code}, {r.type})</span>
                <div className="text-gray-700 dark:text-gray-200">{r.would_happen}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className={card}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">Go live and pause</h3>
        <div className="flex flex-wrap gap-3 mt-2 items-center">
          {!view.live && (
            <button
              className={`${btn} bg-eko hover:bg-eko-dark text-white`}
              disabled={busy}
              title={view.ready_to_go_live ? "" : "Finish the essential steps first"}
              onClick={() => {
                if (window.confirm("Go live? Messages will go to real people from now on.")) {
                  act(() => api.goLive(), "This workspace is live.");
                }
              }}
            >
              Go live
            </button>
          )}
          <label className="inline-flex items-center gap-2 text-sm text-gray-800 dark:text-gray-100">
            <input
              type="checkbox"
              checked={view.pause_all}
              disabled={busy}
              onChange={(e) =>
                act(
                  () => api.changeSetting("pause_all", e.target.checked),
                  e.target.checked ? "Everything is paused." : "Sending again."
                )
              }
            />
            Pause everything {view.pause_all ? "(paused)" : ""}
          </label>
        </div>
      </section>

      <section className={card}>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">This workspace&apos;s data</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          Download everything (records, messages, emails, form links, the list of documents, members,
          settings) as CSV files — no passwords or keys. Closing switches the workspace off; nothing is
          deleted, and the server administrator can open it again.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            className={`${btn} border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200`}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const blob = await api.exportWorkspace();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "workspace-export.zip";
                a.click();
                URL.revokeObjectURL(url);
              } catch (e) {
                setError((e as ApiError).detail || "Could not export.");
              } finally {
                setBusy(false);
              }
            }}
          >
            <i className="fas fa-download mr-1"></i>Download all data
          </button>
          <button
            className={`${btn} border border-red-300 text-red-700 dark:text-red-400`}
            disabled={busy}
            onClick={() => {
              const name = window.prompt("Type this workspace's name to close it:");
              if (name) act(() => api.closeWorkspace(name), "The workspace is closed.");
            }}
          >
            Close this workspace
          </button>
        </div>
      </section>
    </div>
  );
}
