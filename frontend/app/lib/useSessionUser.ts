"use client";

import { useMemo, useSyncExternalStore } from "react";

export interface SessionUser {
  name: string;
  email: string;
  role: string;
}

/** The sign-in is shared by every tab (localStorage, No. 100), so a
 *  sign-out in another tab is heard here and this tab follows it. */
function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function read(): string | null {
  try {
    return localStorage.getItem("user");
  } catch {
    return null;
  }
}

/** Unknown on the server, and during the first (hydrating) render in the
 *  browser, which React draws with this same value. It must not read as
 *  "signed out": a page that redirects on that sent anyone who reloaded it
 *  to the login screen (No. 100). */
function readOnServer(): string | null | undefined {
  return undefined;
}

/**
 * The signed-in user, read from localStorage.
 *
 * useSyncExternalStore rather than an effect: reading browser-only state in
 * an effect and calling setState causes a cascading render, and doing it in a
 * useState initializer would make the server and client render different
 * markup. This gives React both snapshots and lets it reconcile them.
 *
 * Returns undefined while the value is unknown (server render and first
 * paint) and null when there is no signed-in user, so a caller can tell
 * "not loaded yet" from "not logged in" and avoid redirecting too early.
 */
export function useSessionUser(): SessionUser | null | undefined {
  const raw = useSyncExternalStore<string | null | undefined>(
    subscribe, read, readOnServer);

  return useMemo(() => {
    if (raw === undefined) return undefined;
    if (raw === null) return null;
    try {
      const parsed = JSON.parse(raw);
      if (!parsed?.email || !parsed?.role) return null;
      return {
        name: parsed.name ?? parsed.email,
        email: parsed.email,
        role: String(parsed.role).toLowerCase(),
      };
    } catch {
      return null;
    }
  }, [raw]);
}
