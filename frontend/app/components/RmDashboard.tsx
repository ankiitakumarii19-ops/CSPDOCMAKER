"use client";

/**
 * RM portal → Dashboard (No. 234): every CSP still waiting for documents,
 * how many times each has been contacted (WhatsApps + emails that went
 * out), filtered by RM, DC, state and district. Every RM sees every CSP —
 * any RM may open, edit, send the link or send documents to any CSP.
 *
 * "Sent" means the email carrying the document went out (the same rule as
 * the Admin dashboard). Old CSPs (in CSPDATA before the import) are never
 * mailed documents, so they are not listed; their number is shown.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import type { ApiError, DocumentsLeft, DocumentsLeftParams, DocumentsLeftRow } from "../lib/api";

type Filters = Required<Pick<DocumentsLeftParams, "rm" | "dc" | "state" | "district" | "contacted" | "hold" | "q" | "sort">>;

const EMPTY: Filters = { rm: "", dc: "", state: "", district: "", contacted: "", hold: "", q: "", sort: "contacts" };
const GROUPS = [
  ["rm", "RM"],
  ["dc", "DC"],
  ["state", "State"],
  ["district", "District"],
] as const;
const PAGE_SIZE = 25;
const STORE = "rm-dashboard-filters";

const card = "bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700";
const field =
  "w-full min-w-0 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-eko focus:border-eko outline-none";
const label = "block text-[11px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1";

function when(iso: string | null): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  const date = d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  if (days <= 0) return `Today · ${date}`;
  if (days === 1) return `Yesterday · ${date}`;
  return `${days} days ago · ${date}`;
}

function contactTone(n: number): string {
  if (n === 0) return "bg-red-50 text-red-700 border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800";
  if (n <= 2) return "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800";
  return "bg-green-50 text-green-800 border-green-200 dark:bg-green-900/20 dark:text-green-300 dark:border-green-800";
}

function loadFilters(): Filters {
  try {
    const raw = window.localStorage.getItem(STORE);
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

export default function RmDashboard({ onOpenCsp }: { onOpenCsp: (cspId: string) => void }) {
  // The last filters this person used come back (this browser only). The
  // RM page draws this only in the browser, after sign-in is known.
  const [filters, setFilters] = useState<Filters>(() => (typeof window === "undefined" ? EMPTY : loadFilters()));
  const [groupBy, setGroupBy] = useState<string>("rm");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<DocumentsLeft | null>(null);
  const [loadedKey, setLoadedKey] = useState("");
  const [error, setError] = useState("");
  const [search, setSearch] = useState(filters.q);
  const [sending, setSending] = useState<string>("");
  const [sendFor, setSendFor] = useState<string>("");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORE, JSON.stringify(filters));
    } catch {
      /* private window: filters are simply not remembered */
    }
  }, [filters]);

  // Typing in the search waits for a pause.
  useEffect(() => {
    const t = setTimeout(() => {
      setFilters((f) => (f.q === search.trim() ? f : { ...f, q: search.trim() }));
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  // What is asked for now; "loading" until the answer for it arrives.
  const requestKey = JSON.stringify({ filters, groupBy, page, reload });
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let current = true;
    api
      .documentsLeft({ ...filters, group_by: groupBy, page, page_size: PAGE_SIZE })
      .then((d) => {
        if (!current) return;
        setData(d);
        setError("");
      })
      .catch((e) => current && setError((e as ApiError).detail || "The dashboard could not be loaded."))
      .finally(() => current && setLoadedKey(requestKey));
    return () => {
      current = false;
    };
    // requestKey is made of exactly these.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, groupBy, page, reload]);

  const set = useCallback((key: keyof Filters, value: string) => {
    setFilters((f) => {
      const next = { ...f, [key]: value };
      // A new state: its districts only.
      if (key === "state") next.district = "";
      return next;
    });
    setPage(1);
  }, []);

  const active = useMemo(
    () => (["rm", "dc", "state", "district", "contacted", "hold", "q"] as const).filter((k) => filters[k]).length,
    [filters]
  );

  const clear = () => {
    setFilters({ ...EMPTY, sort: filters.sort });
    setSearch("");
    setPage(1);
  };

  async function sendLink(row: DocumentsLeftRow, channel: string) {
    setSending(row.csp_id);
    setNotice(null);
    try {
      const r = await api.messageCsp(row.csp_id, { kind: "details_form", channel });
      setNotice({
        ok: r.sent,
        text: r.sent
          ? `Link sent to ${row.name} by ${channel === "email" ? "email" : "WhatsApp"}.`
          : `Not sent to ${row.name}: ${r.reason}`,
      });
      if (r.sent) setReload((n) => n + 1);
    } catch (e) {
      setNotice({ ok: false, text: `Not sent to ${row.name}: ${(e as ApiError).detail || "the server refused."}` });
    } finally {
      setSending("");
      setSendFor("");
    }
  }

  async function download() {
    setDownloading(true);
    try {
      const blob = await api.documentsLeftCsv(filters);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "csps-documents-left.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setNotice({ ok: false, text: (e as ApiError).detail || "The list could not be downloaded." });
    } finally {
      setDownloading(false);
    }
  }

  const s = data?.summary;
  const tiles = [
    { key: "", label: "Left to send", value: s?.left, icon: "fa-file-circle-exclamation", tone: "text-eko", hint: "CSPs still owed a document" },
    { key: "never", label: "Never contacted", value: s?.never, icon: "fa-phone-slash", tone: "text-red-600 dark:text-red-400", hint: "No WhatsApp or email yet" },
    { key: "1-2", label: "Contacted 1–2 times", value: s?.once_or_twice, icon: "fa-comment", tone: "text-amber-600 dark:text-amber-400", hint: "Follow up" },
    { key: "3+", label: "Contacted 3+ times", value: s?.three_plus, icon: "fa-comments", tone: "text-green-600 dark:text-green-400", hint: "Try a call or the DC" },
  ];
  const options = data?.options ?? { rm: [], dc: [], state: [], district: [] };
  const groupName = GROUPS.find(([k]) => k === groupBy)?.[1] ?? "RM";

  return (
    <div className="space-y-5">
      {/* Title */}
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl sm:text-2xl font-bold text-gray-900 dark:text-white">Documents left to send</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Every CSP still waiting for documents — whoever its RM is — and how often each has been contacted.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            onClick={() => setReload((n) => n + 1)}
            disabled={loading}
            className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
            title="Refresh"
          >
            <i className={`fas fa-rotate-right ${loading ? "fa-spin" : ""}`}></i>
            <span className="ml-1.5 hidden sm:inline">Refresh</span>
          </button>
          <button
            onClick={download}
            disabled={downloading || !data?.total}
            className="px-3 py-2 rounded-lg bg-navy-800 hover:bg-navy-900 dark:bg-eko dark:hover:bg-eko-dark text-white text-sm font-medium disabled:opacity-50"
          >
            <i className="fas fa-download"></i>
            <span className="ml-1.5">{downloading ? "Preparing…" : "Download CSV"}</span>
          </button>
        </div>
      </div>

      {/* Tiles — a contact tile filters the list */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {tiles.map((t) => {
          const on = filters.contacted === t.key && (t.key !== "" || !filters.contacted);
          return (
            <button
              key={t.label}
              onClick={() => set("contacted", t.key === "" || filters.contacted === t.key ? "" : t.key)}
              className={`${card} text-left p-4 transition-all hover:shadow-md ${
                on && t.key ? "ring-2 ring-eko" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] sm:text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider leading-tight">
                  {t.label}
                </span>
                <i className={`fas ${t.icon} ${t.tone} text-sm`}></i>
              </div>
              <div className={`mt-2 text-2xl sm:text-3xl font-bold ${t.tone}`}>
                {t.value === undefined ? "—" : t.value.toLocaleString("en-IN")}
              </div>
              <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 truncate">{t.hint}</div>
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <div className={`${card} p-4`}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {(
            [
              ["rm", "RM", options.rm],
              ["dc", "DC", options.dc],
              ["state", "State", options.state],
              ["district", "District", options.district],
            ] as const
          ).map(([key, name, values]) => (
            <div key={key} className="min-w-0">
              <label className={label} htmlFor={`f-${key}`}>{name}</label>
              <select id={`f-${key}`} value={filters[key]} onChange={(e) => set(key, e.target.value)} className={field}>
                <option value="">All {name === "RM" || name === "DC" ? `${name}s` : name === "State" ? "states" : "districts"}</option>
                {/* A chosen value stays in the list even when nothing matches now. */}
                {filters[key] && !values.some((v) => v.toLowerCase() === filters[key].toLowerCase()) && (
                  <option value={filters[key]}>{filters[key]}</option>
                )}
                {values.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
          <div className="col-span-2 min-w-0">
            <label className={label} htmlFor="f-q">Search</label>
            <div className="relative">
              <i className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-xs"></i>
              <input
                id="f-q"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="CSP code, name or mobile"
                className={`${field} pl-8`}
              />
            </div>
          </div>
          <div className="min-w-0">
            <label className={label} htmlFor="f-contacted">Contacted</label>
            <select id="f-contacted" value={filters.contacted} onChange={(e) => set("contacted", e.target.value)} className={field}>
              <option value="">Any number of times</option>
              <option value="never">Never</option>
              <option value="1-2">1–2 times</option>
              <option value="3+">3 or more times</option>
            </select>
          </div>
          <div className="min-w-0">
            <label className={label} htmlFor="f-hold">On hold</label>
            <select id="f-hold" value={filters.hold} onChange={(e) => set("hold", e.target.value)} className={field}>
              <option value="">Show all</option>
              <option value="hide">Hide CSPs on hold</option>
              <option value="only">Only CSPs on hold</option>
            </select>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-xs text-gray-500 dark:text-gray-400">
          <span>
            {data ? (
              <>
                Showing <b className="text-gray-800 dark:text-gray-200">{data.total.toLocaleString("en-IN")}</b> of{" "}
                {data.all_left.toLocaleString("en-IN")} CSPs left
                {s && s.on_hold > 0 && <> · {s.on_hold} on hold (nothing can be sent until they are live)</>}
              </>
            ) : (
              "Loading…"
            )}
          </span>
          {active > 0 && (
            <button onClick={clear} className="font-semibold text-eko hover:underline">
              <i className="fas fa-xmark mr-1"></i>Clear {active} filter{active > 1 ? "s" : ""}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 dark:bg-red-900/20 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          <i className="fas fa-triangle-exclamation mr-2"></i>
          {error}
        </div>
      )}
      {notice && (
        <div
          className={`rounded-lg border px-4 py-3 text-sm flex justify-between gap-3 ${
            notice.ok
              ? "border-green-200 bg-green-50 text-green-800 dark:bg-green-900/20 dark:border-green-800 dark:text-green-300"
              : "border-red-200 bg-red-50 text-red-700 dark:bg-red-900/20 dark:border-red-800 dark:text-red-300"
          }`}
        >
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} aria-label="Close" className="shrink-0 opacity-70 hover:opacity-100">
            <i className="fas fa-xmark"></i>
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* Breakdown by RM / DC / state / district */}
        <div className={`${card} xl:col-span-1 overflow-hidden self-start`}>
          <div className="px-4 pt-4 pb-3 border-b border-gray-100 dark:border-gray-700">
            <h2 className="text-sm font-semibold text-gray-800 dark:text-white">Left, by {groupName}</h2>
            <div className="mt-2 inline-flex rounded-lg bg-gray-100 dark:bg-gray-900 p-0.5">
              {GROUPS.map(([k, name]) => (
                <button
                  key={k}
                  onClick={() => setGroupBy(k)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium ${
                    groupBy === k ? "bg-white dark:bg-gray-700 text-eko shadow-sm" : "text-gray-600 dark:text-gray-300"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-50 dark:bg-gray-900/80 text-[11px] uppercase tracking-wider text-gray-500 dark:text-gray-400">
                <tr>
                  <th className="text-left font-semibold px-4 py-2">{groupName}</th>
                  <th className="text-right font-semibold px-2 py-2">Left</th>
                  <th className="text-right font-semibold px-2 py-2" title="Never contacted">Never</th>
                  <th className="text-right font-semibold px-4 py-2" title="Average times contacted">Avg</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {(data?.groups ?? []).map((g) => (
                  <tr
                    key={g.name}
                    onClick={() => g.name !== "(not set)" && set(groupBy as keyof Filters, g.name)}
                    className={`hover:bg-gray-50 dark:hover:bg-gray-700/40 ${g.name !== "(not set)" ? "cursor-pointer" : ""}`}
                    title={g.name !== "(not set)" ? `Show only ${g.name}` : ""}
                  >
                    <td className="px-4 py-2 text-gray-800 dark:text-gray-100 truncate max-w-[180px]">{g.name}</td>
                    <td className="px-2 py-2 text-right font-semibold text-gray-900 dark:text-white">{g.left}</td>
                    <td className={`px-2 py-2 text-right ${g.never ? "text-red-600 dark:text-red-400 font-medium" : "text-gray-400"}`}>{g.never}</td>
                    <td className="px-4 py-2 text-right text-gray-600 dark:text-gray-300">{g.average}</td>
                  </tr>
                ))}
                {data && data.groups.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-gray-500">Nothing left here.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* The CSPs */}
        <div className={`${card} xl:col-span-2`}>
          <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-800 dark:text-white">CSPs left to send</h2>
            <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              Sort
              <select value={filters.sort} onChange={(e) => set("sort", e.target.value)} className={`${field} !w-auto !py-1`}>
                <option value="contacts">Least contacted first</option>
                <option value="-contacts">Most contacted first</option>
                <option value="last_contacted">Longest since contact</option>
                <option value="name">Name A–Z</option>
              </select>
            </label>
          </div>

          {data && data.csps.length === 0 && !loading && (
            <div className="px-4 py-12 text-center">
              <i className="fas fa-circle-check text-3xl text-green-500"></i>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
                {active ? "No CSP left for these filters." : "Every CSP has been sent its documents."}
              </p>
            </div>
          )}

          <ul className={`divide-y divide-gray-100 dark:divide-gray-700 ${loading ? "opacity-60" : ""}`}>
            {(data?.csps ?? []).map((row) => (
              <li key={row.csp_id} className="px-4 py-3 hover:bg-gray-50/60 dark:hover:bg-gray-700/20">
                <div className="flex flex-col md:flex-row md:items-center gap-3">
                  {/* Who */}
                  <div className="min-w-0 md:flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      <button
                        onClick={() => onOpenCsp(row.csp_id)}
                        className="font-semibold text-gray-900 dark:text-white hover:text-eko truncate text-left"
                        title="Open this CSP"
                      >
                        {row.name}
                      </button>
                      <span className="text-[11px] font-mono text-gray-500 bg-gray-100 dark:bg-gray-900 px-1.5 py-0.5 rounded shrink-0">
                        {row.csp_id}
                      </span>
                      {row.on_hold && (
                        <span
                          className="text-[11px] font-medium px-1.5 py-0.5 rounded bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300 shrink-0"
                          title={row.on_hold}
                        >
                          On hold
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">
                      {[row.district, row.state].filter(Boolean).join(", ") || "No district"}
                      {" · RM "}
                      {row.rm || "—"}
                      {" · DC "}
                      {row.dc || "—"}
                      {row.mobile ? ` · ${row.mobile}` : ""}
                    </div>
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {row.documents_left.map((d) => (
                        <span
                          key={d}
                          className="text-[11px] px-1.5 py-0.5 rounded border border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-800 dark:bg-orange-900/20 dark:text-orange-300"
                        >
                          {d}
                        </span>
                      ))}
                      {row.documents_sent > 0 && (
                        <span className="text-[11px] px-1.5 py-0.5 text-gray-500">
                          {row.documents_sent} of {row.documents_due} sent
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Contacted */}
                  <div className="flex items-center gap-3 md:w-48 shrink-0">
                    <div
                      className={`w-12 h-12 rounded-lg border flex flex-col items-center justify-center shrink-0 ${contactTone(row.contacts)}`}
                      title={`${row.whatsapp} WhatsApp, ${row.email} email`}
                    >
                      <span className="text-lg font-bold leading-none">{row.contacts}</span>
                      <span className="text-[9px] uppercase tracking-wide mt-0.5">times</span>
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 min-w-0">
                      <div>
                        <i className="fab fa-whatsapp mr-1"></i>
                        {row.whatsapp} · <i className="far fa-envelope mx-1"></i>
                        {row.email}
                      </div>
                      <div className="truncate">{when(row.last_contacted)}</div>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex gap-2 md:w-auto shrink-0 relative">
                    <button
                      onClick={() => onOpenCsp(row.csp_id)}
                      className="flex-1 md:flex-none px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                      title="Open: edit details, photo, send documents"
                    >
                      <i className="fas fa-file-signature mr-1"></i>Open
                    </button>
                    <button
                      onClick={() => setSendFor(sendFor === row.csp_id ? "" : row.csp_id)}
                      disabled={!!row.on_hold || sending === row.csp_id}
                      className="flex-1 md:flex-none px-3 py-1.5 rounded-lg bg-eko hover:bg-eko-dark text-white text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                      title={row.on_hold ? `On hold — nothing is sent: ${row.on_hold}` : "Send the details form link"}
                    >
                      <i className="fas fa-paper-plane mr-1"></i>
                      {sending === row.csp_id ? "Sending…" : "Send link"}
                    </button>
                    {sendFor === row.csp_id && (
                      <div className="absolute right-0 top-full mt-1 z-20 w-48 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg py-1">
                        <div className="px-3 py-1.5 text-[11px] text-gray-500 uppercase tracking-wider">Send the link by</div>
                        <button
                          onClick={() => sendLink(row, "whatsapp")}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-800 dark:text-gray-100"
                        >
                          <i className="fab fa-whatsapp text-green-600 mr-2"></i>WhatsApp
                        </button>
                        <button
                          onClick={() => sendLink(row, "email")}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-800 dark:text-gray-100"
                        >
                          <i className="far fa-envelope text-eko mr-2"></i>Email
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>

          {data && data.pages > 1 && (
            <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-700 flex items-center justify-between text-sm">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || loading}
                className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 disabled:opacity-40"
              >
                <i className="fas fa-chevron-left mr-1 text-xs"></i>Previous
              </button>
              <span className="text-gray-500 dark:text-gray-400">
                Page {data.page} of {data.pages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
                disabled={page >= data.pages || loading}
                className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 disabled:opacity-40"
              >
                Next<i className="fas fa-chevron-right ml-1 text-xs"></i>
              </button>
            </div>
          )}
        </div>
      </div>

      {data && data.old_not_listed > 0 && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          <i className="fas fa-circle-info mr-1"></i>
          {data.old_not_listed.toLocaleString("en-IN")} older CSPs (in CSPDATA before the import) are not listed — they
          are never mailed documents. &quot;Contacted&quot; counts WhatsApps and emails that went out; &quot;sent&quot; means the
          document&apos;s email went out.
        </p>
      )}
    </div>
  );
}
