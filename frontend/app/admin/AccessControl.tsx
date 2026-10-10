"use client";

/**
 * Super Admin — Access
 *
 * Who may sign in, and the only place it can be changed from.
 *
 * Granting someone access writes them into the Authorization Google Sheet
 * rather than only into the database. The sheet stays the source of truth:
 * writing only to the database would be undone by the next sync, and "who
 * can log in" would have two answers.
 *
 * Super Admins are not managed here — they come from configuration, because
 * a Super Admin is who connects a workspace's sheets in the first place.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type {
  AccessListing,
  AccessPerson,
  ApiError,
  LoginEntry,
} from "../lib/api";

export default function AccessControl() {
  const [data, setData] = useState<AccessListing | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Whose sign-in history is open, and what it holds.
  const [logins, setLogins] = useState<{
    email: string;
    entries: LoginEntry[];
    note: string;
  } | null>(null);
  const [loadingLogins, setLoadingLogins] = useState(false);

  async function openLogins(personEmail: string) {
    setLoadingLogins(true);
    setLogins({ email: personEmail, entries: [], note: "" });
    try {
      const r = await api.loginHistory(personEmail);
      setLogins({ email: personEmail, entries: r.logins, note: r.note });
    } catch (e) {
      setError((e as ApiError).detail || "Could not load the sign-in history.");
      setLogins(null);
    } finally {
      setLoadingLogins(false);
    }
  }

  const [showAdd, setShowAdd] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [mobile, setMobile] = useState("");
  const [role, setRole] = useState<"rm" | "admin" | "super_admin">("rm");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.listAccess());
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load access.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function grant() {
    if (!email.trim() || !name.trim()) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const r = await api.grantAccess({
        email: email.trim(),
        name: name.trim(),
        mobile: mobile.trim(),
        role,
      });
      setNotice(
        r.action === "reactivated"
          ? `${r.email} was already listed and has been reactivated.`
          : `${r.email} added as ${r.role.toUpperCase()}. ${r.note ?? ""}` +
              (r.sheet === "not updated"
                ? ` They can sign up now. The Authorization sheet was not updated: ${r.sheet_note ?? ""}`
                : "")
      );
      setEmail("");
      setName("");
      setMobile("");
      setShowAdd(false);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not grant access.");
    } finally {
      setBusy(false);
    }
  }

  async function restore(person: AccessPerson) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      // grant() finds the existing row and flips its Status back to
      // Active rather than adding a duplicate.
      const r = await api.grantAccess({
        email: person.email,
        name: person.name,
        mobile: person.mobile || "",
        role: person.role,
      });
      setNotice(`${person.email} can sign in again. ${r.note ?? ""}`);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not restore access.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(person: AccessPerson) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.revokeAccess({ email: person.email, role: person.role });
      setNotice(`${person.email} can no longer sign in.`);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Could not revoke access.");
    } finally {
      setBusy(false);
    }
  }

  async function syncNow() {
    setBusy(true);
    setError("");
    try {
      await api.syncAccess();
      setNotice("Sync started. The list refreshes once it finishes.");
      setTimeout(load, 4000);
    } catch (e) {
      setError((e as ApiError).detail || "Could not start a sync.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">
            Access
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Who may sign in. Changes here are written to the Authorization
            sheet, which stays the source of truth.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={syncNow}
            disabled={busy}
            className="px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            <i className="fas fa-rotate mr-2 text-xs" />
            Sync now
          </button>
          <button
            onClick={() => setShowAdd((v) => !v)}
            className="px-4 py-2 bg-eko hover:bg-eko-dark text-white text-sm font-medium rounded-lg shadow-sm"
          >
            <i className="fas fa-user-plus mr-2 text-xs" />
            Give access
          </button>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
          <i className="fas fa-circle-exclamation mr-2" />
          {error}
        </div>
      )}
      {notice && (
        <div className="px-4 py-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-sm text-green-700 dark:text-green-300">
          <i className="fas fa-circle-check mr-2" />
          {notice}
        </div>
      )}

      {showAdd && (
        <div className="p-5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 space-y-4">
          <h3 className="font-bold text-gray-900 dark:text-white">
            Give someone access
          </h3>
          <div className="grid gap-4 md:grid-cols-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Email
              </label>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@eko.co.in"
                className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Name
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Mobile
              </label>
              <input
                value={mobile}
                onChange={(e) => setMobile(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Role
              </label>
              <select
                value={role}
                onChange={(e) =>
                  setRole(e.target.value as "rm" | "admin" | "super_admin")
                }
                className="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
              >
                <option value="rm">RM — works their own CSPs</option>
                <option value="admin">Admin — dashboards only</option>
                <option value="super_admin">
                  Super Admin — runs this workspace, adds people
                </option>
              </select>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={grant}
              disabled={busy || !email.trim() || !name.trim()}
              className="px-4 py-2 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm font-medium rounded-lg"
            >
              {busy ? "Writing to the sheet…" : "Give access"}
            </button>
            <button
              onClick={() => setShowAdd(false)}
              className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:underline"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Super admins — shown so it is obvious they are not managed here */}
      {data && data.super_admins.length > 0 && (
        <div className="p-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60">
          <div className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-2">
            Workspace Owners
          </div>
          <div className="flex flex-wrap gap-2">
            {data.super_admins.map((e) => (
              <span
                key={e}
                className="px-2.5 py-1 rounded-full text-xs bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200"
              >
                {e}
              </span>
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-2">
            Set in configuration, not in the sheet — a Workspace Owner is who
            connects the sheets in the first place, so they cannot be listed
            in one.
          </p>
        </div>
      )}

      <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead className="bg-gray-50 dark:bg-gray-900/40 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-3 font-semibold">Person</th>
              <th className="px-4 py-3 font-semibold">Role</th>
              <th className="px-4 py-3 font-semibold">Signed in?</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {loading && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && data?.people.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">
                  Nobody is listed in the Authorization sheet.
                </td>
              </tr>
            )}
            {data?.people.map((p) => (
              <tr key={`${p.email}-${p.role}`} className="hover:bg-gray-50 dark:hover:bg-gray-700/40">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900 dark:text-white">
                    {p.name}
                  </div>
                  <div className="text-xs text-gray-500">{p.email}</div>
                </td>
                <td className="px-4 py-3">
                  <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 uppercase">
                    {p.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">
                  {p.registered ? (
                    p.last_login ? (
                      // The date is the LAST sign-in; clicking it opens
                      // every one that has been recorded.
                      <button
                        onClick={() => openLogins(p.email)}
                        title="Show every recorded sign-in"
                        className="underline decoration-dotted underline-offset-2 hover:text-eko"
                      >
                        {new Date(p.last_login).toLocaleDateString()}
                      </button>
                    ) : (
                      <button
                        onClick={() => openLogins(p.email)}
                        className="underline decoration-dotted underline-offset-2 hover:text-eko"
                      >
                        registered
                      </button>
                    )
                  ) : (
                    <span className="text-gray-400">never</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                      p.active
                        ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                        : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
                    }`}
                  >
                    {p.active ? "Can sign in" : "No access"}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {p.active ? (
                    <button
                      onClick={() => revoke(p)}
                      disabled={busy}
                      className="text-sm text-red-600 hover:underline disabled:opacity-50"
                    >
                      Remove access
                    </button>
                  ) : (
                    <button
                      onClick={() => restore(p)}
                      disabled={busy}
                      className="text-sm font-medium text-eko hover:underline disabled:opacity-50"
                    >
                      Give access
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {logins && (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
          <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-100 dark:border-gray-700">
            <div>
              <h3 className="font-bold text-gray-900 dark:text-white">
                Sign-ins — {logins.email}
              </h3>
              {!loadingLogins && (
                <p className="text-xs text-gray-500">
                  {logins.entries.length === 0
                    ? "Nothing recorded yet."
                    : `${logins.entries.length} recorded`}
                </p>
              )}
            </div>
            <button
              onClick={() => setLogins(null)}
              className="text-sm text-gray-600 dark:text-gray-300 hover:underline"
            >
              Close
            </button>
          </div>
          <div className="p-5">
            {loadingLogins && <p className="text-sm text-gray-500">Loading…</p>}

            {!loadingLogins && logins.entries.length === 0 && (
              // An empty list is not "never signed in" — it is "not
              // written down", and saying which is the whole point.
              <p className="text-sm text-gray-500">{logins.note}</p>
            )}

            {logins.entries.length > 0 && (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="text-xs uppercase text-gray-500">
                      <tr>
                        <th className="pb-2 pr-6 font-semibold">Day</th>
                        <th className="pb-2 pr-6 font-semibold">Date</th>
                        <th className="pb-2 pr-6 font-semibold">Time</th>
                        <th className="pb-2 pr-6 font-semibold">As</th>
                        <th className="pb-2 font-semibold">From</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                      {logins.entries.map((e: LoginEntry, i) => {
                        const when = new Date(e.at);
                        return (
                          <tr key={`${e.at}-${i}`}>
                            <td className="py-2 pr-6 text-gray-600 dark:text-gray-400">
                              {when.toLocaleDateString(undefined, {
                                weekday: "long",
                              })}
                            </td>
                            <td className="py-2 pr-6 text-gray-900 dark:text-white">
                              {when.toLocaleDateString()}
                            </td>
                            <td className="py-2 pr-6 tabular-nums text-gray-700 dark:text-gray-300">
                              {when.toLocaleTimeString()}
                            </td>
                            <td className="py-2 pr-6 uppercase text-xs text-gray-500">
                              {e.role}
                            </td>
                            <td className="py-2 text-gray-500">
                              {e.address || ""}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 text-xs text-gray-400">{logins.note}</p>
              </>
            )}
          </div>
        </div>
      )}

      {data && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Source: {data.source}, mirrored every {data.sync_interval_minutes}{" "}
          minutes. A new person can sign in once that sync has run — use
          <span className="font-medium"> Sync now</span> if you do not want to
          wait.
        </p>
      )}
    </div>
  );
}
