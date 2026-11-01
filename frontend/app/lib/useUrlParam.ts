"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * A piece of page state kept in the address bar (No. 171): the section
 * open, the CSP whose chat is open, the RM's tab. A refresh, a bookmark or
 * Back then brings the same screen back, instead of the first section.
 *
 * The browser's own history (pushState) — which this Next.js version syncs
 * with its router (docs: Linking and Navigating → Native History API) — read
 * with useSyncExternalStore like useSessionUser, so the server and the first
 * paint agree and nothing redirects before the real value is known.
 */

const EVENT = "url-param-change";

function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

/** Change several at once: null or "" removes one. push = a Back step. */
export function setUrlParams(changes: Record<string, string | null>, push = true) {
  const params = new URLSearchParams(window.location.search);
  for (const [key, value] of Object.entries(changes)) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  if (url === `${window.location.pathname}${window.location.search}${window.location.hash}`) return;
  if (push) window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
  window.dispatchEvent(new Event(EVENT));
}

export function useUrlParam(
  key: string,
  fallback = ""
): [string, (value: string | null, push?: boolean) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => new URLSearchParams(window.location.search).get(key) ?? fallback,
    () => fallback
  );
  const set = useCallback(
    (next: string | null, push = true) =>
      setUrlParams({ [key]: next === fallback ? null : next }, push),
    [key, fallback]
  );
  return [value, set];
}
