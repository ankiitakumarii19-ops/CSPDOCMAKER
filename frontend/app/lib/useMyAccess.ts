"use client";

/**
 * What the signed-in person may use in this workspace (No. 206, Feature
 * access). The server refuses anything not given anyway; the screens use
 * this only to show the right menu. Read once per page load.
 */

import { useEffect, useState } from "react";

import { api } from "./api";
import type { MyAccess } from "./api";

let cached: Promise<MyAccess> | null = null;

/** Mix a #rrggbb colour toward black (amount < 0) or white (amount > 0). */
function shade(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const parts = [n >> 16, (n >> 8) & 255, n & 255].map((c) =>
    Math.round(amount < 0 ? c * (1 + amount) : c + (255 - c) * amount)
  );
  return `#${parts.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

/** No. 228: the workspace's Display look (Setup → Display), kept for the
 *  next visit so the page paints in it at once (app/layout.tsx). */
export function applyTheme(theme: string | undefined) {
  const t = theme && /^[a-z]+$/.test(theme) ? theme : "classic";
  if (t === "classic") document.documentElement.removeAttribute("data-ui-theme");
  else document.documentElement.setAttribute("data-ui-theme", t);
  try {
    localStorage.setItem("uiTheme", t);
  } catch {
    // a private window: the look still applies, it is just not remembered
  }
}

/** No. 229: the workspace's design style (shapes, shadows, surfaces). Neon
 *  is made for the dark, so it switches dark mode on; leaving it puts back
 *  the person's own light / dark choice. */
export function applyStyle(style: string | undefined) {
  const s = style && /^[a-z]+$/.test(style) ? style : "standard";
  const root = document.documentElement;
  const was = root.getAttribute("data-ui-style");
  if (s === "standard") root.removeAttribute("data-ui-style");
  else root.setAttribute("data-ui-style", s);
  if (s === "neon") {
    root.classList.add("dark");
  } else if (was === "neon") {
    let own: string | null = null;
    try {
      own = localStorage.getItem("theme");
    } catch {
      own = null;
    }
    const dark = own === "dark" || (!own && matchMedia("(prefers-color-scheme: dark)").matches);
    root.classList.toggle("dark", dark);
  }
  try {
    localStorage.setItem("uiStyle", s);
  } catch {
    // a private window: the style still applies, it is just not remembered
  }
}

/** Eko's own green: the Display look decides unless another colour is set. */
const EKO_GREEN = "#00b259";

/** No. 214: the workspace's colour and name, on every page that asks. */
function applyLook(access: MyAccess) {
  applyTheme(access.look?.theme);
  applyStyle(access.look?.style);
  const color = access.look?.color;
  const root = document.documentElement.style;
  if (!color || color.toLowerCase() === EKO_GREEN) {
    root.removeProperty("--color-eko");
    root.removeProperty("--color-eko-dark");
    root.removeProperty("--color-eko-light");
  } else if (/^#[0-9a-fA-F]{6}$/.test(color)) {
    root.setProperty("--color-eko", color);
    root.setProperty("--color-eko-dark", shade(color, -0.16));
    root.setProperty("--color-eko-light", shade(color, 0.9));
  }
  if (access.look?.name) document.title = access.look.name;
}

export function forgetMyAccess() {
  cached = null;
}

/** undefined while loading; null when it could not be read. */
export function useMyAccess(enabled = true): MyAccess | null | undefined {
  const [access, setAccess] = useState<MyAccess | null | undefined>(undefined);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    if (!cached) cached = api.myAccess();
    cached
      .then((a) => {
        applyLook(a);
        if (alive) setAccess(a);
      })
      .catch(() => {
        cached = null;
        if (alive) setAccess(null);
      });
    return () => {
      alive = false;
    };
  }, [enabled]);
  return access;
}
