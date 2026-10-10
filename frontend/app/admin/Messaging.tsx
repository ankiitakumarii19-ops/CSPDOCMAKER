"use client";

/**
 * Admin — Messaging
 *
 * How this workspace reaches its CSPs: the channel, the wording, and
 * sending one deliberately rather than waiting for a trigger.
 *
 * The send is the part this screen is most careful about. It reaches real
 * people and cannot be taken back, so recipients are ticked one at a time,
 * the count is stated before the button, and the result says per person
 * what happened rather than claiming success for the batch.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError, MessagingOverview, SendCandidate, SendResult,
} from "../lib/api";

export default function Messaging() {
  const [data, setData] = useState<MessagingOverview | null>(null);
  const [candidates, setCandidates] = useState<SendCandidate[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<SendResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [o, c] = await Promise.all([
        api.messagingOverview(),
        api.sendCandidates(),
      ]);
      setData(o);
      setCandidates(c.candidates);
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load messaging.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function addEmailChannel() {
    setBusy(true);
    setError("");
    try {
      await api.addChannel({
        name: "Email", kind: "email", provider: "smtp",
        config: {}, secret_ref: "SMTP_PASSWORD", is_default: true,
        active: true,
      });
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not add that channel.");
    } finally {
      setBusy(false);
    }
  }

  async function saveWording(id: string) {
    const template = data?.templates.find((t) => t.id === id);
    if (!template) return;
    setBusy(true);
    try {
      await api.updateMessageTemplate(id, { ...template, body: draft });
      setEditing(null);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not save that wording.");
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    setBusy(true);
    setError("");
    try {
      const r = await api.sendDataRequests([...chosen]);
      setResult(r);
      setChosen(new Set());
      setConfirming(false);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not send.");
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string) {
    setChosen((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  const canSend = (data?.channels ?? []).some((c) => c.active && c.can_send);
  const askable = candidates.filter((c) => c.reachable && !c.already_asked);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">
          Messaging
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          How CSPs are reached, what the message says, and asking a group
          for their details.
        </p>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {loading && <p className="text-sm text-gray-500 py-8">Loading…</p>}

      {/* Channels */}
      {data && (
        <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500">
              Channels
            </h3>
            {data.channels.length === 0 && (
              <button
                onClick={addEmailChannel}
                disabled={busy}
                className="px-3 py-1.5 text-sm rounded-lg bg-eko hover:bg-eko-dark text-white font-medium disabled:opacity-50"
              >
                Add the email channel
              </button>
            )}
          </div>

          {data.channels.length === 0 ? (
            <p className="text-sm text-gray-500">
              Nothing is configured, so nothing can be sent. Email works
              today and needs no provider approval.
            </p>
          ) : (
            <div className="space-y-2">
              {data.channels.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700"
                >
                  <div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {c.name}
                    </span>
                    <span className="ml-2 text-xs text-gray-500">
                      {c.kind} · {c.provider}
                      {c.is_default && " · default"}
                    </span>
                    {!c.can_send && (
                      <p className="text-xs text-amber-600 mt-0.5">
                        No sender exists for this kind yet — it will not
                        deliver.
                      </p>
                    )}
                    {c.last_error && (
                      <p className="text-xs text-red-600 mt-0.5">
                        Last error: {c.last_error}
                      </p>
                    )}
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] ${
                      c.active && c.can_send
                        ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                        : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
                    }`}
                  >
                    {c.active && c.can_send ? "Can send" : "Cannot send"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Wording */}
      {data && (
        <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5">
          <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500 mb-1">
            What the messages say
          </h3>
          <p className="text-xs text-gray-500 mb-4">
            Supplied as a starting point and fully editable.{" "}
            <code className="px-1 bg-gray-100 dark:bg-gray-900 rounded">
              {"{name}"}
            </code>
            ,{" "}
            <code className="px-1 bg-gray-100 dark:bg-gray-900 rounded">
              {"{link}"}
            </code>{" "}
            and{" "}
            <code className="px-1 bg-gray-100 dark:bg-gray-900 rounded">
              {"{fields}"}
            </code>{" "}
            are filled in; anything else is left alone.
          </p>
          <div className="space-y-3">
            {data.templates.map((t) => (
              <div
                key={t.id}
                className="p-3 rounded-lg border border-gray-200 dark:border-gray-700"
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {t.name}
                    </span>
                    <span className="ml-2 text-xs text-gray-500">
                      {t.purpose} · {t.channel_kind}
                      {t.is_builtin && " · supplied"}
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      setEditing(editing === t.id ? null : t.id);
                      setDraft(t.body);
                    }}
                    className="text-sm text-eko hover:underline"
                  >
                    {editing === t.id ? "Cancel" : "Edit"}
                  </button>
                </div>
                {editing === t.id ? (
                  <div className="mt-3 space-y-2">
                    <textarea
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      rows={10}
                      className="w-full px-3 py-2 text-sm font-mono rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
                    />
                    <button
                      onClick={() => saveWording(t.id)}
                      disabled={busy}
                      className="px-4 py-2 text-sm rounded-lg bg-eko hover:bg-eko-dark text-white font-medium disabled:opacity-50"
                    >
                      Save wording
                    </button>
                  </div>
                ) : (
                  <pre className="mt-2 text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap font-sans line-clamp-3">
                    {t.body.slice(0, 220)}
                    {t.body.length > 220 && "…"}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Asking people */}
      <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5">
        <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500 mb-1">
          Ask CSPs for their details
        </h3>
        <p className="text-xs text-gray-500 mb-4">
          {askable.length} could usefully be asked. Tick the ones to message
          — there is deliberately no &ldquo;everyone&rdquo; button.
        </p>

        {result && (
          <div className="mb-4 px-4 py-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-sm">
            <p className="text-green-800 dark:text-green-300 font-medium">
              Asked {result.asked}: {result.sent} sent, {result.failed} not.
            </p>
            {result.results
              .filter((r) => !r.sent)
              .slice(0, 8)
              .map((r) => (
                <p key={r.csp_id} className="text-xs text-gray-600 mt-1">
                  {r.csp_id}: {r.reason}
                </p>
              ))}
          </div>
        )}

        <div className="space-y-1 max-h-80 overflow-y-auto">
          {candidates.map((c) => (
            <label
              key={c.csp_id}
              className={`flex items-start gap-3 px-3 py-2 rounded-lg border text-sm ${
                c.reachable && !c.already_asked
                  ? "border-gray-200 dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/40"
                  : "border-gray-100 dark:border-gray-800 opacity-60"
              }`}
            >
              <input
                type="checkbox"
                className="mt-1 accent-eko"
                disabled={!c.reachable || c.already_asked}
                checked={chosen.has(c.csp_id)}
                onChange={() => toggle(c.csp_id)}
              />
              <div className="min-w-0">
                <span className="font-medium text-gray-900 dark:text-white">
                  {c.name || c.csp_id}
                </span>
                <span className="ml-2 text-xs text-gray-500">{c.csp_id}</span>
                <p className="text-xs text-gray-500">
                  Missing: {c.missing.join(", ")}
                </p>
                {!c.reachable && (
                  <p className="text-xs text-amber-600">
                    No usable mobile and no email — their RM must collect
                    this in person.
                  </p>
                )}
                {c.already_asked && (
                  <p className="text-xs text-gray-500">
                    Already asked and being waited on.
                  </p>
                )}
              </div>
            </label>
          ))}
          {candidates.length === 0 && !loading && (
            <p className="text-sm text-gray-500 py-4">
              Nobody is missing anything only they can supply.
            </p>
          )}
        </div>

        <div className="mt-4 flex items-center gap-3 flex-wrap">
          {confirming ? (
            <>
              <span className="text-sm text-amber-800 dark:text-amber-300">
                This emails {chosen.size}{" "}
                {chosen.size === 1 ? "person" : "people"} directly. There is
                no undo.
              </span>
              <button
                onClick={send}
                disabled={busy}
                className="px-4 py-2 text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium disabled:opacity-50"
              >
                {busy ? "Sending…" : `Yes — send ${chosen.size}`}
              </button>
              <button
                onClick={() => setConfirming(false)}
                className="text-sm text-gray-600 dark:text-gray-300 hover:underline"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              disabled={chosen.size === 0 || !canSend}
              title={
                !canSend ? "No channel that can actually deliver" : undefined
              }
              className="px-4 py-2 text-sm rounded-lg bg-eko hover:bg-eko-dark text-white font-medium disabled:opacity-40"
            >
              Ask {chosen.size > 0 ? chosen.size : ""}{" "}
              {chosen.size === 1 ? "CSP" : "CSPs"}
            </button>
          )}
          {!canSend && (
            <span className="text-xs text-amber-600">
              Add a channel that can deliver first.
            </span>
          )}
        </div>
      </section>
    </div>
  );
}
