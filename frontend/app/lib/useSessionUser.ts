"use client";

import { useMemo, useSyncExternalStore } from "react";

export interface SessionUser {
  name: string;
  email: string;
  role: string;
}

/** Nothing writes to sessionStorage while a page is mounted except sign-in
 *  and sign-out, both of which navigate, so there is nothing to subscribe to. */
function subscribe() {
  return () => {};
}

function read(): string | null {
  try {
    return sessionStorage.getItem("user");
  } catch {
    return null;
  }
}

/** Nothing on the server: the value lives only in the browser. */
function readOnServer(): string | null {
  return null;
}

/**
 * The signed-in user, read from sessionStorage.
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
  const raw = useSyncExternalStore(subscribe, read, readOnServer);

  return useMemo(() => {
    if (raw === null) return typeof window === "undefined" ? undefined : null;
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
