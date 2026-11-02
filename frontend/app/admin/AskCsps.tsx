"use client";

/**
 * Messaging → Ask CSPs (No. 174). Anyone can be messaged: "already asked"
 * is only a label now. Search by name, CSP code, phone or email; filter by
 * whether they were asked and by what they miss; ticks stay when the
 * search changes. Choose the usual details form, a saved message, or your
 * own words ({name}, {csp_id}, {missing_items} filled in), see it for one
 * CSP, pick a channel that can send, confirm, and it goes out in parts with
 * progress. Every send is logged (the CSP's chat and Action Required).
 *
 * Kept from before (owner's choices, 2 Nov 2026): a CSP on hold is never
 * messaged; an existing CSP never gets the details form (custom is fine).
 */

import { useMemo, useRef, useState } from "react";

import { fillPlaceholders } from "../components/ActionRequiredDetail";
import { matches } from "../lib/searchMatch";
import { api } from "../lib/api";
import type {
  ApiError, CspSendResult, MessageTemplateInfo, SendCandidate, SendChannel,
} from "../lib/api";

const DETAILS = "__details__";
const OWN = "__own__";
const PART = 25;
const PAGE = 200;
const WRAPPER = "Namaste {name}, here is a message from Eko Bharat Ventures: {message} Thank you.";

const input =
  "px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white";

function day(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "";
}

export default function AskCsps({
  candidates,
  templates,
  channels,
  onChanged,
}: {
  candidates: SendCandidate[];
  templates: MessageTemplateInfo[];
  channels: SendChannel[];
  onChanged: () => void;
}) {
  // Who
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"all" | "missing" | "asked" | "not_asked">("all");
  const [needs, setNeeds] = useState<string[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState(PAGE);
  // What
  const saved = templates.filter((t) => t.purpose === "custom" && t.active);
  const [pick, setPick] = useState<string>(OWN);
  const [text, setText] = useState("Namaste {name}, please send us your {missing_items}.");
  const [newName, setNewName] = useState("");
  const [savingAs, setSavingAs] = useState(false);
  // How
  const usable = channels.filter((c) => c.can_send);
  const [picked, setChannel] = useState<string>(usable[0]?.kind ?? "whatsapp");
  // The chosen channel, or the first that can send if it no longer can.
  const channel = usable.some((c) => c.kind === picked) ? picked : usable[0]?.kind ?? picked;
  // Sending
  const [confirming, setConfirming] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  // Read between parts; a ref, so the loop sees a press at once.
  const stopRef = useRef(false);
  const [results, setResults] = useState<CspSendResult[] | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const kinds = useMemo(
    () => [...new Set(candidates.flatMap((c) => c.missing))].sort(),
    [candidates]
  );

  const filtered = useMemo(() => {
    return candidates.filter((c) => {
      if (status === "missing" && c.missing.length === 0) return false;
      if (status === "asked" && !c.already_asked) return false;
      if (status === "not_asked" && c.already_asked) return false;
      if (needs.length && !needs.every((n) => c.missing.includes(n))) return false;
      // The one way every search box matches (No. 175).
      return matches(q, [c.name, c.csp_id, c.email], [c.mobile]);
    });
  }, [candidates, q, status, needs]);

  const sendable = (c: SendCandidate) => !c.on_hold;
  const byId = useMemo(() => new Map(candidates.map((c) => [c.csp_id, c])), [candidates]);
  const selected = [...chosen].map((id) => byId.get(id)).filter(Boolean) as SendCandidate[];
  const first = selected[0];
  const template = saved.find((t) => t.id === pick);
  const kind: "custom" | "details_form" = pick === DETAILS ? "details_form" : "custom";
  const skippedExisting = kind === "details_form" ? selected.filter((c) => c.existing).length : 0;
  const channelLabel = channels.find((c) => c.kind === channel)?.label ?? channel;

  const choose = (t: string) => {
    setPick(t);
    const tpl = saved.find((x) => x.id === t);
    if (tpl) setText(tpl.body);
  };
  const toggle = (id: string) =>
    setChosen((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selectMany = (rows: SendCandidate[]) =>
    setChosen((s) => new Set([...s, ...rows.filter(sendable).map((c) => c.csp_id)]));

  const saveNew = async () => {
    if (!newName.trim() || !text.trim()) return;
    setError("");
    try {
      const r = await api.addMessageTemplate({ name: newName.trim(), body: text });
      setNote(`Saved as "${newName.trim()}".`);
      setNewName("");
      setSavingAs(false);
      setPick(r.id);
      onChanged();
    } catch (e) {
      setError((e as ApiError).detail || "Could not save the message.");
    }
  };
  const updateSaved = async () => {
    if (!template) return;
    try {
      await api.updateMessageTemplate(template.id, { ...template, body: text });
      setNote(`"${template.name}" updated.`);
      onChanged();
    } catch (e) {
      setError((e as ApiError).detail || "Could not update the message.");
    }
  };
  const deleteSaved = async () => {
    if (!template || !window.confirm(`Delete the saved message "${template.name}"?`)) return;
    try {
      await api.deleteMessageTemplate(template.id);
      setNote(`"${template.name}" deleted.`);
      setPick(OWN);
      onChanged();
    } catch (e) {
      setError((e as ApiError).detail || "Could not delete the message.");
    }
  };

  const send = async () => {
    setConfirming(false);
    stopRef.current = false;
    setError("");
    setResults(null);
    const ids = selected.map((c) => c.csp_id);
    const all: CspSendResult[] = [];
    setProgress({ done: 0, total: ids.length });
    let stopped = false;
    for (let i = 0; i < ids.length; i += PART) {
      if (stopRef.current) {
        stopped = true;
        break;
      }
      try {
        const r = await api.sendMessage({
          csp_ids: ids.slice(i, i + PART), kind, channel,
          text: kind === "custom" ? text : "",
          template_id: template?.id ?? null,
          name: `Message to ${ids.length} CSP(s) — ${template?.name ?? (kind === "details_form" ? "details form" : "own message")}`,
        });
        all.push(...r.results);
      } catch (e) {
        setError(`${(e as ApiError).detail || "Sending stopped."} ${all.length} handled before it.`);
        break;
      }
      setProgress({ done: Math.min(i + PART, ids.length), total: ids.length });
    }
    setResults(all);
    setProgress(null);
    const done = new Set(all.filter((r) => r.sent).map((r) => r.csp_id));
    setChosen((s) => new Set([...s].filter((id) => !done.has(id))));
    if (stopped) setNote(`Stopped. ${all.length} of ${ids.length} handled.`);
    onChanged();
  };

  const label = (cls: string, words: string) => (
    <span className={`px-1.5 py-0.5 rounded text-xs ${cls}`}>{words}</span>
  );

  return (
    <section className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5 space-y-4">
      <div>
        <h3 className="text-sm font-bold uppercase tracking-wider text-gray-500 mb-1">
          Ask CSPs for their details
        </h3>
        <p className="text-xs text-gray-500">
          Anyone can be messaged. A CSP on hold is never messaged, and an existing CSP is never
          sent the details form. Every message is logged in the CSP&apos;s chat and Action Required.
        </p>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {note && <p className="text-sm text-green-700 dark:text-green-400">{note}</p>}

      {/* 1. Who */}
      <div className="space-y-2">
        <div className="flex flex-wrap gap-2">
          <input
            value={q}
            onChange={(e) => { setQ(e.target.value); setShown(PAGE); }}
            placeholder="Search name, CSP code, phone or email"
            className={`${input} flex-1 min-w-[14rem]`}
          />
          <select value={status} onChange={(e) => { setStatus(e.target.value as typeof status); setShown(PAGE); }} className={input}>
            <option value="all">All</option>
            <option value="missing">Missing details</option>
            <option value="asked">Already asked</option>
            <option value="not_asked">Not asked yet</option>
          </select>
        </div>
        {kinds.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-gray-500">Missing:</span>
            {kinds.map((k) => (
              <button
                key={k}
                onClick={() => setNeeds((n) => (n.includes(k) ? n.filter((x) => x !== k) : [...n, k]))}
                className={`px-2 py-0.5 rounded-full border ${
                  needs.includes(k)
                    ? "bg-eko/10 border-eko text-eko"
                    : "border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300"}`}
              >
                {k}
              </button>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="text-gray-600 dark:text-gray-300">
            {filtered.length} shown of {candidates.length} · <b>{chosen.size} selected</b>
          </span>
          <button onClick={() => selectMany(candidates)} className="text-eko hover:underline">Select all</button>
          {filtered.length !== candidates.length && (
            <button onClick={() => selectMany(filtered)} className="text-eko hover:underline">
              Select all filtered ({filtered.filter(sendable).length})
            </button>
          )}
          {chosen.size > 0 && (
            <button onClick={() => setChosen(new Set())} className="text-gray-500 hover:underline">Clear selection</button>
          )}
          <span className="text-gray-400">Ticks stay when you search or filter. CSPs on hold are not selected.</span>
        </div>
        <div className="space-y-1 max-h-[50dvh] sm:max-h-96 overflow-y-auto overscroll-contain">
          {filtered.slice(0, shown).map((c) => (
            <label
              key={c.csp_id}
              className={`flex items-start gap-3 px-3 py-2 rounded-lg border text-sm ${
                c.on_hold
                  ? "border-gray-100 dark:border-gray-800 opacity-60"
                  : "border-gray-200 dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/40"}`}
            >
              <input
                type="checkbox"
                className="mt-1 accent-eko"
                disabled={!!c.on_hold}
                checked={chosen.has(c.csp_id)}
                onChange={() => toggle(c.csp_id)}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-medium text-gray-900 dark:text-white">{c.name || c.csp_id}</span>
                  <span className="text-xs text-gray-500">{c.csp_id}</span>
                  {c.already_asked && label("bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300", `Already asked ${day(c.asked_at)}`)}
                  {c.existing && label("bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300", "Existing CSP")}
                  {c.on_hold && label("bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300", `On hold: ${c.on_hold}`)}
                  {!c.reachable && label("bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300", "No mobile or email")}
                </div>
                <p className="text-xs text-gray-500">
                  {c.missing.length ? `Missing: ${c.missing.join(", ")}` : "Nothing missing"}
                  {(c.mobile || c.email) && <> · {[c.mobile, c.email].filter(Boolean).join(" · ")}</>}
                </p>
              </div>
            </label>
          ))}
          {filtered.length === 0 && <p className="text-sm text-gray-500 py-4">No CSP matches.</p>}
          {filtered.length > shown && (
            <button onClick={() => setShown((n) => n + PAGE)} className="w-full py-2 text-sm text-eko hover:underline">
              Show more ({filtered.length - shown} left)
            </button>
          )}
        </div>
      </div>

      {/* 2. What */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Message</span>
          <select value={pick} onChange={(e) => choose(e.target.value)} className={input}>
            <option value={DETAILS}>Details form — the usual message with a link</option>
            <option value={OWN}>Write your own</option>
            {saved.length > 0 && (
              <optgroup label="Saved messages">
                {saved.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </optgroup>
            )}
          </select>
        </div>
        {kind === "details_form" ? (
          <p className="text-xs text-gray-500">
            The wording under &ldquo;What the messages say&rdquo; above, with a new link to their own
            details form. Existing CSPs are skipped for this message.
          </p>
        ) : (
          <>
            <textarea
              rows={4}
              value={text}
              maxLength={900}
              onChange={(e) => setText(e.target.value)}
              className={`${input} w-full`}
            />
            <p className="text-xs text-gray-500">
              {"{name}"}, {"{csp_id}"} and {"{missing_items}"} are filled in for each CSP. On WhatsApp
              it goes inside the approved wording, on one line.
            </p>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {template && text !== template.body && (
                <button onClick={updateSaved} className="text-eko hover:underline">Save changes to &ldquo;{template.name}&rdquo;</button>
              )}
              {template && (
                <button onClick={deleteSaved} className="text-red-600 hover:underline">Delete &ldquo;{template.name}&rdquo;</button>
              )}
              {savingAs ? (
                <>
                  <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Name for this message" className={input} />
                  <button onClick={saveNew} disabled={!newName.trim()} className="text-eko hover:underline disabled:opacity-50">Save</button>
                  <button onClick={() => setSavingAs(false)} className="text-gray-500 hover:underline">Cancel</button>
                </>
              ) : (
                <button onClick={() => setSavingAs(true)} className="text-eko hover:underline">Save as a new message</button>
              )}
            </div>
          </>
        )}
        {first && (
          <div className="rounded-lg bg-gray-50 dark:bg-gray-900/50 p-2 text-xs space-y-1">
            <div className="font-semibold text-gray-600 dark:text-gray-300">
              Preview for {first.name || first.csp_id} ({first.csp_id})
            </div>
            {kind === "details_form" ? (
              <div className="text-gray-700 dark:text-gray-300">
                {first.existing
                  ? "Not sent — an existing CSP never gets the details form."
                  : "The usual details message with a new link to their form."}
              </div>
            ) : (
              <div className="text-gray-700 dark:text-gray-300">
                {channel === "whatsapp"
                  ? WRAPPER.replace("{name}", first.name || "CSP").replace(
                      "{message}", fillPlaceholders(text, first.name, first.csp_id, first.missing).split(/\s+/).join(" "))
                  : fillPlaceholders(text, first.name, first.csp_id, first.missing)}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 3. How */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-1.5" id="send-channels">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Send through</span>
        {channels.map((c) => (
          <label key={c.kind} className={`flex items-start gap-2 text-sm ${c.can_send ? "" : "opacity-60"}`}>
            <input type="radio" className="mt-1 accent-eko" disabled={!c.can_send}
              checked={channel === c.kind} onChange={() => setChannel(c.kind)} />
            <span>
              <span className="font-medium text-gray-900 dark:text-white">{c.label}</span>{" "}
              <span className={c.can_send ? "text-green-700 dark:text-green-400 text-xs" : "text-gray-500 text-xs"}>
                {c.can_send ? "can send" : c.why_not}
              </span>
            </span>
          </label>
        ))}
        {usable.length === 0 && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            No channel can send right now.{" "}
            <a href="#channels" className="underline">Set up channels</a> (above), or ask whoever runs
            the server to set the WhatsApp / email settings.
          </p>
        )}
      </div>

      {/* 4. Send — kept at the bottom of the screen (No. 176), clear of the
          chat button on the right. */}
      <div className="sticky bottom-0 z-10 -mx-5 px-5 pr-20 sm:pr-5 py-3 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 flex flex-wrap items-center gap-3">
        {progress ? (
          <>
            <span className="text-sm text-gray-700 dark:text-gray-300">
              Sending… {progress.done} of {progress.total}
            </span>
            <div className="h-2 w-40 rounded bg-gray-200 dark:bg-gray-700 overflow-hidden">
              <div className="h-full bg-eko" style={{ width: `${(100 * progress.done) / Math.max(progress.total, 1)}%` }}></div>
            </div>
            <button onClick={() => { stopRef.current = true; }} className="text-sm text-red-600 hover:underline">Stop</button>
          </>
        ) : confirming ? (
          <>
            <span className="text-sm text-amber-800 dark:text-amber-300">
              You are about to message {selected.length} CSP{selected.length === 1 ? "" : "s"} on {channelLabel}
              {skippedExisting > 0 && ` (${skippedExisting} existing CSP${skippedExisting === 1 ? "" : "s"} will be skipped)`}.
              There is no undo. Continue?
            </span>
            <button onClick={send} className="px-4 py-2 text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium">
              Yes — send {selected.length}
            </button>
            <button onClick={() => setConfirming(false)} className="text-sm text-gray-600 dark:text-gray-300 hover:underline">Cancel</button>
          </>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            disabled={selected.length === 0 || usable.length === 0 || (kind === "custom" && !text.trim())}
            className="px-4 py-2 text-sm rounded-lg bg-eko hover:bg-eko-dark text-white font-medium disabled:opacity-40"
          >
            Message {selected.length || ""} {selected.length === 1 ? "CSP" : "CSPs"}
          </button>
        )}
      </div>

      {results && (
        <div className="px-4 py-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-sm">
          <p className="text-green-800 dark:text-green-300 font-medium">
            {results.filter((r) => r.sent).length} sent, {results.filter((r) => !r.sent).length} not.
          </p>
          {results.filter((r) => !r.sent).slice(0, 20).map((r) => (
            <p key={r.csp_id} className="text-xs text-gray-600 dark:text-gray-400 mt-1">
              {r.csp_id}: {r.reason}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}
