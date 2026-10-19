"use client";

/**
 * Setup — Workspace Rules (tracker No. 120)
 *
 * Each workspace's Owner chooses its own rules: which email domains may join
 * (Eko keeps @eko.co.in and @ekosupport.in; another company chooses its own),
 * how long a sign-in lasts, whether Admins may add members, and the sign-off
 * on messages to CSPs. The server enforces every rule; a rule that would lock
 * out this workspace's own Super Admin is refused there.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, WorkspaceRules as Rules, WorkspaceRulesInput } from "../lib/api";

const card = "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-5";
const input =
  "w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-eko";
const label = "block text-sm font-semibold text-gray-900 dark:text-white";
const hint = "text-xs text-gray-500 dark:text-gray-400 mt-0.5 mb-2";

function domainsFromText(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((d) => d.trim())
    .filter(Boolean);
}

export default function WorkspaceRules({ canEdit }: { canEdit: boolean }) {
  const [rules, setRules] = useState<Rules | null>(null);
  const [form, setForm] = useState<WorkspaceRulesInput | null>(null);
  const [domainsText, setDomainsText] = useState("");
  const [anyone, setAnyone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  function take(r: Rules) {
    setRules(r);
    setForm({
      allowed_email_domains: r.allowed_email_domains,
      session_hours: r.session_hours,
      members_added_by: r.members_added_by,
      message_signoff: r.message_signoff,
    });
    setAnyone(r.allowed_email_domains.length === 0);
    setDomainsText(r.allowed_email_domains.map((d) => `@${d}`).join(", "));
  }

  useEffect(() => {
    api
      .workspaceRules()
      .then(take)
      .catch((e) => setError((e as ApiError).detail || "Could not load the rules."));
  }, []);

  async function save() {
    if (!form) return;
    const domains = anyone ? [] : domainsFromText(domainsText);
    if (!anyone && domains.length === 0) {
      setError("Add at least one domain, or choose “Any email address”.");
      return;
    }
    setBusy(true);
    setError("");
    setSaved("");
    try {
      const r = await api.saveWorkspaceRules({ ...form, allowed_email_domains: domains });
      take(r);
      const parts = ["Saved."];
      if (r.wordings_resigned && r.wordings_resigned.length > 0) {
        parts.push(`Sign-off updated on: ${r.wordings_resigned.join(", ")}.`);
      }
      if (r.note) parts.push(r.note);
      setSaved(parts.join(" "));
    } catch (e) {
      setError((e as ApiError).detail || "Could not save the rules.");
    } finally {
      setBusy(false);
    }
  }

  if (!form || !rules) {
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

  const disabled = !canEdit || busy;

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Workspace Rules</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          The rules for <strong>{rules.workspace.name}</strong>. Other workspaces have their own.
          {!canEdit && " Only the Workspace Owner can change them."}
        </p>
      </div>

      <section className={card}>
        <span className={label}>Who can join this workspace</span>
        <p className={hint}>
          Only people with these email domains can be added and can sign in here. Someone already
          added whose domain you remove can no longer enter.
        </p>
        <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200 mb-2">
          <input
            type="radio"
            checked={!anyone}
            disabled={disabled}
            onChange={() => setAnyone(false)}
          />
          Only these domains
        </label>
        <input
          className={`${input} ${anyone ? "opacity-50" : ""}`}
          value={domainsText}
          disabled={disabled || anyone}
          onChange={(e) => setDomainsText(e.target.value)}
          placeholder="@yourcompany.com, @partner.in"
        />
        <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200 mt-3">
          <input
            type="radio"
            checked={anyone}
            disabled={disabled}
            onChange={() => setAnyone(true)}
          />
          Any email address (you still choose who is added)
        </label>
      </section>

      <section className={card}>
        <span className={label}>Sign-in length</span>
        <p className={hint}>
          How many hours a sign-in lasts before asking again (1–720). Applies from each person&apos;s
          next sign-in.
        </p>
        <input
          type="number"
          min={1}
          max={720}
          className={`${input} max-w-[10rem]`}
          value={form.session_hours}
          disabled={disabled}
          onChange={(e) => setForm({ ...form, session_hours: Number(e.target.value) })}
        />
        <span className="ml-2 text-sm text-gray-500">hours</span>
      </section>

      <section className={card}>
        <span className={label}>Who can add and remove members</span>
        <p className={hint}>Only you can add or remove a Super Admin either way.</p>
        {(
          [
            ["owner", "Only the Workspace Owner (Super Admins)"],
            ["owner_and_admins", "The Workspace Owner and Admins"],
          ] as const
        ).map(([value, text]) => (
          <label key={value} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input
              type="radio"
              checked={form.members_added_by === value}
              disabled={disabled}
              onChange={() => setForm({ ...form, members_added_by: value })}
            />
            {text}
          </label>
        ))}
      </section>

      <section className={card}>
        <span className={label}>Message sign-off</span>
        <p className={hint}>
          The “— …” line messages to CSPs end with. Saving puts it on every message wording that ends
          with a sign-off; WhatsApp wordings then need Meta&apos;s approval once. Leave empty to keep
          each wording as written.
        </p>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">—</span>
          <input
            className={input}
            value={form.message_signoff}
            maxLength={100}
            disabled={disabled}
            onChange={(e) => setForm({ ...form, message_signoff: e.target.value })}
            placeholder="Team Eko"
          />
        </div>
      </section>

      {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {saved && <div className="text-sm text-eko-dark dark:text-eko">{saved}</div>}

      {canEdit && (
        <button
          onClick={save}
          disabled={busy}
          className="px-4 py-2 rounded-lg text-sm font-semibold bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save rules"}
        </button>
      )}
    </div>
  );
}
