"use client";

/**
 * Ask-anything chat (tracker No. 114; no AI model since No. 116).
 *
 * A round button bottom-right on the Admin and RM screens. Ask about a CSP in
 * English, Hindi or Hinglish: its documents (Download / Share), its contacts
 * (RBO, RM, ASM, DC, branch), what is missing, or "remind <code> to …".
 * Process questions are answered from the Knowledge Base (Admin → Knowledge
 * Base). The server answers by fixed rules, so the same question always gets
 * the same answer, and everything shown comes from the records.
 * A message is only ever a DRAFT here until the person presses Send.
 * RMs get answers about their own CSPs only (enforced by the server).
 */

import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type {
  ApiError,
  AssistantActionResult,
  AssistantCard,
  AssistantDocument,
  AssistantSendResult,
  AssistantTurn,
} from "../lib/api";

interface Entry {
  role: "user" | "assistant" | "error";
  content: string;
  cards?: AssistantCard[];
  suggestions?: string[];
}

const EXAMPLES = [
  "Do you have the documents of CSP 1A850466?",
  "RBO contact number of CSP 1A851727",
  "What is missing for 1A851727?",
  "How many CSPs without photo?",
  "Remind CSP 1A851727 to send their photo by Friday",
  "What is a BCP?",
];

function errorText(e: unknown): string {
  const err = e as ApiError;
  return err?.detail || "Something went wrong. Please try again.";
}

/** **bold**, "- " lists and line breaks — no HTML is ever injected. */
function Rich({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((raw, i) => {
        // A Markdown table, should the model write one: the |---| rule is
        // dropped and each row shows as one line of cells.
        if (/^\s*\|[\s:|-]+\|\s*$/.test(raw)) return null;
        const line = /^\s*\|.*\|\s*$/.test(raw)
          ? raw.trim().slice(1, -1).split("|").map((c) => c.trim()).join(" · ")
          : raw;
        const bullet = /^\s*[-*•]\s+/.test(line);
        const body = bullet ? line.replace(/^\s*[-*•]\s+/, "") : line;
        const parts = body.split(/(\*\*[^*]+\*\*)/g).map((p, j) =>
          p.startsWith("**") && p.endsWith("**") ? (
            <strong key={j}>{p.slice(2, -2)}</strong>
          ) : (
            <span key={j}>{p}</span>
          )
        );
        if (!body.trim()) return <div key={i} className="h-2" />;
        return bullet ? (
          <div key={i} className="flex gap-2 pl-1">
            <span>•</span>
            <span>{parts}</span>
          </div>
        ) : (
          <div key={i}>{parts}</div>
        );
      })}
    </>
  );
}

function DocumentRow({ doc }: { doc: AssistantDocument }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function file(): Promise<File> {
    const blob = await api.assistantDocument(doc.id);
    return new File([blob], doc.filename, { type: "application/pdf" });
  }

  async function download() {
    setBusy(true);
    setError("");
    try {
      const f = await file();
      const url = URL.createObjectURL(f);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function share() {
    setBusy(true);
    setError("");
    try {
      const f = await file();
      if (!navigator.canShare?.({ files: [f] })) {
        setError("This browser cannot share files. Download it instead.");
        return;
      }
      await navigator.share({ files: [f], title: doc.filename });
    } catch (e) {
      // Closing the share sheet is not an error.
      if ((e as DOMException)?.name !== "AbortError") setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const canShare =
    typeof navigator !== "undefined" && typeof navigator.share === "function";

  return (
    <div className="py-1.5">
      <div className="flex items-center gap-2">
        <i className="fas fa-file-pdf text-red-500"></i>
        <div className="flex-1 min-w-0">
          <div className="text-sm text-gray-900 dark:text-white truncate">
            {doc.label}
          </div>
          <div className="text-xs text-gray-500">
            Version {doc.version}
            {doc.versions > 1 ? ` (latest of ${doc.versions})` : ""} ·{" "}
            {Math.max(1, Math.round(doc.size / 1024))} KB
          </div>
        </div>
        <button
          onClick={download}
          disabled={busy}
          title="Download"
          className="px-2.5 py-1 text-xs rounded-md bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
        >
          <i className="fas fa-download"></i>
        </button>
        {canShare && (
          <button
            onClick={share}
            disabled={busy}
            title="Share (WhatsApp, email…)"
            className="px-2.5 py-1 text-xs rounded-md border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            <i className="fas fa-share-nodes"></i>
          </button>
        )}
      </div>
      {error && <div className="text-xs text-red-600 dark:text-red-400 mt-1">{error}</div>}
    </div>
  );
}

function Documents({ docs }: { docs: AssistantDocument[] }) {
  if (docs.length === 0) {
    return <div className="text-sm text-gray-500">No documents stored yet.</div>;
  }
  return (
    <div className="divide-y divide-gray-100 dark:divide-gray-700">
      {docs.map((d) => (
        <DocumentRow key={d.id} doc={d} />
      ))}
    </div>
  );
}

function linkFor(key: string, value: string) {
  if (/(mobile|contact)/.test(key) && /\d{6,}/.test(value)) {
    return (
      <a href={`tel:${value.replace(/[^\d+]/g, "")}`} className="text-eko hover:underline">
        {value}
      </a>
    );
  }
  if (/email/.test(key) && value.includes("@")) {
    return (
      <a href={`mailto:${value}`} className="text-eko hover:underline">
        {value}
      </a>
    );
  }
  return value;
}

function Draft({ card }: { card: Extract<AssistantCard, { type: "draft" }> }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AssistantSendResult | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const [error, setError] = useState("");

  const done = cancelled || (result && result.state !== "failed");

  async function send() {
    setBusy(true);
    setError("");
    try {
      setResult(await api.assistantSend(card.id));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    setError("");
    try {
      await api.assistantCancel(card.id);
      setCancelled(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const how = card.channel === "whatsapp" ? "WhatsApp" : "Email";
  return (
    <div>
      <div className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">
        <i className={card.channel === "whatsapp" ? "fab fa-whatsapp mr-1" : "fas fa-envelope mr-1"}></i>
        Draft {how} — not sent yet
      </div>
      <div className="text-xs text-gray-500 mb-2">
        To {card.csp_name} ({card.csp_code}) · {card.to}
      </div>
      {card.subject && (
        <div className="text-xs text-gray-700 dark:text-gray-300 mb-1">
          <span className="text-gray-500">Subject:</span> {card.subject}
        </div>
      )}
      <div className="text-sm whitespace-pre-wrap rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 p-2.5 text-gray-900 dark:text-gray-100">
        {card.preview}
      </div>

      {result && result.state === "sent" && (
        <div className="mt-2 text-sm text-eko-dark dark:text-eko">
          <i className="fas fa-check-circle mr-1"></i>Sent by {how} to {result.to}.
        </div>
      )}
      {result && result.state === "pending" && (
        <div className="mt-2 text-sm text-amber-700 dark:text-amber-400">
          <i className="fas fa-clock mr-1"></i>
          {result.reason}
        </div>
      )}
      {result && (result.state === "rejected" || result.state === "failed") && (
        <div className="mt-2 text-sm text-red-600 dark:text-red-400">
          <i className="fas fa-circle-exclamation mr-1"></i>
          Not sent: {result.reason || "unknown reason"}
          {result.state === "failed" ? " — you can press Send again." : ""}
        </div>
      )}
      {cancelled && <div className="mt-2 text-sm text-gray-500">Cancelled — nothing was sent.</div>}
      {error && <div className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</div>}

      {!done && (
        <div className="flex gap-2 mt-2">
          <button
            onClick={send}
            disabled={busy}
            className="px-4 py-1.5 bg-eko hover:bg-eko-dark text-white text-sm font-medium rounded-lg disabled:opacity-50"
          >
            {busy ? "Sending…" : "Send"}
          </button>
          <button
            onClick={cancel}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

const STEP_STYLE: Record<string, { icon: string; tone: string }> = {
  done: { icon: "fa-circle-check", tone: "text-eko-dark dark:text-eko" },
  todo: { icon: "fa-circle", tone: "text-gray-400" },
  problem: { icon: "fa-triangle-exclamation", tone: "text-amber-600 dark:text-amber-400" },
  blocked: { icon: "fa-ban", tone: "text-red-600 dark:text-red-400" },
  optional: { icon: "fa-circle-half-stroke", tone: "text-gray-400" },
};

/** The Owner's setup checklist (No. 117): each step with what to do; a
 *  button asks the chat to explain the step or to offer doing it. */
function SetupChecklist({
  card,
  ask,
}: {
  card: Extract<AssistantCard, { type: "setup" }>;
  ask: (q: string) => void;
}) {
  return (
    <div>
      <div className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
        Setup — {card.done} of {card.total} essential steps done
      </div>
      <ul className="space-y-2">
        {card.steps.map((s) => {
          const style = STEP_STYLE[s.status] || STEP_STYLE.todo;
          return (
            <li key={s.key} className="flex gap-2">
              <i className={`fas ${style.icon} ${style.tone} mt-0.5 w-4 text-center`}></i>
              <div className="flex-1 min-w-0">
                <div className="text-sm text-gray-900 dark:text-gray-100">
                  <span className="font-semibold">{s.title}</span>{" "}
                  <span className={`text-xs ${style.tone}`}>{s.label}</span>
                </div>
                <div className="text-xs text-gray-600 dark:text-gray-400">{s.detail}</div>
                {s.status !== "done" && s.how && (
                  <div className="text-xs text-gray-500 mt-0.5">
                    <Rich text={s.how} />
                  </div>
                )}
                {s.status !== "done" && s.ask && (
                  <button
                    onClick={() => ask(s.ask as string)}
                    className="mt-1 px-2.5 py-1 rounded-full border border-gray-300 dark:border-gray-600 text-xs text-gray-700 dark:text-gray-200 hover:border-eko"
                  >
                    {/^(create|add|turn)/i.test(s.ask) ? "Do this for me" : "How?"}
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** A setup change the chat offers to make (No. 117). Nothing changes until
 *  the Owner presses Do it; the server runs it once and records it. */
function SetupAction({
  card,
  ask,
}: {
  card: Extract<AssistantCard, { type: "action" }>;
  ask: (q: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AssistantActionResult | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const [error, setError] = useState("");
  const finished = cancelled || result !== null;

  async function run() {
    setBusy(true);
    setError("");
    try {
      setResult(await api.assistantRunAction(card.id));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    setError("");
    try {
      await api.assistantCancelAction(card.id);
      setCancelled(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">
        <i className="fas fa-wand-magic-sparkles mr-1"></i>Setup — not done yet
      </div>
      <div className="text-sm font-semibold text-gray-900 dark:text-white">{card.title}</div>
      <div className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">{card.detail}</div>
      {card.extra.map((x, i) => (
        <div key={i} className="text-xs text-amber-700 dark:text-amber-400 mt-1">
          <Rich text={x} />
        </div>
      ))}

      {result && result.ok && (
        <div className="mt-2 text-sm text-eko-dark dark:text-eko">
          <i className="fas fa-check-circle mr-1"></i>
          {result.message}
        </div>
      )}
      {result && !result.ok && (
        <div className="mt-2 text-sm text-red-600 dark:text-red-400">
          <i className="fas fa-circle-exclamation mr-1"></i>
          Not done: {result.message}
        </div>
      )}
      {result && result.ok && result.next && (
        <button
          onClick={() => ask(result.next!.ask)}
          className="mt-2 px-2.5 py-1 rounded-full border border-gray-300 dark:border-gray-600 text-xs text-gray-700 dark:text-gray-200 hover:border-eko"
        >
          Next: {result.next.title}
        </button>
      )}
      {cancelled && <div className="mt-2 text-sm text-gray-500">Cancelled — nothing was changed.</div>}
      {error && <div className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</div>}

      {!finished && (
        <div className="flex gap-2 mt-2">
          <button
            onClick={run}
            disabled={busy}
            className="px-4 py-1.5 bg-eko hover:bg-eko-dark text-white text-sm font-medium rounded-lg disabled:opacity-50"
          >
            {busy ? "Working…" : "Do it"}
          </button>
          <button
            onClick={cancel}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

function Card({ card, ask }: { card: AssistantCard; ask: (q: string) => void }) {
  const box =
    "mt-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-3";
  if (card.type === "draft") {
    return (
      <div className={box}>
        <Draft card={card} />
      </div>
    );
  }
  if (card.type === "setup") {
    return (
      <div className={box}>
        <SetupChecklist card={card} ask={ask} />
      </div>
    );
  }
  if (card.type === "action") {
    return (
      <div className={box}>
        <SetupAction card={card} ask={ask} />
      </div>
    );
  }
  if (card.type === "csp_list") {
    return (
      <div className={box}>
        <div className="text-xs text-gray-500 mb-1">
          {card.total} match{card.total === 1 ? "" : "es"} for “{card.query}”
          {card.total > card.items.length ? ` — first ${card.items.length} shown` : ""}
        </div>
        {card.items.map((c) => (
          <button
            key={c.csp_code}
            onClick={() => ask(`Details of CSP ${c.csp_code}`)}
            className="w-full text-left py-1.5 px-1 rounded hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            <span className="font-mono text-xs text-gray-500 mr-2">{c.csp_code}</span>
            <span className="text-sm text-gray-900 dark:text-white">{c.name}</span>
            {c.district && <span className="text-xs text-gray-500"> · {c.district}</span>}
          </button>
        ))}
      </div>
    );
  }
  const header = (
    <div className="text-sm font-semibold text-gray-900 dark:text-white mb-1">
      {card.name} <span className="font-mono text-xs text-gray-500">({card.csp_code})</span>
    </div>
  );
  if (card.type === "documents") {
    return (
      <div className={box}>
        {header}
        <Documents docs={card.documents} />
      </div>
    );
  }
  return (
    <div className={box}>
      {header}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        {card.fields
          .filter((f) => f.key !== "csp_code" && f.key !== "name")
          .map((f) => (
            <div key={f.key} className="contents">
              <dt className="text-gray-500">{f.label}</dt>
              <dd className="text-gray-900 dark:text-gray-100 break-words">
                {linkFor(f.key, String(f.value))}
              </dd>
            </div>
          ))}
      </dl>
      {card.documents.length > 0 && (
        <details className="mt-2">
          <summary className="text-xs text-eko cursor-pointer">
            {card.documents.length} document{card.documents.length === 1 ? "" : "s"}
          </summary>
          <Documents docs={card.documents} />
        </details>
      )}
    </div>
  );
}

export default function AssistantChat() {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries, busy]);

  // A Workspace Owner whose workspace is not ready yet is shown the setup
  // checklist as soon as the chat opens (No. 117). Others: nothing changes.
  const [setupChecked, setSetupChecked] = useState(false);
  useEffect(() => {
    if (!open || setupChecked || entries.length > 0) return;
    setSetupChecked(true);
    api
      .assistantSetup()
      .then((s) => {
        if (s.owner && !s.complete && s.reply) {
          setEntries((now) =>
            now.length > 0
              ? now
              : [{ role: "assistant", content: s.reply as string, cards: s.cards || [] }]
          );
        }
      })
      .catch(() => {
        // Not knowing the setup state must never block the chat itself;
        // asking "setup status" reports any failure with its Error ID.
      });
  }, [open, setupChecked, entries.length]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const next: Entry[] = [...entries, { role: "user", content: q }];
    setEntries(next);
    setInput("");
    setBusy(true);
    // Only the conversation's words go back; errors are not part of it.
    const history: AssistantTurn[] = next
      .filter((e) => e.role !== "error")
      .map((e) => ({ role: e.role as "user" | "assistant", content: e.content }));
    try {
      const answer = await api.assistantChat(history);
      setEntries([
        ...next,
        {
          role: "assistant",
          content: answer.reply,
          cards: answer.cards,
          suggestions: answer.suggestions,
        },
      ]);
    } catch (e) {
      setEntries([...next, { role: "error", content: errorText(e) }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          title="Ask about any CSP"
          className="fixed bottom-5 right-5 z-40 w-14 h-14 rounded-full bg-eko hover:bg-eko-dark text-white shadow-lg flex items-center justify-center"
        >
          <i className="fas fa-comments text-xl"></i>
        </button>
      )}

      {open && (
        <div className="fixed z-50 bottom-0 right-0 sm:bottom-5 sm:right-5 w-full sm:w-[420px] h-[85vh] sm:h-[620px] max-h-screen flex flex-col rounded-t-2xl sm:rounded-2xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 shadow-2xl">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 rounded-t-2xl">
            <i className="fas fa-comments text-eko"></i>
            <div className="flex-1">
              <div className="text-sm font-bold text-gray-900 dark:text-white">Ask about any CSP</div>
              <div className="text-xs text-gray-500">Documents, contacts, messages</div>
            </div>
            {entries.length > 0 && (
              <button
                onClick={() => setEntries([])}
                title="New chat"
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 px-2"
              >
                <i className="fas fa-rotate-right"></i>
              </button>
            )}
            <button
              onClick={() => setOpen(false)}
              title="Close (Esc)"
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 px-2"
            >
              <i className="fas fa-xmark text-lg"></i>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {entries.length === 0 && (
              <div className="text-sm text-gray-600 dark:text-gray-400">
                <p className="mb-3">
                  Ask in English, Hindi or Hinglish. Answers come straight from the app&apos;s
                  records and the Knowledge Base — no AI. Messages are shown to you as a draft
                  first — nothing is sent until you press <strong>Send</strong>.
                </p>
                <div className="space-y-2">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex}
                      onClick={() => ask(ex)}
                      className="block w-full text-left px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-eko text-gray-700 dark:text-gray-200"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {entries.map((e, i) =>
              e.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-eko text-white text-sm px-3 py-2 whitespace-pre-wrap">
                    {e.content}
                  </div>
                </div>
              ) : e.role === "error" ? (
                <div
                  key={i}
                  className="px-3 py-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300"
                >
                  <i className="fas fa-circle-exclamation mr-2"></i>
                  {e.content}
                </div>
              ) : (
                <div key={i}>
                  <div className="max-w-[95%] rounded-2xl rounded-bl-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-sm text-gray-900 dark:text-gray-100 px-3 py-2">
                    <Rich text={e.content} />
                  </div>
                  {e.cards?.map((c, j) => (
                    <Card key={j} card={c} ask={ask} />
                  ))}
                  {i === entries.length - 1 && e.suggestions && e.suggestions.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {e.suggestions.map((sg) => (
                        <button
                          key={sg}
                          onClick={() => ask(sg)}
                          disabled={busy}
                          className="px-2.5 py-1 rounded-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-xs text-gray-700 dark:text-gray-200 hover:border-eko disabled:opacity-50"
                        >
                          {sg}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )
            )}

            {busy && (
              <div className="text-sm text-gray-500">
                <i className="fas fa-circle-notch fa-spin mr-2"></i>Looking it up…
              </div>
            )}
            <div ref={endRef} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(input);
            }}
            className="flex gap-2 p-3 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 sm:rounded-b-2xl"
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(input);
                }
              }}
              rows={1}
              maxLength={2000}
              placeholder="e.g. RBO number of 1A851727"
              className="flex-1 resize-none px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-eko"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              title="Ask"
              className="px-3 rounded-lg bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
            >
              <i className="fas fa-paper-plane"></i>
            </button>
          </form>
        </div>
      )}
    </>
  );
}
