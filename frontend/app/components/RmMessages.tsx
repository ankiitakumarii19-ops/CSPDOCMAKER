"use client";

/**
 * RM portal → Messages (No. 192): send a CSP their data verification link,
 * as many times as needed. Each send makes a NEW link that works for 3 days
 * (DATA_REQUEST_EXPIRY_DAYS); the earlier one stops working once the new
 * one reaches the CSP. Every link sent is listed: when, how, valid until,
 * and whether it was filled, ran out or was replaced. A custom message and
 * the CSP's WhatsApp chat are here too.
 *
 * RMs act on their own (and unowned) CSPs; the server checks. The usual
 * rules stay: nothing to a CSP on hold, and an existing CSP (in CSPDATA
 * before the import) is never sent the details form.
 */

import { useCallback, useEffect, useState } from "react";

import CspChat from "../admin/CspChat";
import { api } from "../lib/api";
import type { ApiError, CSPDetail, CspSendResult, VerificationLinks } from "../lib/api";

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

const STATE: Record<string, { label: string; cls: string }> = {
  waiting: { label: "Waiting — link works", cls: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300" },
  filled: { label: "Filled", cls: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300" },
  "ran out": { label: "Ran out", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  replaced: { label: "Closed — a newer link or details came", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  "not delivered": { label: "Not delivered", cls: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
};

const card = "bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 sm:p-6";
const h3 = "text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-2";

export default function RmMessages() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CSPDetail[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [cspId, setCspId] = useState<string | null>(null);

  const [data, setData] = useState<VerificationLinks | null>(null);
  const [loadError, setLoadError] = useState("");
  const [channel, setChannel] = useState("whatsapp");
  const [sending, setSending] = useState<"" | "link" | "custom">("");
  const [sent, setSent] = useState<CspSendResult | null>(null);
  const [text, setText] = useState("");
  const [chat, setChat] = useState(false);

  // Search as they type (2+ characters), like the Documents tab.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) return;
    const t = setTimeout(() => {
      setSearching(true);
      api
        .searchCSP(q, 20)
        .then((r) => {
          setResults(r.results);
          setSearchError("");
        })
        .catch((e) => setSearchError((e as ApiError).detail || "Search failed."))
        .finally(() => setSearching(false));
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback((id: string) => {
    api
      .cspVerificationLinks(id)
      .then((d) => {
        setData(d);
        setLoadError("");
        const first = d.channels.find((c) => c.can_send);
        if (first) setChannel((prev) => (d.channels.find((c) => c.kind === prev && c.can_send) ? prev : first.kind));
      })
      .catch((e) => {
        setData(null);
        setLoadError((e as ApiError).detail || "Could not open this CSP.");
      });
  }, []);

  const pick = (id: string) => {
    setCspId(id);
    setSent(null);
    setData(null);
    setLoadError("");
    load(id);
  };

  // Results only for 2+ characters; shorter shows nothing (and no error).
  const longEnough = query.trim().length >= 2;
  const shown = longEnough ? results : [];

  const send = async (kind: "details_form" | "custom") => {
    if (!data) return;
    setSending(kind === "details_form" ? "link" : "custom");
    setSent(null);
    try {
      setSent(await api.messageCsp(data.csp_id, { kind, channel, text: kind === "custom" ? text : "" }));
      if (kind === "custom") setText("");
      load(data.csp_id);
    } catch (e) {
      setSent({
        csp_id: data.csp_id, sent: false, channel, kind, text: "",
        reason: (e as ApiError).detail || "Could not send.",
      });
    } finally {
      setSending("");
    }
  };

  const usable = data?.channels.filter((c) => c.can_send) ?? [];
  const waiting = data?.links.find((l) => l.state === "waiting");

  return (
    <div className="space-y-6">
      <div className={card}>
        <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-1">
          <i className="fas fa-paper-plane mr-2 text-eko"></i>Messages
        </h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Send a CSP their data verification link — as often as needed. Each send makes a new link that
          works for 3 days; the earlier link stops working once the new one reaches them.
        </p>
        <label className={h3} htmlFor="rm-msg-search">Find a CSP</label>
        <div className="relative">
          <i className="fas fa-search absolute left-4 top-1/2 -translate-y-1/2 text-gray-400"></i>
          <input
            id="rm-msg-search"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="CSP code, name, phone or email"
            className="w-full pl-11 pr-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
          />
        </div>
        {longEnough && searching && <p className="text-xs text-gray-500 mt-2">Searching…</p>}
        {longEnough && searchError && <p className="text-sm text-red-600 mt-2">{searchError}</p>}
        {longEnough && !searching && shown.length === 0 && !searchError && (
          <p className="text-sm text-gray-500 mt-2">No CSP matches.</p>
        )}
        {shown.length > 0 && (
          <ul className="mt-3 divide-y divide-gray-100 dark:divide-gray-700 border border-gray-200 dark:border-gray-700 rounded-lg max-h-72 overflow-y-auto">
            {shown.map((r) => (
              <li key={r.csp_id}>
                <button
                  onClick={() => pick(r.csp_id)}
                  className={`w-full text-left px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-700 ${
                    cspId === r.csp_id ? "bg-eko/10" : ""
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-x-2">
                    <span className="font-semibold text-sm text-gray-900 dark:text-white">{r.name}</span>
                    <span className="text-xs font-mono text-gray-500">{r.csp_id}</span>
                    {r.can_act === false && (
                      <span className="text-xs text-gray-500">· another RM&apos;s CSP (view only)</span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500">
                    {[r.mobile, r.district, r.state].filter(Boolean).join(" · ")}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {cspId && (
        <div className={card}>
          {loadError && <p className="text-sm text-red-600">{loadError}</p>}
          {!data && !loadError && <p className="text-sm text-gray-500">Loading…</p>}
          {data && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                    {data.name || data.csp_id}{" "}
                    <span className="text-sm font-mono text-gray-500">{data.csp_id}</span>
                  </h3>
                  <p className="text-sm text-gray-500">
                    {[data.mobile && `WhatsApp ${data.mobile}`, data.email].filter(Boolean).join(" · ") ||
                      "No phone or email on record"}
                  </p>
                </div>
                <button
                  onClick={() => setChat(true)}
                  className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                >
                  <i className="fab fa-whatsapp mr-1.5"></i>Open chat
                </button>
              </div>

              <section>
                <h4 className={h3}>Data verification link</h4>
                {waiting && (
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                    Their current link works until {when(waiting.valid_until)}. Sending again replaces it.
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={channel}
                    onChange={(e) => setChannel(e.target.value)}
                    aria-label="Send by"
                    className="px-2 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm dark:text-white"
                  >
                    {data.channels.map((c) => (
                      <option key={c.kind} value={c.kind} disabled={!c.can_send}>
                        {c.label}{c.can_send ? "" : " — not available"}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => send("details_form")}
                    disabled={!!sending || !!data.refusal || usable.length === 0}
                    className="px-4 py-2 rounded-lg bg-eko hover:bg-eko-dark disabled:opacity-50 text-white text-sm font-medium"
                  >
                    {sending === "link" ? "Sending…" : waiting ? "Send a new link" : "Send verification link"}
                  </button>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  The usual data verification message with a link valid for {data.valid_days} days.
                </p>
                {data.refusal && (
                  <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">Cannot be sent: {data.refusal}</p>
                )}
                {usable.length === 0 && (
                  <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">
                    No channel can send right now: {data.channels.map((c) => `${c.label} — ${c.why_not}`).join(" · ")}
                  </p>
                )}
              </section>

              <section>
                <h4 className={h3}>Your own message</h4>
                <textarea
                  rows={2}
                  value={text}
                  maxLength={900}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Namaste {name}, …"
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white"
                />
                <div className="flex flex-wrap items-center gap-2 mt-1">
                  <button
                    onClick={() => send("custom")}
                    disabled={!!sending || !!data.on_hold || usable.length === 0 || !text.trim()}
                    className="px-4 py-1.5 rounded-lg border border-eko text-eko hover:bg-eko/10 disabled:opacity-50 text-sm"
                  >
                    {sending === "custom" ? "Sending…" : "Send message"}
                  </button>
                  <span className="text-xs text-gray-500">{"{name}"}, {"{csp_id}"} and {"{missing_items}"} are filled in.</span>
                </div>
              </section>

              {sent && (
                <p className={`text-sm ${sent.sent ? "text-green-700 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                  {sent.sent
                    ? sent.kind === "details_form"
                      ? `New link sent — it works for ${data.valid_days} days.`
                      : "Message sent."
                    : `Not sent: ${sent.reason}`}
                </p>
              )}

              <section>
                <h4 className={h3}>Links sent ({data.links.length})</h4>
                {data.links.length === 0 ? (
                  <p className="text-sm text-gray-500">No link has been sent to this CSP yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {data.links.map((l, i) => {
                      const s = STATE[l.state] ?? { label: l.state, cls: STATE["ran out"].cls };
                      return (
                        <li key={i} className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-medium text-gray-900 dark:text-white">Sent {when(l.sent_at)}</span>
                            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${s.cls}`}>{s.label}</span>
                          </div>
                          <div className="text-xs text-gray-500 mt-0.5">
                            {l.via ? `${l.via === "whatsapp" ? "WhatsApp" : "Email"} to ${l.to}` : "—"}
                            {" · "}
                            {l.state === "filled" ? `filled ${when(l.answered_at)}` : `valid until ${when(l.valid_until)}`}
                          </div>
                          {l.error && <div className="text-xs text-red-600 mt-0.5">{l.error}</div>}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            </div>
          )}
        </div>
      )}
      {chat && data && <CspChat cspId={data.csp_id} onClose={() => setChat(false)} />}
    </div>
  );
}
