"use client";

import { useEffect, useRef, useState } from "react";

/**
 * "Log in with Google" (No. 171) — Google's own button (Google Identity
 * Services). Google signs the person in and hands this page an ID token,
 * which the server checks (POST /api/auth/google). Nothing to do with the
 * Gmail account the app sends mail from.
 */

type GoogleId = {
  initialize: (o: {
    client_id: string;
    callback: (r: { credential?: string }) => void;
    ux_mode?: "popup" | "redirect";
  }) => void;
  renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
};

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleId } };
  }
}

const SCRIPT = "https://accounts.google.com/gsi/client";

function loadScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  const existing = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT}"]`);
  return new Promise((resolve, reject) => {
    const s = existing ?? document.createElement("script");
    s.addEventListener("load", () => resolve());
    s.addEventListener("error", () => reject(new Error("load failed")));
    if (!existing) {
      s.src = SCRIPT;
      s.async = true;
      document.head.appendChild(s);
    }
  });
}

export default function GoogleSignIn({
  clientId,
  onCredential,
  dark,
}: {
  clientId: string;
  onCredential: (credential: string) => void;
  dark?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  // The latest handler, so re-rendering the page does not redraw the button.
  const handler = useRef(onCredential);
  useEffect(() => {
    handler.current = onCredential;
  }, [onCredential]);

  useEffect(() => {
    let cancelled = false;
    loadScript()
      .then(() => {
        const id = window.google?.accounts?.id;
        if (cancelled || !id || !box.current) return;
        id.initialize({
          client_id: clientId,
          ux_mode: "popup",
          callback: (r) => r.credential && handler.current(r.credential),
        });
        id.renderButton(box.current, {
          type: "standard",
          theme: dark ? "filled_black" : "outline",
          size: "large",
          text: "signin_with",
          shape: "rectangular",
          logo_alignment: "center",
          width: Math.min(box.current.offsetWidth || 400, 400),
        });
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [clientId, dark]);

  if (failed) {
    return (
      <p className="text-xs text-center text-gray-500">
        Google sign-in could not be loaded. Check the connection, or log in with your password.
      </p>
    );
  }
  return <div ref={box} className="w-full flex justify-center min-h-[44px]" />;
}
