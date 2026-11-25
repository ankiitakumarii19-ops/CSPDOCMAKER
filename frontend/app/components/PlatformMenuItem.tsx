"use client";

/**
 * "Supreme Owner console" in the profile menu (No. 240, Stage 6) — shown only
 * to the platform's Supreme Owner (the server decides: /api/me/platform). The
 * console's server routes refuse everyone else anyway.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "../lib/api";

let cached: Promise<boolean> | null = null;

export default function PlatformMenuItem() {
  const router = useRouter();
  const [show, setShow] = useState(false);

  useEffect(() => {
    let alive = true;
    if (!cached) {
      cached = api
        .mePlatform()
        .then((r) => r.supreme_owner)
        .catch(() => {
          cached = null;
          return false;
        });
    }
    cached.then((yes) => alive && setShow(yes));
    return () => {
      alive = false;
    };
  }, []);

  if (!show) return null;
  return (
    <button
      onClick={() => router.push("/platform")}
      className="w-full text-left px-4 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
    >
      <i className="fas fa-crown mr-2"></i> Supreme Owner console
    </button>
  );
}
