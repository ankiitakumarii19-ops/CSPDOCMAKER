"use client";

import { useEffect, useState } from "react";

import { api } from "../lib/api";

/**
 * A CSP's photo as every screen shows it: the edited passport version
 * (white background, 35 x 45 mm), whether it came from the sheet, an RM's
 * upload or the CSP's own form (No. 102).
 *
 * Fetched with the signed-in person's token — a plain <img src> sends none,
 * so it could never be authorised. Give it a `key` that changes when the
 * photo does (for example after an upload) to load it afresh.
 */
export default function CspPhoto({
  cspId,
  className = "w-[70px] h-[90px]",
  showEmpty = true,
}: {
  cspId: string;
  className?: string;
  /** Show a "No photo" box when there is none; otherwise render nothing. */
  showEmpty?: boolean;
}) {
  const [state, setState] = useState<
    { kind: "loading" } | { kind: "none" } | { kind: "error" } | { kind: "ready"; url: string }
  >({ kind: "loading" });

  useEffect(() => {
    let url = "";
    let cancelled = false;
    api
      .cspPhoto(cspId)
      .then((blob) => {
        if (cancelled) return;
        if (!blob) {
          setState({ kind: "none" });
          return;
        }
        url = URL.createObjectURL(blob);
        setState({ kind: "ready", url });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "error" });
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [cspId]);

  const frame = `${className} rounded border border-gray-200 dark:border-gray-600 shrink-0`;

  if (state.kind === "ready") {
    return (
      // A blob: URL from an authorised fetch, which next/image cannot load.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={state.url}
        alt={`Photo of ${cspId}`}
        className={`${frame} object-cover bg-white`}
      />
    );
  }
  if (state.kind === "loading") {
    return <div className={`${frame} bg-gray-100 dark:bg-gray-700 animate-pulse`} />;
  }
  if (!showEmpty) return null;
  return (
    <div
      className={`${frame} bg-gray-50 dark:bg-gray-900 flex flex-col items-center justify-center text-center text-gray-400`}
      title={state.kind === "error" ? "The photo could not be loaded" : "No photo yet"}
    >
      <i className="fas fa-user text-lg"></i>
      <span className="text-[10px] leading-tight mt-1">
        {state.kind === "error" ? "Not loaded" : "No photo"}
      </span>
    </div>
  );
}
