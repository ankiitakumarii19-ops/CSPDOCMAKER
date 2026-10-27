"use client";

/**
 * One line under "Why messages were sent" (No. 158): what the contact job is
 * doing about bounced emails and WhatsApps that did not reach the phone —
 * in progress, fixed, stopped, and what the ones in progress wait for.
 * The full list: Admin → Setup → Data quality → Loop 2.
 */

import type { ContactStatus } from "../lib/api";

export default function ContactStatusLine({ status }: { status?: ContactStatus }) {
  if (!status) return null;
  return (
    <p className="mt-3 text-xs text-gray-600 dark:text-gray-300">
      <i className="fas fa-arrows-rotate mr-1 text-gray-400"></i>
      {status.found === 0 ? (
        <>Bounced emails / WhatsApps that did not reach the phone: none found yet.</>
      ) : (
        <>
          Bounced emails / unreachable WhatsApp: <b>{status.in_progress}</b> in progress ·{" "}
          <b>{status.fixed}</b> fixed · <b>{status.stopped}</b> stopped
          {status.waiting.length > 0 && (
            <>
              {" "}— waiting:{" "}
              {status.waiting.map((w, i) => (
                <span key={w.note}>
                  {i > 0 && "; "}
                  {w.note.replace(/^waiting: /, "")} ({w.count})
                </span>
              ))}
            </>
          )}
          . Details: Admin → Setup → Data quality → Loop 2.
        </>
      )}
    </p>
  );
}
