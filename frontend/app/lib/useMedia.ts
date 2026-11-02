"use client";

import { useSyncExternalStore } from "react";

/**
 * Whether a media query matches now (No. 176), e.g. "(min-width: 1024px)"
 * for the desktop layout. useSyncExternalStore like useSessionUser: false on
 * the server and the first paint, then the real answer, and it follows the
 * window as it is resized or the phone is turned.
 */
export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false
  );
}

/** The laptop / desktop layout: 1024px and wider. */
export const DESKTOP = "(min-width: 1024px)";
