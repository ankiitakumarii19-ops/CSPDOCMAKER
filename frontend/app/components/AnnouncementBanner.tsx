"use client";

/**
 * The platform's announcements (No. 240, Stage 6) — set by the Supreme Owner
 * for every workspace or one; shown to signed-in staff on the Admin and RM
 * pages only (never to CSPs on their form). A person may close one for this
 * visit; it comes back next time until the Supreme Owner ends it.
 */

import { useEffect, useState } from "react";

import { api } from "../lib/api";

interface Announcement {
  id: string;
  message: string;
  level: "info" | "warning";
}

export default function AnnouncementBanner() {
  const [items, setItems] = useState<Announcement[]>([]);
  const [closed, setClosed] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    api
      .myAnnouncements()
      .then((r) => alive && setItems(r.announcements))
      .catch((e) => console.warn("AnnouncementBanner: announcements not read", e));
    return () => {
      alive = false;
    };
  }, []);

  const shown = items.filter((a) => !closed.includes(a.id));
  if (shown.length === 0) return null;
  return (
    <div className="shrink-0" role="region" aria-label="Announcements">
      {shown.map((a) => (
        <div
          key={a.id}
          role={a.level === "warning" ? "alert" : "status"}
          className={`flex items-start gap-3 px-3 sm:px-6 py-2 text-sm border-b ${
            a.level === "warning"
              ? "bg-amber-50 text-amber-900 border-amber-200 dark:bg-amber-900/30 dark:text-amber-200 dark:border-amber-800"
              : "bg-blue-50 text-blue-900 border-blue-200 dark:bg-blue-900/30 dark:text-blue-200 dark:border-blue-800"
          }`}
        >
          <i className={`fas ${a.level === "warning" ? "fa-triangle-exclamation" : "fa-bullhorn"} mt-0.5`} />
          <span className="flex-1">{a.message}</span>
          <button
            type="button"
            aria-label="Close this announcement"
            onClick={() => setClosed((c) => [...c, a.id])}
            className="opacity-70 hover:opacity-100 px-1"
          >
            <i className="fas fa-times" />
          </button>
        </div>
      ))}
    </div>
  );
}
