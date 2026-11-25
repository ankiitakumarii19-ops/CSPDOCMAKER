"use client";

/**
 * Document templates → Signatures (No. 247)
 *
 * Upload signature pictures, then say which one goes on which document:
 *   "on <this document | every document>, when <column> is <values>
 *    (or: every other CSP), print <signature>".
 * The first rule that matches, from the top, wins. With no rule matching, a
 * document is made exactly as before (its own signature).
 *
 * With `code`, the screen is one document's Signature tab: where its
 * signature sits (a picture inside the file, or a line of text that becomes
 * the signature) and the rules that apply to it.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError,
  SignatureOverview,
  SignatureRule,
  SignatureRuleInput,
  SignatureSpot,
} from "../lib/api";

const box =
  "rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-3";
const input =
  "px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white";
const primary =
  "px-4 py-2 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm font-medium rounded-lg";
const plain =
  "px-3 py-1.5 text-sm rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40";

/** A picture that needs the sign-in to load. */
function Picture({ path, alt, className }: { path: string; alt: string; className?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    let made: string | null = null;
    api
      .pictureUrl(path)
      .then((u) => {
        made = u;
        if (alive) setUrl(u);
        else URL.revokeObjectURL(u);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [path]);
  if (failed) return <div className={`${className} text-xs text-red-600`}>Could not load</div>;
  if (!url) return <div className={`${className} bg-gray-100 dark:bg-gray-700 animate-pulse`} />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={alt} className={`${className} object-contain bg-white`} />;
}

const EMPTY: SignatureRuleInput = {
  document_code: null,
  column: "lho",
  values: [],
  signature_id: "",
  active: true,
};

export default function Signatures({ code }: { code?: string }) {
  const [data, setData] = useState<SignatureOverview | null>(null);
  const [spot, setSpot] = useState<SignatureSpot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // upload
  const [newName, setNewName] = useState("");
  const [newFile, setNewFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);

  // rule form
  const [form, setForm] = useState<SignatureRuleInput | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [known, setKnown] = useState<{ value: string; count: number }[]>([]);
  const [extra, setExtra] = useState("");

  // checker
  const [checkCsp, setCheckCsp] = useState("");
  const [checkDoc, setCheckDoc] = useState(code ?? "");
  const [answer, setAnswer] = useState("");

  const load = useCallback(async () => {
    try {
      const [o, s] = await Promise.all([
        api.signatures(),
        code ? api.signatureSpot(code) : Promise.resolve(null),
      ]);
      setData(o);
      setSpot(s);
      setError("");
    } catch (e) {
      setError((e as ApiError).detail || "Could not load the signatures.");
    }
  }, [code]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const column = form?.column;
    if (!column) return;
    let alive = true;
    api
      .signatureColumnValues(column)
      .then((v) => alive && setKnown(v.values))
      .catch(() => alive && setKnown([]));
    return () => {
      alive = false;
    };
  }, [form?.column]);

  async function run(work: () => Promise<string | void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const message = await work();
      if (message) setNotice(message);
      await load();
    } catch (e) {
      setError((e as ApiError).detail || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const rules: SignatureRule[] = useMemo(
    () => (data?.rules ?? []).filter((r) => !code || !r.document_code || r.document_code === code),
    [data, code]
  );

  if (!data) {
    return (
      <div className="p-5 text-sm text-gray-500">
        {error ? <span className="text-red-600">{error}</span> : "Loading…"}
      </div>
    );
  }

  const upload = () =>
    run(async () => {
      if (!newFile) return;
      const made = await api.uploadSignature(newName.trim(), newFile);
      setNewName("");
      setNewFile(null);
      setFileKey((k) => k + 1);
      return `Signature “${made.name}” added. Now add a rule to say where it goes.`;
    });

  const startRule = (rule?: SignatureRule) => {
    setExtra("");
    if (rule) {
      setEditing(rule.id);
      setForm({
        document_code: rule.document_code,
        column: rule.column,
        values: rule.values,
        signature_id: rule.signature_id,
        active: rule.active,
      });
    } else {
      setEditing(null);
      setForm({ ...EMPTY, document_code: code ?? null, signature_id: data.signatures[0]?.id ?? "" });
    }
  };

  const saveRule = () =>
    run(async () => {
      if (!form) return;
      const values = extra.trim()
        ? [...form.values, ...extra.split(",").map((v) => v.trim()).filter(Boolean)]
        : form.values;
      const body = { ...form, values: form.column ? values : [] };
      if (editing) await api.changeSignatureRule(editing, body);
      else await api.addSignatureRule(body);
      setForm(null);
      setEditing(null);
      return editing ? "Rule saved." : "Rule added. It is used for documents made from now on.";
    });

  const move = (id: string, by: number) =>
    run(async () => {
      const ids = data.rules.map((r) => r.id);
      const at = ids.indexOf(id);
      const to = at + by;
      if (at < 0 || to < 0 || to >= ids.length) return;
      [ids[at], ids[to]] = [ids[to], ids[at]];
      await api.orderSignatureRules(ids);
      return "Order saved.";
    });

  const toggle = (r: SignatureRule) =>
    run(async () => {
      await api.changeSignatureRule(r.id, {
        document_code: r.document_code,
        column: r.column,
        values: r.values,
        signature_id: r.signature_id,
        active: !r.active,
      });
      return r.active ? "Rule switched off." : "Rule switched on.";
    });

  const check = () =>
    run(async () => {
      setAnswer("");
      const doc = code ?? checkDoc;
      const w = await api.whichSignature(doc, checkCsp.trim());
      setAnswer(w.signature ? `${w.signature} — ${w.why}` : w.why);
    });

  const columnLabel = (key: string) => data.columns.find((c) => c.key === key)?.label ?? key;
  const canAddRule = data.signatures.length > 0;

  return (
    <div className={code ? "p-5 space-y-4" : "space-y-4"}>
      {error && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 text-sm px-4 py-3">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-sm px-4 py-3">
          {notice}
        </div>
      )}

      {/* Where the signature sits in this document */}
      {code && spot && (
        <div className={box}>
          <h4 className="font-semibold text-gray-900 dark:text-white">Where the signature goes</h4>
          {spot.spot ? (
            <p className="text-sm text-gray-600 dark:text-gray-300">
              {spot.spot.startsWith("picture:")
                ? "The picture marked below is replaced by the chosen signature, in the same box."
                : `The line “${spot.spot.slice(5)}” is replaced by the chosen signature.`}
              {!spot.chosen && " (This is the document's own signature picture.)"}
            </p>
          ) : (
            <p className="text-sm text-amber-700 dark:text-amber-300">
              Not chosen yet — click the picture that is the signature, or pick the line of text
              where the signature should be printed.
            </p>
          )}
          {!spot.found && (
            <p className="text-sm text-red-600">
              The chosen place is not in this document&apos;s current file (a new file may have
              been uploaded). Choose it again, or documents with a signature rule will not be made.
            </p>
          )}
          {spot.pictures.length > 0 && (
            <div className="flex flex-wrap gap-3">
              {spot.pictures.map((p) => {
                const chosen = spot.spot === `picture:${p.checksum}`;
                return (
                  <button
                    key={p.checksum}
                    disabled={busy}
                    onClick={() =>
                      run(async () => {
                        await api.setSignatureSpot(code, `picture:${p.checksum}`);
                        return "This picture is now the signature's place.";
                      })
                    }
                    className={`rounded-lg border-2 p-2 text-left ${
                      chosen ? "border-eko" : "border-gray-200 dark:border-gray-700 hover:border-gray-400"
                    }`}
                    title="Use this picture as the signature's place"
                  >
                    <Picture
                      path={api.documentPicturePath(code, p.checksum)}
                      alt="Picture in the document"
                      className="h-20 w-36 rounded"
                    />
                    <div className="mt-1 text-xs text-gray-500">
                      {chosen ? "✓ Signature" : "Use as signature"}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <select
              className={`${input} max-w-full sm:max-w-md`}
              value={spot.spot?.startsWith("text:") ? spot.spot.slice(5) : ""}
              disabled={busy}
              onChange={(e) =>
                e.target.value &&
                run(async () => {
                  await api.setSignatureSpot(code, `text:${e.target.value}`);
                  return "That line is now where the signature is printed.";
                })
              }
            >
              <option value="">…or print it in place of a line of text</option>
              {spot.paragraphs.map((p, i) => (
                <option key={i} value={p.text.trim()}>
                  {p.text.trim().slice(0, 90)}
                </option>
              ))}
            </select>
            {spot.chosen && (
              <button
                className={plain}
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await api.setSignatureSpot(code, null);
                    return "Back to the document's own signature picture.";
                  })
                }
              >
                Clear my choice
              </button>
            )}
          </div>
        </div>
      )}

      {/* The signature pictures */}
      {!code && (
        <div className={box}>
          <h4 className="font-semibold text-gray-900 dark:text-white">Signature pictures</h4>
          {data.signatures.length === 0 && (
            <p className="text-sm text-gray-500">
              None yet. Upload a signature (or signature with stamp) as a PNG, JPEG or WEBP.
            </p>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.signatures.map((s) => (
              <div key={s.id} className="rounded-lg border border-gray-200 dark:border-gray-700 p-3 space-y-2">
                <Picture path={api.signaturePicturePath(s.id)} alt={s.name} className="h-20 w-full rounded" />
                <div className="font-medium text-sm text-gray-900 dark:text-white break-words">{s.name}</div>
                <div className="text-xs text-gray-500">
                  {s.used_by ? `Used by ${s.used_by} rule(s)` : "Not used by any rule"}
                </div>
                <div className="flex gap-2">
                  <button
                    className={plain}
                    disabled={busy}
                    onClick={() => {
                      const name = window.prompt("New name", s.name);
                      if (name && name.trim() !== s.name)
                        run(async () => {
                          await api.renameSignature(s.id, name);
                          return "Renamed.";
                        });
                    }}
                  >
                    Rename
                  </button>
                  <button
                    className={plain}
                    disabled={busy || s.used_by > 0}
                    title={s.used_by ? "Remove or change its rules first" : undefined}
                    onClick={() =>
                      window.confirm(`Remove the signature “${s.name}”?`) &&
                      run(async () => {
                        await api.removeSignature(s.id);
                        return "Signature removed.";
                      })
                    }
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-700">
            <label className="text-sm text-gray-600 dark:text-gray-300 flex flex-col gap-1">
              Name
              <input
                className={input}
                value={newName}
                placeholder="e.g. North region head"
                onChange={(e) => setNewName(e.target.value)}
              />
            </label>
            <label className="text-sm text-gray-600 dark:text-gray-300 flex flex-col gap-1">
              Picture
              <input
                key={fileKey}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="text-sm"
                onChange={(e) => setNewFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <button className={primary} disabled={busy || !newFile || !newName.trim()} onClick={upload}>
              Upload signature
            </button>
          </div>
        </div>
      )}

      {/* The rules */}
      <div className={box}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h4 className="font-semibold text-gray-900 dark:text-white">
            {code ? "Which signature this document gets" : "Which signature goes where"}
          </h4>
          <button
            className={primary}
            disabled={busy || !canAddRule}
            title={canAddRule ? undefined : "Upload a signature picture first (Document templates → Signatures)"}
            onClick={() => startRule()}
          >
            Add a rule
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Rules are tried from the top; the first that matches the CSP decides. When none matches,
          the document keeps its own signature, as before.
          {code && " Rules for every document are shown here too; change their order on Signatures."}
        </p>
        {rules.length === 0 && <p className="text-sm text-gray-500">No rules yet.</p>}
        <ul className="divide-y divide-gray-100 dark:divide-gray-700">
          {rules.map((r) => {
            const at = data.rules.findIndex((x) => x.id === r.id);
            return (
              <li key={r.id} className="py-2 flex flex-wrap items-center gap-2">
                <span className="text-xs tabular-nums text-gray-400 w-6">{at + 1}.</span>
                <span
                  className={`flex-1 min-w-[12rem] text-sm ${
                    r.active ? "text-gray-900 dark:text-white" : "text-gray-400 line-through"
                  }`}
                >
                  {r.words}
                </span>
                {!code && (
                  <>
                    <button className={plain} disabled={busy || at === 0} onClick={() => move(r.id, -1)} aria-label="Move up">
                      ↑
                    </button>
                    <button
                      className={plain}
                      disabled={busy || at === data.rules.length - 1}
                      onClick={() => move(r.id, 1)}
                      aria-label="Move down"
                    >
                      ↓
                    </button>
                  </>
                )}
                <button className={plain} disabled={busy} onClick={() => toggle(r)}>
                  {r.active ? "Switch off" : "Switch on"}
                </button>
                <button className={plain} disabled={busy} onClick={() => startRule(r)}>
                  Change
                </button>
                <button
                  className={plain}
                  disabled={busy}
                  onClick={() =>
                    window.confirm("Remove this rule?") &&
                    run(async () => {
                      await api.removeSignatureRule(r.id);
                      return "Rule removed.";
                    })
                  }
                >
                  Remove
                </button>
              </li>
            );
          })}
        </ul>

        {form && (
          <div className="rounded-lg bg-gray-50 dark:bg-gray-900/40 p-3 space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <label className="text-sm text-gray-600 dark:text-gray-300 flex flex-col gap-1">
                On
                <select
                  className={input}
                  value={form.document_code ?? ""}
                  onChange={(e) => setForm({ ...form, document_code: e.target.value || null })}
                >
                  <option value="">Every document</option>
                  {data.documents.map((d) => (
                    <option key={d.code} value={d.code}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-sm text-gray-600 dark:text-gray-300 flex flex-col gap-1">
                When
                <select
                  className={input}
                  value={form.column}
                  onChange={(e) => {
                    setKnown([]);
                    setForm({ ...form, column: e.target.value, values: [] });
                  }}
                >
                  {data.columns.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label} is…
                    </option>
                  ))}
                  <option value="">Every other CSP</option>
                </select>
              </label>
              <label className="text-sm text-gray-600 dark:text-gray-300 flex flex-col gap-1">
                Print
                <select
                  className={input}
                  value={form.signature_id}
                  onChange={(e) => setForm({ ...form, signature_id: e.target.value })}
                >
                  {data.signatures.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {form.column && (
              <div className="space-y-2">
                <div className="text-sm text-gray-600 dark:text-gray-300">
                  {columnLabel(form.column)} is one of:
                  {form.values.length > 0 && (
                    <span className="ml-2 font-medium text-gray-900 dark:text-white">
                      {form.values.join(", ")}
                    </span>
                  )}
                </div>
                {known.length > 0 && form.column && (
                  <div className="max-h-48 overflow-y-auto flex flex-wrap gap-2">
                    {known.map((v) => {
                      const on = form.values.some((x) => x.toLowerCase() === v.value.toLowerCase());
                      return (
                        <button
                          key={v.value}
                          type="button"
                          onClick={() =>
                            setForm({
                              ...form,
                              values: on
                                ? form.values.filter((x) => x.toLowerCase() !== v.value.toLowerCase())
                                : [...form.values, v.value],
                            })
                          }
                          className={`px-2 py-1 rounded-full text-xs border ${
                            on
                              ? "bg-eko text-white border-eko"
                              : "border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200"
                          }`}
                        >
                          {v.value} <span className="opacity-70">({v.count})</span>
                        </button>
                      );
                    })}
                  </div>
                )}
                <input
                  className={`${input} w-full`}
                  value={extra}
                  placeholder="Other values, separated by commas"
                  onChange={(e) => setExtra(e.target.value)}
                />
              </div>
            )}

            <div className="flex gap-2">
              <button
                className={primary}
                disabled={busy || !form.signature_id || (!!form.column && form.values.length === 0 && !extra.trim())}
                onClick={saveRule}
              >
                {editing ? "Save rule" : "Add rule"}
              </button>
              <button className={plain} onClick={() => setForm(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Which signature would this CSP get? */}
      <div className={box}>
        <h4 className="font-semibold text-gray-900 dark:text-white">Check a CSP</h4>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className={input}
            value={checkCsp}
            placeholder="CSP ID"
            onChange={(e) => setCheckCsp(e.target.value)}
          />
          {!code && (
            <select className={input} value={checkDoc} onChange={(e) => setCheckDoc(e.target.value)}>
              <option value="">Choose a document</option>
              {data.documents.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                </option>
              ))}
            </select>
          )}
          <button className={plain} disabled={busy || !checkCsp.trim() || !(code ?? checkDoc)} onClick={check}>
            Which signature?
          </button>
        </div>
        {answer && <p className="text-sm text-gray-700 dark:text-gray-200">{answer}</p>}
        <p className="text-xs text-gray-500">
          To see the finished document, open the document and use Versions &amp; test → Test on a CSP.
        </p>
      </div>
    </div>
  );
}
