"use client";

/**
 * Setup → Display → Branding (No. 240, SaaS upgrade Stage 3)
 *
 * The organisation's logo, its second colour, and whether people may pick
 * their own colours and font. The name and main colour are on the same
 * screen's settings (Settings → Look); the email sender is on Connections.
 * Only the Super Admin changes these; everything else here is a workspace
 * setting with history and undo (Settings → History).
 */

import { useEffect, useRef, useState } from "react";

import BrandLogo from "../components/BrandLogo";
import { api } from "../lib/api";
import type { ApiError } from "../lib/api";
import { forgetMyAccess } from "../lib/useMyAccess";

export default function Branding({ canChange }: { canChange: boolean }) {
  const [logo, setLogo] = useState<string | null | undefined>(undefined);
  const [name, setName] = useState("");
  const [colour2, setColour2] = useState("");
  const [ownColours, setOwnColours] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const file = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let alive = true;
    forgetMyAccess();
    api
      .myAccess()
      .then((a) => {
        if (!alive) return;
        setLogo(a.look.logo ?? null);
        setName(a.look.org_name || a.look.name);
        setColour2(a.look.color_2 || "");
        setOwnColours(a.look.own_colours !== false);
      })
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load the branding."));
    return () => {
      alive = false;
    };
  }, []);

  async function run(work: () => Promise<void>, done: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
      forgetMyAccess();
      setMessage(done);
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  const upload = (f: File) =>
    run(async () => {
      const r = await api.uploadLogo(f);
      setLogo(r.logo);
    }, "Logo saved. Everyone in this workspace sees it from their next page.");

  const remove = () => {
    if (!window.confirm("Remove the logo and show the app's own again?")) return;
    run(async () => {
      await api.removeLogo();
      setLogo(null);
    }, "Logo removed: the app's own logo is shown again.");
  };

  const saveColour2 = (value: string) =>
    run(async () => {
      await api.changeSetting("brand_color_2", value);
      setColour2(value);
    }, value ? "Second colour saved." : "Second colour removed.");

  const saveOwnColours = (value: boolean) =>
    run(async () => {
      await api.changeSetting("allow_personal_look", value);
      setOwnColours(value);
    }, value
      ? "People may pick their own colours and font again."
      : "Everyone now sees the workspace's colours and font. Light / dark, sizes and accessibility stay theirs.");

  return (
    <section className="space-y-4">
      <div>
        <h3 className="text-base font-bold text-gray-900 dark:text-white">Branding</h3>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Your organisation&apos;s logo and second colour. App name and main colour: Settings → Look. Email
          sender: Connections → Email.
        </p>
      </div>
      {error && <div role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {message && <div role="status" className="text-sm text-eko-dark dark:text-eko">{message}</div>}
      {logo === undefined && !error && <div className="text-sm text-gray-500">Loading…</div>}
      {logo !== undefined && (
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-3">
            <div className="text-sm font-semibold text-gray-900 dark:text-white">Logo</div>
            <div className="h-16 flex items-center px-3 rounded-lg bg-navy-900">
              <BrandLogo height={36} logo={logo} name={name} />
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {logo ? "Your organisation's logo." : "The app's own logo (none uploaded)."} PNG, JPEG or WEBP, up to 2 MB.
            </p>
            {canChange && (
              <div className="flex flex-wrap gap-2">
                <input
                  ref={file}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    // Cleared only after the upload has read the file (so the
                    // same file can be chosen again); clearing first sent an
                    // empty file.
                    const box = e.target;
                    if (f) void upload(f).finally(() => { box.value = ""; });
                  }}
                />
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => file.current?.click()}
                  className="px-3 py-1.5 rounded-lg text-sm font-semibold bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
                >
                  {logo ? "Change logo" : "Upload logo"}
                </button>
                {logo && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={remove}
                    className="px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
                  >
                    Remove
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-3">
            <div className="text-sm font-semibold text-gray-900 dark:text-white">Second colour</div>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={colour2 || "#1e293b"}
                disabled={!canChange || busy}
                aria-label="Second colour"
                onChange={(e) => setColour2(e.target.value)}
                className={`h-9 w-12 rounded border border-gray-200 dark:border-gray-600 ${colour2 ? "" : "opacity-60"}`}
              />
              <span className="text-sm font-mono text-gray-700 dark:text-gray-200">{colour2 || "None"}</span>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">The strip behind the logo on the Admin pages.</p>
            {canChange && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy || !colour2}
                  onClick={() => saveColour2(colour2)}
                  className="px-3 py-1.5 rounded-lg text-sm font-semibold bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
                >
                  Save colour
                </button>
                {colour2 && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => saveColour2("")}
                    className="px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
                  >
                    None
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-gray-900 dark:text-white">People pick their own colours</div>
              <button
                type="button"
                role="switch"
                aria-checked={ownColours}
                aria-label="People may pick their own colours and font"
                disabled={!canChange || busy}
                onClick={() => saveOwnColours(!ownColours)}
                className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
                  ownColours ? "bg-eko" : "bg-gray-300 dark:bg-gray-600"}`}
              >
                <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${
                  ownColours ? "translate-x-5" : "translate-x-0.5"}`} />
              </button>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              On: each person may choose their own colours and font (Settings &amp; appearance). Off: everyone sees
              this workspace&apos;s. Light / dark, sizes, layout and accessibility always stay each person&apos;s.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
