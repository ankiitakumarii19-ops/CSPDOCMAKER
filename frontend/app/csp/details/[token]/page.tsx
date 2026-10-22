"use client";

/**
 * The page a CSP fills their own details on.
 *
 * No login. The token in the URL is the whole credential, so this page
 * shows one person's own information and nothing else — no list, no
 * neighbouring record, no hierarchy.
 *
 * Everything is pre-filled: the CSP is confirming their record, not filling
 * a blank form, because a value already on file can be wrong and they are
 * the only person who would know.
 *
 * Bilingual throughout, and it says plainly that the form can be submitted
 * only once — in both languages, before the button rather than after it.
 */

import { use, useCallback, useEffect, useState } from "react";

import { withBase } from "../../../lib/basePath";

interface FormField {
  name: string;
  label: string;
  label_hi: string;
  type: string;
  value: string;
}

interface DocumentQuestion {
  name: string;
  label: string;
  label_hi: string;
  upload_label: string;
  upload_label_hi: string;
  value: string;
}

interface Choice {
  value: string;
  label: string;
}

interface FormData {
  csp_code: string;
  csp_name: string;
  fields: FormField[];
  documents: DocumentQuestion[];
  gender_choices: Choice[];
  yesno_choices: Choice[];
  expires_at: string;
  submit_once: boolean;
}

export default function CSPDetailsForm({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);

  const [form, setForm] = useState<FormData | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [gone, setGone] = useState<{ en: string; hi: string } | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ en: string; hi: string } | null>(null);
  // The CSP's own photo, sent the moment it is chosen (No. 102) — the link
  // stops working once the form is submitted, so it cannot wait for that.
  const [photo, setPhoto] = useState<
    { status: "idle" } | { status: "sending" } | { status: "sent"; en: string; hi: string } | { status: "failed"; text: string }
  >({ status: "idle" });

  const load = useCallback(async () => {
    try {
      const response = await fetch(withBase(`/api/csp-form/${encodeURIComponent(token)}`));
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        const detail = body?.detail;
        setGone({
          en: detail?.message ?? "This link is no longer usable.",
          hi: detail?.message_hi ?? "",
        });
        return;
      }
      const data: FormData = await response.json();
      setForm(data);
      const initial: Record<string, string> = {};
      data.fields.forEach((f) => (initial[f.name] = f.value));
      data.documents.forEach((d) => (initial[d.name] = d.value));
      setValues(initial);
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  async function submit() {
    setSaving(true);
    setError("");
    try {
      const response = await fetch(
        withBase(`/api/csp-form/${encodeURIComponent(token)}`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ values }),
        }
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(
          typeof body?.detail === "string"
            ? body.detail
            : body?.detail?.message ?? "Could not submit. Please try again."
        );
        return;
      }
      setDone({ en: body.message, hi: body.message_hi });
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  const set = (name: string, value: string) =>
    setValues((v) => ({ ...v, [name]: value }));

  async function sendPhoto(fieldName: string, file?: File) {
    if (!file) return;
    setPhoto({ status: "sending" });
    try {
      // globalThis: this page's own FormData type hides the browser's.
      const body = new globalThis.FormData();
      body.append("file", file);
      const response = await fetch(
        withBase(`/api/csp-form/${encodeURIComponent(token)}/photo`),
        { method: "POST", body }
      );
      const answer = await response.json().catch(() => ({}));
      if (!response.ok) {
        setPhoto({
          status: "failed",
          text:
            typeof answer?.detail === "string"
              ? answer.detail
              : answer?.detail?.message ?? "The photo could not be sent. Please try again.",
        });
        return;
      }
      set(fieldName, "on file");
      setPhoto({ status: "sent", en: answer.message, hi: answer.message_hi });
    } catch {
      setPhoto({ status: "failed", text: "Could not reach the server. Please try again." });
    }
  }

  // ---- states before the form ------------------------------------------

  if (loading) {
    return (
      <Shell>
        <p className="text-gray-500 text-center py-12">Loading…</p>
      </Shell>
    );
  }

  if (gone) {
    return (
      <Shell>
        <div className="text-center py-10 space-y-3">
          <i className="fas fa-link-slash text-3xl text-gray-400" />
          <p className="text-gray-800 dark:text-gray-200">{gone.en}</p>
          {gone.hi && <p className="text-gray-600 dark:text-gray-400">{gone.hi}</p>}
        </div>
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell>
        <div className="text-center py-10 space-y-3">
          <i className="fas fa-circle-check text-4xl text-eko" />
          <p className="text-lg font-medium text-gray-900 dark:text-white">
            {done.en}
          </p>
          <p className="text-gray-600 dark:text-gray-400">{done.hi}</p>
        </div>
      </Shell>
    );
  }

  if (!form) return null;

  // ---- the form ---------------------------------------------------------

  return (
    <Shell>
      <div className="space-y-6">
        <header className="space-y-1">
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">
            Confirm your details
          </h1>
          <p className="text-gray-600 dark:text-gray-400">
            अपनी जानकारी की पुष्टि करें
          </p>
          <p className="text-sm text-gray-500 pt-2">
            {form.csp_name} · {form.csp_code}
          </p>
        </header>

        {/* Said before the button, not after it. */}
        <div className="px-4 py-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-sm space-y-1">
          <p className="text-amber-900 dark:text-amber-200">
            Please check everything carefully. You can submit this form{" "}
            <strong>only once</strong>.
          </p>
          <p className="text-amber-800 dark:text-amber-300">
            कृपया सब कुछ ध्यान से जाँच लें। आप यह फ़ॉर्म{" "}
            <strong>केवल एक ही बार</strong> जमा कर सकते हैं।
          </p>
        </div>

        {error && (
          <div className="px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300">
            {error}
          </div>
        )}

        {/* Your details */}
        <section className="space-y-4">
          {form.fields.map((field) => (
            <div key={field.name}>
              <label className="block text-sm font-medium text-gray-800 dark:text-gray-200">
                {field.label}
                {field.label_hi && (
                  <span className="text-gray-500 font-normal">
                    {" "}/ {field.label_hi}
                  </span>
                )}
              </label>

              {field.type === "gender" ? (
                <div className="flex gap-4 mt-2">
                  {form.gender_choices.map((c) => (
                    <label
                      key={c.value}
                      className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300"
                    >
                      <input
                        type="radio"
                        name={field.name}
                        checked={values[field.name] === c.value}
                        onChange={() => set(field.name, c.value)}
                        className="accent-eko"
                      />
                      {c.label}
                    </label>
                  ))}
                </div>
              ) : field.type === "address" ? (
                <textarea
                  rows={3}
                  value={values[field.name] ?? ""}
                  onChange={(e) => set(field.name, e.target.value)}
                  className="mt-1 w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
                />
              ) : field.type === "photo" ? (
                <div className="mt-1 space-y-2">
                  <p className="text-sm text-gray-500">
                    {values[field.name]
                      ? "A photograph is on file. You can send a newer one. / फ़ोटो उपलब्ध है। आप नई फ़ोटो भेज सकते हैं।"
                      : "Please send a clear photo of your face, facing the camera. / कृपया अपने चेहरे की साफ़ फ़ोटो भेजें, कैमरे की ओर देखते हुए।"}
                  </p>
                  <label
                    className={`inline-block px-4 py-2 text-sm font-medium rounded-lg border border-eko text-eko cursor-pointer hover:bg-eko/10 ${
                      photo.status === "sending" ? "opacity-50 pointer-events-none" : ""
                    }`}
                  >
                    <i className="fas fa-camera mr-2"></i>
                    {photo.status === "sending"
                      ? "Sending… / भेजा जा रहा है…"
                      : "Choose or take a photo / फ़ोटो चुनें या लें"}
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        sendPhoto(field.name, file);
                      }}
                    />
                  </label>
                  {photo.status === "sent" && (
                    <p className="text-sm text-green-700 dark:text-green-400">
                      {photo.en} / {photo.hi}
                    </p>
                  )}
                  {photo.status === "failed" && (
                    <p className="text-sm text-red-600 dark:text-red-400">{photo.text}</p>
                  )}
                </div>
              ) : (
                <input
                  type={field.type === "email" ? "email" : "text"}
                  inputMode={field.type === "phone" ? "numeric" : undefined}
                  value={values[field.name] ?? ""}
                  onChange={(e) => set(field.name, e.target.value)}
                  className="mt-1 w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-eko"
                />
              )}
            </div>
          ))}
        </section>

        {/* Documents they may already hold */}
        {form.documents.length > 0 && (
          <section className="space-y-4 pt-2">
            <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500">
              Documents you already have / आपके पास मौजूद दस्तावेज़
            </h2>
            {form.documents.map((doc) => (
              <div
                key={doc.name}
                className="p-4 rounded-lg border border-gray-200 dark:border-gray-700"
              >
                <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
                  {doc.label}
                </p>
                {doc.label_hi && (
                  <p className="text-sm text-gray-500">{doc.label_hi}</p>
                )}
                <div className="flex gap-4 mt-2">
                  {form.yesno_choices.map((c) => (
                    <label
                      key={c.value}
                      className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300"
                    >
                      <input
                        type="radio"
                        name={doc.name}
                        checked={values[doc.name] === c.value}
                        onChange={() => set(doc.name, c.value)}
                        className="accent-eko"
                      />
                      {c.label}
                    </label>
                  ))}
                </div>
                {/* The upload only appears on Yes, as specified. */}
                {values[doc.name] === "Yes" && (
                  <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
                    <p className="text-sm text-gray-700 dark:text-gray-300">
                      {doc.upload_label}
                    </p>
                    <p className="text-xs text-gray-500">{doc.upload_label_hi}</p>
                    <p className="mt-2 text-xs text-gray-400">
                      Your RM will collect this from you. / आपका RM यह आपसे
                      प्राप्त करेगा।
                    </p>
                  </div>
                )}
              </div>
            ))}
          </section>
        )}

        <button
          onClick={submit}
          disabled={saving}
          className="w-full py-3 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg shadow-sm"
        >
          {saving ? "Submitting…" : "Submit / जमा करें"}
        </button>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  // The app's frame (layout.tsx) is one screen tall with scrolling off —
  // the admin and RM screens scroll inside their own panels. This page has
  // no panel, so it scrolls itself; without this a CSP on a phone could not
  // reach anything below the first screen (reported 21 Oct 2026).
  return (
    <div className="flex-1 min-h-0 h-full overflow-y-auto overscroll-contain bg-gray-50 dark:bg-gray-900 py-8 px-4">
      <div className="max-w-xl mx-auto bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 sm:p-8">
        {children}
      </div>
    </div>
  );
}
