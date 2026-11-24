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

/** No. 214: the workspace's colour and name, on every page that asks. */
function applyLook(access: MyAccess) {
  const color = access.look?.color;
  if (color && /^#[0-9a-fA-F]{6}$/.test(color)) {
    const root = document.documentElement.style;
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
