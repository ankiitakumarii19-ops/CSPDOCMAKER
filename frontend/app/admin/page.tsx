"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import BrandLogo from "../components/BrandLogo";
import DocumentTemplates from "./DocumentTemplates";
import AccessControl from "./AccessControl";
import Sheets from "./Sheets";
import Database from "./Database";
import CspSearch from "./CspSearch";
import Agents from "./Agents";
import Messaging from "./Messaging";
import DashboardView from "./DashboardView";
import DashboardBuilder from "./DashboardBuilder";
import { api } from "../lib/api";
import type { ApiError, DashboardSummary } from "../lib/api";
import { useSessionUser } from "../lib/useSessionUser";
import { useTheme } from "../lib/useTheme";

interface Metrics {
  totals: {
    csps: number;
    new: number;
    existing: number;
    awaiting_rm: number;
    details_fetched: number;
    details_missing: number;
  };
  documents: Array<{
    document_type: string;
    label: string;
    new: number;
    existing: number;
    generated: number;
    mailed: number;
    pending: number;
    failed: number;
  }>;
}

interface CSPRow {
  csp_id: string;
  name: string;
  origin: string | null;
  district: string | null;
  state: string | null;
  lho: string | null;
  rm_name: string | null;
  circle_head: string | null;
}

const FILTERS = [
  ["rm", "RM"],
  ["dc", "DC"],
  ["ao", "AO"],
  ["asm", "ASM"],
  ["ch", "CH"],
  ["lho", "LHO"],
  ["district", "District"],
  ["state", "State"],
] as const;

// Who the admin screens are for. An Admin monitors; a Super Admin also
// configures. Both land here.
const ADMIN_ROLES = ["admin", "super_admin"];

export default function AdminDashboard() {
  const router = useRouter();
  const user = useSessionUser();

  const [adminRoute, setAdminRoute] = useState("overview");
  // What each role may do, deliberately separated. The server enforces the
  // same split; hiding a button here is for clarity, not security.
  //
  // canConfigure — shaping the work: dashboards, document templates and
  //                messaging. Both Admins and Workspace Owners do this
  //                (confirmed 12 Oct 2026, No. 88). Acting on agents is the
  //                Owner's alone (Agents canAct).
  // isOwner      — controlling who may sign in. The Owner alone, because
  //                an Admin who could grant access could grant themselves
  //                anything.
  const isOwner = user?.role === "super_admin";
  const canConfigure = isOwner || user?.role === "admin";

  // The dashboards are data now. The permanent one still renders the
  // existing screen below — it has filters, drill-down and CSV export, and
  // replacing it with generic cards would be a downgrade.
  const [dashboards, setDashboards] = useState<DashboardSummary[]>([]);

  const loadDashboards = useCallback(async () => {
    try {
      const data = await api.listDashboards();
      setDashboards(data.dashboards);
    } catch {
      // A failure here must not cost the user their dashboard; the
      // permanent one is rendered from the sidebar regardless.
    }
  }, []);

  useEffect(() => {
    loadDashboards();
  }, [loadDashboards]);
  const [theme, toggleTheme] = useTheme();
  const [logoutMenu, setLogoutMenu] = useState(false);

  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [options, setOptions] = useState<Record<string, string[]>>({});
  const [filters, setFilters] = useState<Record<string, string>>({});
  // One day, not a range: the dashboard is read day-wise. It is sent as
  // date_from and date_to together, which the API treats as inclusive.
  const [day, setDay] = useState("");
  const [error, setError] = useState("");

  const [drill, setDrill] = useState<{ title: string; rows: CSPRow[] } | null>(null);
  // The drill-down sits below a tall table, so opening it off-screen looks
  // like the click did nothing. Bring it into view instead.
  const drillRef = useRef<HTMLDivElement | null>(null);
  const [drilling, setDrilling] = useState(false);

  useEffect(() => {
    if (user === undefined) return;
    if (user === null) router.replace("/auth/login");
    // A Super Admin belongs here too. Before this, "super_admin" failed
    // the test and was sent to /rm, which sent them straight back —
    // an endless bounce between the two screens and a white page.
    else if (!ADMIN_ROLES.includes(user.role)) router.replace("/rm");
  }, [user, router]);

  const dayParams: Record<string, string> = day
    ? { date_from: day, date_to: day }
    : {};
  const query = { ...filters, ...dayParams };
  const queryKey = JSON.stringify(query);

  useEffect(() => {
    let cancelled = false;
    api
      .cspMetrics(JSON.parse(queryKey))
      .then((res) => {
        if (cancelled) return;
        setMetrics(res);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError((err as ApiError).detail || "Could not load.");
      });
    return () => {
      cancelled = true;
    };
  }, [queryKey]);

  useEffect(() => {
    api
      .cspFilters()
      .then((res) => setOptions(res.filters))
      .catch(() => setOptions({}));
  }, []);

  useEffect(() => {
    if (drill) {
      drillRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [drill]);

  const openDrill = async (title: string, params: Record<string, string>) => {
    setDrilling(true);
    setDrill({ title, rows: [] });
    try {
      const res = await api.cspList({ ...query, ...params });
      setDrill({ title, rows: res.csps });
    } catch (err) {
      setError((err as ApiError).detail || "Could not load the list.");
      setDrill(null);
    } finally {
      setDrilling(false);
    }
  };

  const logout = async () => {
    await api.logout();
    router.replace("/");
  };

  if (!user || !ADMIN_ROLES.includes(user.role)) return null;

  const activeFilters = Object.entries(filters).filter(([, v]) => v);
  const anythingApplied = activeFilters.length > 0 || day !== "";

  const clearAll = () => {
    setFilters({});
    setDay("");
    setDrill(null);
  };

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-navy-900 w-full overflow-hidden">
      {/* Admin Sidebar */}
      <aside className="w-64 bg-navy-900 text-gray-300 hidden md:flex flex-col shrink-0">
        {/* The name was being clipped by the sidebar's edge: the logo at
            36px plus the title at text-lg needed more room than w-56 left
            after its padding. */}
        <div className="h-16 flex items-center gap-2 px-4 bg-navy-800 border-b border-gray-700 overflow-hidden">
          <BrandLogo height={30} className="shrink-0" />
          <span className="font-bold text-base text-white whitespace-nowrap">
            CSPdocMaker
          </span>
        </div>
        <nav className="flex-grow py-6 px-3 space-y-1 overflow-y-auto">
          <div className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2 px-3">
            Monitoring
          </div>
          {dashboards.map((d) => (
            <button
              key={d.slug}
              onClick={() =>
                setAdminRoute(d.is_system ? "overview" : `dash:${d.slug}`)
              }
              className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                (d.is_system && adminRoute === "overview") ||
                adminRoute === `dash:${d.slug}`
                  ? "bg-navy-800 text-white border-l-4 border-eko"
                  : "hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
              }`}
            >
              <i className={`fas ${d.icon} w-5 text-center`}></i> {d.name}
            </button>
          ))}
          {dashboards.length === 0 && (
            <button
              onClick={() => setAdminRoute("overview")}
              className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                adminRoute === "overview"
                  ? "bg-navy-800 text-white border-l-4 border-eko"
                  : "hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
              }`}
            >
              <i className="fas fa-chart-line w-5 text-center"></i> Dashboard Overview
            </button>
          )}
          {canConfigure && (
            <button
              onClick={() => setAdminRoute("build")}
              className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                adminRoute === "build"
                  ? "bg-navy-800 text-white border-l-4 border-eko"
                  : "text-gray-400 hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
              }`}
            >
              <i className="fas fa-plus w-5 text-center"></i> Build a dashboard
            </button>
          )}

          {canConfigure && (
            <>
              <div className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2 mt-6 px-3">
                Setup
              </div>
              {/* The agents are the Super Admin's alone (No. 104). */}
              {isOwner && (
              <button
                onClick={() => setAdminRoute("agents")}
                className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                  adminRoute === "agents"
                    ? "bg-navy-800 text-white border-l-4 border-eko"
                    : "hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
                }`}
              >
                <i className="fas fa-robot w-5 text-center"></i> Agents
              </button>
              )}
              <button
                onClick={() => setAdminRoute("messaging")}
                className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                  adminRoute === "messaging"
                    ? "bg-navy-800 text-white border-l-4 border-eko"
                    : "hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
                }`}
              >
                <i className="fas fa-comment-dots w-5 text-center"></i> Messaging
              </button>
              <button
                onClick={() => setAdminRoute("templates")}
                className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                  adminRoute === "templates"
                    ? "bg-navy-800 text-white border-l-4 border-eko"
                    : "hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
                }`}
              >
                <i className="fas fa-file-lines w-5 text-center"></i> Document Templates
              </button>
              {/* Access is the Workspace Owner's alone. An Admin who
                  could grant access could grant themselves anything. */}
              {isOwner && (
                <button
                  onClick={() => setAdminRoute("access")}
                  className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                    adminRoute === "access"
                      ? "bg-navy-800 text-white border-l-4 border-eko"
                      : "hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
                  }`}
                >
                  <i className="fas fa-users-gear w-5 text-center"></i> Access
                </button>
              )}
              {/* The sheets every other screen is derived from. Admins
                  edit the CSP tabs only; the access sheet and which sheets
                  are read stay the Owner's (No. 104, enforced server-side). */}
              {canConfigure && (
                <button
                  onClick={() => setAdminRoute("sheets")}
                  className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                    adminRoute === "sheets"
                      ? "bg-navy-800 text-white border-l-4 border-eko"
                      : "hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
                  }`}
                >
                  <i className="fas fa-table w-5 text-center"></i> Sheets
                </button>
              )}
              {/* Every CSP's complete record (No. 89), read-only. Admins
                  and RMs too since No. 104. */}
              {canConfigure && (
                <button
                  onClick={() => setAdminRoute("database")}
                  className={`w-full text-left px-3 py-2.5 rounded text-sm font-medium transition-all flex items-center gap-3 ${
                    adminRoute === "database"
                      ? "bg-navy-800 text-white border-l-4 border-eko"
                      : "hover:bg-navy-800 hover:text-white border-l-4 border-transparent"
                  }`}
                >
                  <i className="fas fa-database w-5 text-center"></i> Database
                </button>
              )}
            </>
          )}
        </nav>
        <div className="px-6 py-4 text-[11px] text-gray-500 border-t border-gray-800">
          {isOwner
            ? "Workspace Owner — you also control who may sign in."
            : "Admin — dashboards, templates and messaging. Access, sheets, the database and agent actions are the Owner's."}
        </div>
      </aside>

      {/* Admin Main Content */}
      <main className="flex-grow flex flex-col h-full overflow-hidden relative">
        {/* Admin Top Nav */}
        <header className="h-16 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-4 w-1/3">
            <CspSearch />
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={toggleTheme}
              className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            >
              <i className={`fas ${theme === "dark" ? "fa-sun" : "fa-moon"}`}></i>
            </button>
            <div className="h-6 w-px bg-gray-200 dark:bg-gray-700"></div>
            <div
              className="flex items-center gap-2 cursor-pointer relative"
              onClick={() => setLogoutMenu(!logoutMenu)}
            >
              <div className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold text-sm">
                {user.name.slice(0, 2).toUpperCase()}
              </div>
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-200 hidden sm:block">
                {user.name}
              </span>

              {logoutMenu && (
                <div className="absolute top-12 right-0 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-50">
                  <button
                    onClick={logout}
                    className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                  >
                    <i className="fas fa-sign-out-alt mr-2"></i> Sign Out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Scrollable Area */}
        <div className="flex-grow overflow-y-auto p-4 md:p-8">
          <div className="max-w-screen-2xl mx-auto space-y-8">
            {adminRoute.startsWith("dash:") && (
              <DashboardView
                slug={adminRoute.slice(5)}
                canManage={canConfigure}
                onRetired={() => {
                  setAdminRoute("overview");
                  loadDashboards();
                }}
              />
            )}

            {canConfigure && adminRoute === "build" && (
              <DashboardBuilder
                onBuilt={(slug) => {
                  loadDashboards();
                  setAdminRoute(`dash:${slug}`);
                }}
                onCancel={() => setAdminRoute("overview")}
              />
            )}

            {isOwner && adminRoute === "agents" && (
              <Agents canSeeHistory={isOwner} canAct={isOwner} />
            )}
            {canConfigure && adminRoute === "messaging" && <Messaging />}
            {canConfigure && adminRoute === "templates" && <DocumentTemplates />}
            {isOwner && adminRoute === "access" && <AccessControl />}
            {canConfigure && adminRoute === "sheets" && <Sheets canManage={isOwner} />}
            {canConfigure && adminRoute === "database" && <Database />}

            {adminRoute === "overview" && (
            <>
            {error && (
              <div className="p-3 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg text-sm">
                {error}
              </div>
            )}

            {/* Filters */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                  <i className="fas fa-filter mr-1.5"></i> Filter
                </h2>
                <button
                  onClick={clearAll}
                  disabled={!anythingApplied}
                  className="text-xs font-medium text-eko hover:underline disabled:text-gray-400 disabled:no-underline disabled:cursor-not-allowed"
                >
                  <i className="fas fa-xmark mr-1"></i> Clear filters
                </button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-9 gap-3">
                <div>
                  <label className="block text-[11px] font-medium text-gray-500 mb-1">
                    Date
                  </label>
                  <input
                    type="date"
                    value={day}
                    onChange={(e) => setDay(e.target.value)}
                    className="w-full px-2 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white focus:ring-2 focus:ring-eko outline-none cursor-pointer"
                  />
                </div>
                {FILTERS.map(([key, label]) => (
                  <div key={key}>
                    <label className="block text-[11px] font-medium text-gray-500 mb-1">
                      {label}
                    </label>
                    <select
                      value={filters[key] ?? ""}
                      onChange={(e) =>
                        setFilters({ ...filters, [key]: e.target.value })
                      }
                      className="w-full px-2 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white focus:ring-2 focus:ring-eko outline-none cursor-pointer"
                    >
                      <option value="">All</option>
                      {(options[key] ?? []).map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
              {anythingApplied && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {day && (
                    <span className="text-[11px] px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                      Date: {day}
                    </span>
                  )}
                  {activeFilters.map(([key, value]) => (
                    <span
                      key={key}
                      className="text-[11px] px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
                    >
                      {key.toUpperCase()}: {value}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Stat cards — each one opens the CSPs behind it */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {(
                [
                  ["Total CSPs", metrics?.totals.csps, "fa-store", "text-blue-500", ""],
                  ["New CSPs", metrics?.totals.new, "fa-plus-circle", "text-eko", "new"],
                  [
                    "Existing CSPs",
                    metrics?.totals.existing,
                    "fa-clock-rotate-left",
                    "text-gray-500",
                    "existing",
                  ],
                  [
                    "Data Missing Alert",
                    metrics?.totals.awaiting_rm,
                    "fa-exclamation-triangle",
                    "text-orange-500",
                    "awaiting_rm",
                  ],
                ] as Array<[string, number | undefined, string, string, string]>
              ).map(([label, value, icon, colour, view]) => (
                <button
                  key={label}
                  onClick={() =>
                    openDrill(label, view ? { view } : {})
                  }
                  disabled={metrics === null}
                  title={`Show the CSPs behind “${label}”`}
                  className="group cursor-pointer text-left bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-5 hover:border-eko hover:shadow-md hover:-translate-y-0.5 transition-all disabled:cursor-not-allowed disabled:hover:translate-y-0"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-xs font-medium uppercase tracking-wider text-gray-500">
                      {label}
                    </div>
                    <i className={`fas ${icon} ${colour}`}></i>
                  </div>
                  <div className="flex items-end justify-between">
                    <div className="text-3xl font-bold text-gray-900 dark:text-white tabular-nums">
                      {metrics === null ? "—" : value ?? 0}
                    </div>
                    <span className="text-[11px] text-gray-400 group-hover:text-eko transition-colors">
                      View <i className="fas fa-arrow-right"></i>
                    </span>
                  </div>
                </button>
              ))}
            </div>

            {/* Documents table */}
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700">
                <h2 className="font-bold text-gray-900 dark:text-white">
                  Documents Issued
                </h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Generated counts stored PDFs. Mailed, Pending and Failed
                  count delivery of that document and always add up to the
                  CSPs in scope. Every document name and every number here
                  is clickable — a zero opens an empty list.
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 text-xs uppercase tracking-wider">
                      <th className="px-6 py-3 font-semibold w-1/3">Document</th>
                      <th className="px-6 py-3 font-semibold text-right">New</th>
                      <th className="px-6 py-3 font-semibold text-right">Existing</th>
                      <th className="px-6 py-3 font-semibold text-right">Generated</th>
                      <th className="px-6 py-3 font-semibold text-right">Mailed</th>
                      <th className="px-6 py-3 font-semibold text-right">Pending</th>
                      <th className="px-6 py-3 font-semibold text-right">Failed</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {(metrics?.documents ?? []).map((doc) => {
                      /* Every number opens the CSPs behind it, including a
                         zero — an empty list is a real answer, and a dead
                         number just looks broken. */
                      const cell = (
                        value: number,
                        title: string,
                        params: Record<string, string>,
                        tone: string
                      ) => (
                        <td className="px-6 py-3 text-right">
                          <button
                            onClick={() =>
                              openDrill(`${doc.label} — ${title}`, {
                                document_type: doc.document_type,
                                ...params,
                              })
                            }
                            title={`Show the ${doc.label} CSPs that are ${title}`}
                            className={`text-sm font-bold tabular-nums cursor-pointer hover:underline ${
                              value === 0 ? "text-gray-400" : tone
                            }`}
                          >
                            {value}
                          </button>
                        </td>
                      );
                      return (
                        <tr
                          key={doc.document_type}
                          className="hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors"
                        >
                          <td className="px-6 py-3">
                            <button
                              onClick={() =>
                                openDrill(
                                  `${doc.label} — all CSPs in scope`,
                                  {}
                                )
                              }
                              title={`Show every CSP in scope for the ${doc.label}`}
                              className="text-sm font-medium text-gray-900 dark:text-white cursor-pointer hover:text-eko hover:underline text-left"
                            >
                              <i className="fas fa-file-pdf text-red-500 mr-2"></i>
                              {doc.label}
                            </button>
                          </td>
                          {cell(doc.new, "new", { view: "new" }, "text-gray-700 dark:text-gray-200")}
                          {cell(doc.existing, "existing", { view: "existing" }, "text-gray-700 dark:text-gray-200")}
                          {cell(doc.generated, "generated", {}, "text-gray-700 dark:text-gray-200")}
                          {cell(doc.mailed, "mailed", { delivery: "mailed" }, "text-eko")}
                          {cell(doc.pending, "pending", { delivery: "pending" }, "text-orange-600 dark:text-orange-400")}
                          {cell(doc.failed, "failed", { delivery: "failed" }, "text-red-600 dark:text-red-400")}
                        </tr>
                      );
                    })}
                    {metrics !== null && metrics.documents.length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-6 py-8 text-center text-gray-500">
                          Nothing matches these filters.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Drill-down */}
            {drill && (
              <div
                ref={drillRef}
                className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border-2 border-eko rounded-xl shadow-md overflow-hidden scroll-mt-4"
              >
                <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                  <h2 className="font-bold text-gray-900 dark:text-white">
                    {drill.title}
                    <span className="ml-2 text-sm font-normal text-gray-500">
                      {drilling ? "loading…" : drill.rows.length}
                    </span>
                  </h2>
                  <button
                    onClick={() => setDrill(null)}
                    className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                  >
                    <i className="fas fa-xmark"></i> Close
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="bg-gray-50 dark:bg-gray-900/50 text-gray-500 text-xs uppercase tracking-wider">
                        <th className="px-5 py-3 font-semibold">CSP</th>
                        <th className="px-5 py-3 font-semibold">Location</th>
                        <th className="px-5 py-3 font-semibold">RM</th>
                        <th className="px-5 py-3 font-semibold">CH</th>
                        <th className="px-5 py-3 font-semibold">Type</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                      {drill.rows.map((row) => (
                        <tr key={row.csp_id}>
                          <td className="px-5 py-3">
                            <div className="text-sm font-medium text-gray-900 dark:text-white">
                              {row.name}
                            </div>
                            <div className="text-xs text-gray-500">{row.csp_id}</div>
                          </td>
                          <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">
                            {[row.district, row.state, row.lho]
                              .filter(Boolean)
                              .join(" · ") || "—"}
                          </td>
                          <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">
                            {row.rm_name || (
                              <span className="text-orange-600 dark:text-orange-400">
                                unassigned
                              </span>
                            )}
                          </td>
                          <td className="px-5 py-3 text-sm text-gray-600 dark:text-gray-300">
                            {row.circle_head || "—"}
                          </td>
                          <td className="px-5 py-3">
                            <span className="px-2 py-0.5 text-[10px] uppercase tracking-wider rounded font-bold bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                              {row.origin === "new" ? "New" : "Existing"}
                            </span>
                          </td>
                        </tr>
                      ))}
                      {!drilling && drill.rows.length === 0 && (
                        <tr>
                          <td colSpan={5} className="px-5 py-8 text-center text-gray-500">
                            No CSPs here.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            </>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
