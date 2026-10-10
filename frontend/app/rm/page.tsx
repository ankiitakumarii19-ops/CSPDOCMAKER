"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import BrandLogo from "../components/BrandLogo";
import { api, DOCUMENT_TYPES } from "../lib/api";
import type { ApiError, CSPDetail, DocumentTypeKey } from "../lib/api";
import { useSessionUser } from "../lib/useSessionUser";
import { useTheme } from "../lib/useTheme";

interface MissingField {
  field_name: string;
  field_label: string;
  field_type: string;
}

interface MissingData {
  csp_id: string;
  csp_name: string;
  total_missing_fields: number;
  documents: Array<{
    document_type: DocumentTypeKey;
    document_label: string;
    missing_fields: MissingField[];
  }>;
}

interface AlertItem {
  id: string;
  csp_id: string;
  message: string;
  unassigned: boolean;
  details?: { csp_id: string; csp_name: string; fields: MissingField[] };
}

type Step =
  | "dashboard"
  | "search_result"
  | "generating"
  | "missing_data"
  | "validating"
  | "confirm_email"
  | "success";

function uniqueFields(data: MissingData): MissingField[] {
  const seen = new Map<string, MissingField>();
  for (const doc of data.documents) {
    for (const field of doc.missing_fields) {
      if (!seen.has(field.field_name)) seen.set(field.field_name, field);
    }
  }
  return [...seen.values()];
}

function blockedBy(data: MissingData, fieldName: string): string[] {
  return data.documents
    .filter((d) => d.missing_fields.some((f) => f.field_name === fieldName))
    .map((d) => d.document_label);
}

export default function RMDashboard() {
  const router = useRouter();
  const user = useSessionUser();

  const [rmStep, setRmStep] = useState<Step>("dashboard");
  const [theme, toggleTheme] = useTheme();
  const [alertsMenu, setAlertsMenu] = useState(false);
  const [logoutMenu, setLogoutMenu] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [results, setResults] = useState<CSPDetail[]>([]);
  const [csp, setCsp] = useState<CSPDetail | null>(null);
  const [searchError, setSearchError] = useState("");
  const [searching, setSearching] = useState(false);

  const [selectedDocs, setSelectedDocs] = useState<DocumentTypeKey[]>([]);
  const [jobId, setJobId] = useState("");
  const [recipient, setRecipient] = useState("");
  const [sentCount, setSentCount] = useState(0);
  const [processingError, setProcessingError] = useState("");
  const [busy, setBusy] = useState(false);

  const [missing, setMissing] = useState<MissingData | null>(null);

  const [rmAlerts, setRmAlerts] = useState<AlertItem[]>([]);

  // Handing a CSP to the automation instead of walking it through by hand.
  const [enrolling, setEnrolling] = useState(false);
  // Asked before, not after. Enrolling emails a real person and there is
  // no undo once the worker has run.
  const [confirmAuto, setConfirmAuto] = useState(false);
  const [enrolled, setEnrolled] = useState<{
    message: string;
    missing: string[];
  } | null>(null);

  useEffect(() => {
    if (user === undefined) return;
    if (user === null) router.replace("/auth/login");
    // Anyone who is not an RM belongs on the admin screens, which now
    // accept both admin and super_admin — so this no longer bounces.
    else if (user.role !== "rm") router.replace("/admin");
  }, [user, router]);

  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      api
        .alerts()
        .then((res) => {
          if (!cancelled) setRmAlerts(res.alerts as AlertItem[]);
        })
        .catch(() => {});
    };
    poll();
    const timer = setInterval(poll, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const resetRM = useCallback(() => {
    setRmStep("dashboard");
    setSearchQuery("");
    setResults([]);
    setCsp(null);
    setEnrolled(null);
    setConfirmAuto(false);
    setSelectedDocs([]);
    setJobId("");
    setProcessingError("");
    setMissing(null);
  }, []);

  const searchCSP = async (term?: string) => {
    const text = (term ?? searchQuery).trim();
    if (!text) return;
    setSearching(true);
    setSearchError("");
    try {
      const res = await api.searchCSP(text);
      setResults(res.results);
      if (res.results.length === 1) {
        setCsp(res.results[0]);
        setSelectedDocs(DOCUMENT_TYPES.map((d) => d.key));
        setRmStep("search_result");
      } else if (res.results.length === 0) {
        setSearchError(`No CSP found for "${text}".`);
      }
    } catch (err) {
      setSearchError((err as ApiError).detail || "Search failed.");
    } finally {
      setSearching(false);
    }
  };

  const pick = (record: CSPDetail) => {
    setCsp(record);
    setSelectedDocs(DOCUMENT_TYPES.map((d) => d.key));
    setRmStep("search_result");
  };

  const openAlert = async (alert: AlertItem) => {
    setAlertsMenu(false);
    try {
      pick(await api.getCSP(alert.csp_id));
    } catch {
      setSearchQuery(alert.csp_id);
      searchCSP(alert.csp_id);
    }
  };

  /** Let the automation finish this CSP rather than doing it step by step.
   *
   *  Existing CSPs are kept out of the automatic pipeline so a first sync
   *  cannot email a whole organisation. Choosing one deliberately is not
   *  that, so an RM can enrol the one in front of them.
   */
  const handToAutomation = async () => {
    if (!csp) return;
    setEnrolling(true);
    setProcessingError("");
    try {
      const result = await api.autoIssue(csp.csp_id);
      setEnrolled({ message: result.message, missing: result.missing_fields });
      setConfirmAuto(false);
    } catch (e) {
      setProcessingError(
        (e as ApiError).detail || "Could not hand this CSP to the automation."
      );
    } finally {
      setEnrolling(false);
    }
  };

  const startGeneration = async (record?: CSPDetail) => {
    const target = record ?? csp;
    if (!target || selectedDocs.length === 0) return;
    setBusy(true);
    setProcessingError("");
    setRmStep("generating");
    try {
      const res = await api.processWorkflow({
        csp_id: target.csp_id,
        document_types: selectedDocs,
      });
      setJobId(res.job_id);
      setRecipient(res.email_recipient ?? target.email ?? "");
      if (res.status === "pending_data" && res.missing_data) {
        // The RM fills nothing (tracker No. 53): the CSP is asked, and the
        // documents are made and sent automatically once the data is in.
        setMissing(res.missing_data as MissingData);
        setRmStep("missing_data");
        return;
      }
      if (res.ready_to_send) {
        setRmStep("validating");
      } else {
        setProcessingError(res.message || "Processing failed.");
        setRmStep("success");
      }
    } catch (err) {
      setProcessingError((err as ApiError).detail || "Processing failed.");
      setRmStep("success");
    } finally {
      setBusy(false);
    }
  };

  const sendEmail = async () => {
    if (!jobId) return;
    setBusy(true);
    try {
      const res = await api.confirmAndSend(jobId);
      setSentCount(res.documents_sent);
      setProcessingError("");
      setRmStep("success");
    } catch (err) {
      setProcessingError((err as ApiError).detail || "Send failed.");
      setRmStep("success");
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    await api.logout();
    router.replace("/");
  };

  if (!user || user.role !== "rm") return null;

  const unreadAlerts = rmAlerts.length;
  const initials = user.name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const docLabel = (key: DocumentTypeKey) =>
    DOCUMENT_TYPES.find((d) => d.key === key)?.label ?? key;

  return (
    <div className="flex flex-col h-screen bg-gray-50 dark:bg-navy-900 w-full overflow-hidden">
      {/* Global Top Nav */}
      <header className="h-16 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-6 shrink-0 z-20">
        <div className="flex items-center gap-3">
          <BrandLogo height={36} />
          <span className="font-bold text-lg hidden sm:block text-gray-900 dark:text-white">
            CSPdocMaker
            <span className="text-xs font-normal text-gray-500 bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded ml-2">
              RM Portal
            </span>
          </span>
        </div>
        <div className="flex items-center gap-4">
          {/* Notifications Dropdown */}
          <div className="relative">
            <button
              onClick={() => setAlertsMenu(!alertsMenu)}
              onBlur={() => setTimeout(() => setAlertsMenu(false), 200)}
              className="relative text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
            >
              <i className="far fa-bell text-xl"></i>
              {unreadAlerts > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white text-[10px] font-bold flex items-center justify-center rounded-full">
                  {unreadAlerts}
                </span>
              )}
            </button>

            {alertsMenu && (
              <div className="absolute top-10 right-0 w-80 bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-50">
                <div className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-700 flex justify-between items-center">
                  <span className="font-bold text-sm text-gray-800 dark:text-white">
                    Action Required
                  </span>
                  <span className="text-xs bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400 px-2 py-0.5 rounded-full font-bold">
                    {unreadAlerts} New
                  </span>
                </div>
                <div className="max-h-80 overflow-y-auto">
                  {rmAlerts.length === 0 && (
                    <div className="px-4 py-8 text-sm text-gray-500 text-center">
                      Nothing needs your attention.
                    </div>
                  )}
                  {rmAlerts.map((alert) => (
                    <div
                      key={alert.id}
                      onMouseDown={() => openAlert(alert)}
                      className="px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer border-b border-gray-100 dark:border-gray-700 last:border-0 transition-colors bg-orange-50/30 dark:bg-orange-900/10"
                    >
                      <div className="flex justify-between items-start mb-1">
                        <div className="font-bold text-sm text-gray-900 dark:text-white">
                          {alert.details?.csp_name ?? alert.csp_id}
                        </div>
                        <div className="text-xs font-semibold text-gray-500 bg-gray-100 dark:bg-gray-900 px-1.5 py-0.5 rounded">
                          {alert.csp_id}
                        </div>
                      </div>
                      <div className="text-xs text-orange-600 dark:text-orange-400 font-medium mt-1.5">
                        <i className="fas fa-exclamation-triangle mr-1"></i> Missing:{" "}
                        {alert.details?.fields.map((f) => f.field_label ?? f.field_name).join(", ")}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <button
            onClick={toggleTheme}
            className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
          >
            <i className={`fas ${theme === "dark" ? "fa-sun" : "fa-moon"}`}></i>
          </button>
          <div className="h-8 w-px bg-gray-200 dark:bg-gray-700 mx-2"></div>
          <div
            className="flex items-center gap-3 cursor-pointer group relative"
            onClick={() => setLogoutMenu(!logoutMenu)}
          >
            <div className="text-right hidden sm:block">
              <div className="text-sm font-semibold text-gray-900 dark:text-white">
                {user.name}
              </div>
              <div className="text-xs text-gray-500">{user.email}</div>
            </div>
            <div className="w-9 h-9 rounded-full bg-eko text-white flex items-center justify-center font-bold">
              {initials}
            </div>
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

      {/* RM Main Scrollable Area */}
      <main className="flex-grow overflow-y-auto p-4 sm:p-8">
        <div className="max-w-5xl mx-auto space-y-6">
          {/* State 1: Dashboard & Search */}
          {(rmStep === "dashboard" || rmStep === "search_result") && (
            <div>
              {/* Search Bar */}
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 mb-6">
                <label className="block text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2 uppercase tracking-wider">
                  Search CSP
                </label>
                <div className="flex gap-3">
                  <div className="relative flex-grow">
                    <i className="fas fa-search absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400"></i>
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyUp={(e) => e.key === "Enter" && searchCSP()}
                      className="w-full pl-11 pr-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-900 focus:ring-2 focus:ring-eko focus:border-eko dark:text-white outline-none transition-all text-lg"
                      placeholder="Enter CSP ID (e.g. 1A850466)"
                    />
                  </div>
                  <button
                    onClick={() => searchCSP()}
                    disabled={searching}
                    className="px-6 py-3 bg-navy-800 hover:bg-navy-900 dark:bg-eko dark:hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg shadow-sm transition-all whitespace-nowrap"
                  >
                    {searching ? "Searching..." : "Search"}
                  </button>
                </div>
                {searchError && (
                  <p className="mt-3 text-sm text-red-600 dark:text-red-400">
                    {searchError}
                  </p>
                )}
                {results.length > 1 && rmStep === "dashboard" && (
                  <div className="mt-4 divide-y divide-gray-100 dark:divide-gray-700 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                    {results.map((r) => (
                      <button
                        key={r.csp_id}
                        onClick={() => pick(r)}
                        className="w-full text-left px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 flex justify-between items-center"
                      >
                        <span className="font-medium text-gray-900 dark:text-white">
                          {r.name}
                        </span>
                        <span className="text-xs text-gray-500">{r.csp_id}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Search Result / Details */}
              {rmStep === "search_result" && csp && (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  {/* Left Column: CSP Details Card */}
                  <div className="lg:col-span-1 bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
                    <div className="bg-gray-50 dark:bg-gray-900/50 p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                      <h3 className="font-semibold text-gray-900 dark:text-white">
                        <i className="far fa-id-card text-eko mr-2"></i> CSP Details
                      </h3>
                      <span className="px-2 py-1 bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 text-xs rounded font-medium border border-green-200 dark:border-green-800">
                        {csp.origin === "new" ? "New" : "Existing"}
                      </span>
                    </div>
                    <div className="p-4 flex flex-col items-center border-b border-gray-200 dark:border-gray-700">
                      <div className="w-20 h-20 bg-gray-200 dark:bg-gray-700 rounded-full mb-3 flex items-center justify-center overflow-hidden">
                        <i className="fas fa-user text-3xl text-gray-400"></i>
                      </div>
                      <h4 className="font-bold text-lg text-gray-900 dark:text-white">
                        {csp.name}
                      </h4>
                      <p className="text-sm text-gray-500 font-medium">{csp.csp_id}</p>
                    </div>
                    <div className="p-4 space-y-3 text-sm">
                      {[
                        ["Branch", [csp.branch_name, csp.branch_code].filter(Boolean).join(", ")],
                        ["Location", [csp.district, csp.state].filter(Boolean).join(", ")],
                        ["LHO", csp.lho],
                        ["Mobile", csp.mobile],
                        ["Email", csp.email],
                        ["DC", csp.dc],
                        ["ASM", csp.asm_name],
                      ]
                        .filter(([, v]) => v)
                        .map(([label, value]) => (
                          <div className="flex justify-between gap-3" key={label as string}>
                            <span className="text-gray-500 shrink-0">{label}</span>
                            <span className="font-medium text-gray-900 dark:text-white text-right break-words min-w-0">
                              {value}
                            </span>
                          </div>
                        ))}
                      <div className="pt-2 mt-2 border-t border-gray-100 dark:border-gray-700 flex justify-between">
                        <span className="text-gray-500">Assigned RM</span>
                        <span className="font-medium text-gray-900 dark:text-white">
                          {csp.rm_name || "Unassigned"}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Right Column: Document Selection */}
                  <div className="lg:col-span-2 bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 flex flex-col">
                    <h3 className="font-semibold text-gray-900 dark:text-white mb-4 text-lg">
                      Select Documents to Generate
                    </h3>

                    {confirmAuto && !enrolled && (
                      <div className="mb-4 px-4 py-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 text-sm">
                        <p className="font-medium text-amber-900 dark:text-amber-200">
                          This will email {csp.name || csp.csp_id} directly.
                        </p>
                        <p className="text-amber-800 dark:text-amber-300 mt-1">
                          Documents are generated and sent to{" "}
                          <span className="font-mono">
                            {csp.email || "their address on file"}
                          </span>{" "}
                          within a few minutes. There is no undo once it has
                          gone.
                        </p>
                      </div>
                    )}

                    {enrolled && (
                      <div className="mb-4 px-4 py-3 rounded-lg bg-eko-light dark:bg-eko/10 border border-eko/30 text-sm">
                        <p className="text-eko-dark dark:text-eko font-medium">
                          <i className="fas fa-circle-check mr-2" />
                          {enrolled.message}
                        </p>
                        {enrolled.missing.length > 0 && (
                          <p className="text-gray-600 dark:text-gray-400 mt-1">
                            Still needed: {enrolled.missing.join(", ")}.
                          </p>
                        )}
                        <p className="text-xs text-gray-500 mt-2">
                          You can close this — nothing else is needed from you.
                        </p>
                      </div>
                    )}

                    <div className="space-y-3 flex-grow">
                      {DOCUMENT_TYPES.map((doc) => {
                        const on = selectedDocs.includes(doc.key);
                        return (
                          <label
                            key={doc.key}
                            className={`flex items-center p-4 border rounded-lg cursor-pointer transition-colors ${
                              on
                                ? "border-eko bg-eko-light/30 dark:border-eko dark:bg-eko/10"
                                : "border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50"
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={() =>
                                setSelectedDocs(
                                  on
                                    ? selectedDocs.filter((k) => k !== doc.key)
                                    : [...selectedDocs, doc.key]
                                )
                              }
                              className="w-5 h-5 accent-eko border-gray-300 rounded focus:ring-eko"
                            />
                            <span className="ml-3 font-medium text-gray-900 dark:text-white">
                              {doc.label}
                            </span>
                            <i
                              className={`fas fa-file-alt ml-auto ${
                                on ? "text-eko" : "text-gray-400"
                              }`}
                            ></i>
                          </label>
                        );
                      })}
                    </div>

                    <div className="mt-6 pt-4 border-t border-gray-200 dark:border-gray-700 flex justify-end gap-3">
                      <button
                        onClick={resetRM}
                        className="px-5 py-2.5 text-gray-600 dark:text-gray-300 font-medium hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                      >
                        Cancel
                      </button>
                      {confirmAuto ? (
                        <>
                          <button
                            onClick={() => setConfirmAuto(false)}
                            className="px-4 py-2.5 text-gray-600 dark:text-gray-300 font-medium hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                          >
                            Keep control
                          </button>
                          <button
                            onClick={handToAutomation}
                            disabled={enrolling}
                            className="px-5 py-2.5 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-medium rounded-lg flex items-center gap-2"
                          >
                            <i className="fas fa-paper-plane text-sm"></i>
                            <span>
                              {enrolling
                                ? "Handing over…"
                                : `Yes — email ${csp.name || csp.csp_id}`}
                            </span>
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => setConfirmAuto(true)}
                          disabled={enrolling || busy || !!enrolled}
                          title="Generate and email everything automatically, without stepping through it"
                          className="px-5 py-2.5 border border-eko text-eko font-medium rounded-lg transition-colors hover:bg-eko/5 disabled:opacity-50 flex items-center gap-2"
                        >
                          <i className="fas fa-wand-magic-sparkles text-sm"></i>
                          <span>Issue automatically</span>
                        </button>
                      )}
                      <button
                        onClick={() => startGeneration()}
                        disabled={selectedDocs.length === 0 || busy}
                        className={`px-6 py-2.5 bg-eko text-white font-medium rounded-lg transition-all flex items-center gap-2 ${
                          selectedDocs.length === 0
                            ? "opacity-50 cursor-not-allowed"
                            : "hover:bg-eko-dark shadow-sm shadow-green-500/30"
                        }`}
                      >
                        <span>Generate Documents</span> <i className="fas fa-cogs"></i>
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* State 2: Generating Progress */}
          {rmStep === "generating" && (
            <div className="flex flex-col items-center justify-center py-20">
              <div className="w-16 h-16 border-4 border-gray-200 border-t-eko rounded-full animate-spin mb-6"></div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                Preparing Documents...
              </h2>
              <div className="w-64 space-y-3 mt-4 text-sm text-gray-600 dark:text-gray-300">
                <div className="flex items-center gap-2">
                  <i className="fas fa-check text-green-500"></i> Checking CSP data
                </div>
                <div className="flex items-center gap-2">
                  <i className="fas fa-circle-notch fa-spin"></i> Verifying required fields
                </div>
                <div className="flex items-center gap-2 opacity-50">
                  <i className="fas fa-circle-notch fa-spin"></i> Analyzing templates
                </div>
              </div>
            </div>
          )}

          {/* State 3: Details missing — Pending (the RM fills nothing) */}
          {rmStep === "missing_data" && missing && csp && (
            <div className="max-w-2xl mx-auto">
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-orange-200 dark:border-orange-900 overflow-hidden">
                <div className="bg-orange-50 dark:bg-orange-900/30 p-6 border-b border-orange-100 dark:border-orange-800 text-center flex flex-col items-center">
                  <div className="w-16 h-16 bg-orange-100 dark:bg-orange-800/50 text-orange-500 dark:text-orange-400 rounded-full flex items-center justify-center text-3xl mb-4">
                    <i className="fas fa-exclamation-triangle"></i>
                  </div>
                  <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
                    Details Missing
                  </h2>
                  <p className="text-gray-600 dark:text-gray-300 mt-2 text-sm">
                    The CSP will be asked for these on WhatsApp. The documents
                    will be made and sent to them automatically once the
                    details are in the sheet. Nothing else is needed from you.
                  </p>
                </div>

                {/* Alert Context: CSP Details */}
                <div className="p-5 bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 bg-white dark:bg-gray-800 rounded-full shadow-sm border border-gray-200 dark:border-gray-700 flex items-center justify-center text-gray-400 text-xl">
                      <i className="fas fa-store"></i>
                    </div>
                    <div>
                      <div className="font-bold text-gray-900 dark:text-white">
                        {missing.csp_name}
                      </div>
                      <div className="text-xs text-gray-500 font-medium mt-0.5">
                        ID:{" "}
                        <span className="text-gray-700 dark:text-gray-300">
                          {missing.csp_id}
                        </span>{" "}
                        &bull; RM:{" "}
                        <span className="text-gray-700 dark:text-gray-300">
                          {csp.rm_name || "Unassigned"}
                        </span>
                      </div>
                    </div>
                  </div>
                  <span className="px-2.5 py-1 bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400 text-[10px] uppercase tracking-wider rounded font-bold border border-orange-200 dark:border-orange-800">
                    Pending
                  </span>
                </div>

                <div className="p-6 md:p-8 space-y-3">
                  {uniqueFields(missing).map((field) => (
                    <div
                      key={field.field_name}
                      className="flex justify-between items-center gap-4 text-sm py-2 border-b border-gray-100 dark:border-gray-700 last:border-0"
                    >
                      <span className="font-medium text-gray-700 dark:text-gray-300">
                        {field.field_label}
                      </span>
                      <span className="text-xs text-orange-500 text-right">
                        <i className="fas fa-info-circle"></i> Needed for{" "}
                        {blockedBy(missing, field.field_name).join(", ")}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="p-6 bg-gray-50 dark:bg-gray-900/50 border-t border-gray-200 dark:border-gray-700 flex justify-between items-center">
                  <div className="text-sm text-gray-500">
                    Status:{" "}
                    <strong className="text-orange-600 dark:text-orange-400">
                      Pending — waiting for the CSP
                    </strong>
                  </div>
                  <button
                    onClick={resetRM}
                    className="px-6 py-2.5 bg-eko hover:bg-eko-dark text-white font-medium rounded-lg shadow-sm transition-all flex items-center gap-2"
                  >
                    <i className="fas fa-arrow-left"></i>
                    <span>Back to search</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* State 4: Validation Screen */}
          {rmStep === "validating" && csp && (
            <div className="max-w-2xl mx-auto">
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
                <div className="p-6 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
                  <div>
                    <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                      Document Validation
                    </h2>
                    <p className="text-sm text-gray-500">
                      {csp.name} ({csp.csp_id})
                    </p>
                  </div>
                  <div className="w-12 h-12 bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400 rounded-full flex items-center justify-center text-2xl">
                    <i className="fas fa-check-double"></i>
                  </div>
                </div>
                <div className="p-6 bg-gray-50 dark:bg-gray-900/30">
                  <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">
                    Generated Documents
                  </h4>
                  <div className="flex flex-wrap gap-2 mb-6">
                    {selectedDocs.map((key) => (
                      <span
                        key={key}
                        className="px-3 py-1 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded text-sm font-medium text-gray-700 dark:text-gray-200 shadow-sm"
                      >
                        <i className="fas fa-file-pdf text-red-500 mr-1.5"></i>{" "}
                        {docLabel(key)}
                      </span>
                    ))}
                  </div>

                  <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">
                    Automated Checks
                  </h4>
                  <ul className="space-y-3 bg-white dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700 shadow-sm">
                    {[
                      "Every required field present",
                      "Each value matches the CSP record",
                      "No placeholder left unfilled",
                      "Converted to PDF and stored",
                    ].map((check) => (
                      <li
                        key={check}
                        className="flex items-center gap-3 text-sm font-medium text-gray-800 dark:text-gray-200"
                      >
                        <i className="fas fa-check-circle text-eko"></i> {check}
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="p-6 border-t border-gray-200 dark:border-gray-700 flex justify-end">
                  <button
                    onClick={() => setRmStep("confirm_email")}
                    className="px-6 py-2.5 bg-navy-800 hover:bg-navy-900 dark:bg-gray-700 dark:hover:bg-gray-600 text-white font-medium rounded-lg transition-all flex items-center gap-2"
                  >
                    <span>Continue to Email</span> <i className="fas fa-envelope"></i>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* State 5: Email Confirmation */}
          {rmStep === "confirm_email" && csp && (
            <div className="max-w-md mx-auto">
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 overflow-hidden text-center">
                <div className="p-8">
                  <div className="w-20 h-20 bg-blue-50 dark:bg-blue-900/20 text-blue-500 dark:text-blue-400 rounded-full flex items-center justify-center text-3xl mx-auto mb-4 border border-blue-100 dark:border-blue-800/50">
                    <i className="fas fa-paper-plane"></i>
                  </div>
                  <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                    Confirm Delivery
                  </h2>
                  <p className="text-sm text-gray-500 mb-6">
                    You are about to send{" "}
                    <strong className="text-gray-800 dark:text-gray-200">
                      {selectedDocs.length}
                    </strong>{" "}
                    documents to the CSP.
                  </p>

                  <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4 text-left border border-gray-100 dark:border-gray-700 mb-6">
                    <div className="text-xs text-gray-500 mb-1">Recipient Email</div>
                    <div className="font-medium text-gray-900 dark:text-white mb-3 break-all">
                      {recipient || csp.email}
                    </div>
                    <div className="text-xs text-gray-500 mb-1">Subject</div>
                    <div className="font-medium text-gray-900 dark:text-white text-sm">
                      Your CSP Documents — {csp.csp_id} | EKO India Financial Services
                    </div>
                  </div>

                  <div className="flex gap-3">
                    <button
                      onClick={resetRM}
                      className="w-1/3 py-2.5 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-all"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={sendEmail}
                      disabled={busy}
                      className="w-2/3 py-2.5 bg-eko hover:bg-eko-dark disabled:opacity-50 text-white font-medium rounded-lg shadow-sm shadow-green-500/30 transition-all flex justify-center items-center gap-2"
                    >
                      <span>{busy ? "Sending..." : "Send Documents"}</span>
                      <i className="fas fa-paper-plane text-xs"></i>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* State 6: Success */}
          {rmStep === "success" && (
            <div className="max-w-lg mx-auto">
              <div
                className={`bg-white dark:bg-gray-800 rounded-xl shadow-lg border overflow-hidden text-center p-10 ${
                  processingError
                    ? "border-red-200 dark:border-red-900"
                    : "border-green-200 dark:border-green-900"
                }`}
              >
                <div
                  className={`w-24 h-24 rounded-full flex items-center justify-center text-4xl mx-auto mb-6 ${
                    processingError
                      ? "bg-red-100 dark:bg-red-900/30 text-red-600"
                      : "bg-green-100 dark:bg-green-900/30 text-eko"
                  }`}
                >
                  <i className={`fas ${processingError ? "fa-xmark" : "fa-check"}`}></i>
                </div>
                <h2 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
                  {processingError ? "Not Sent" : "Sent Successfully"}
                </h2>
                <p className="text-gray-600 dark:text-gray-300 mb-8">
                  {processingError || (
                    <>
                      {sentCount} document{sentCount === 1 ? "" : "s"} have been
                      generated and emailed to <strong>{recipient}</strong>.
                    </>
                  )}
                </p>

                <div className="flex flex-col gap-3">
                  <button
                    onClick={resetRM}
                    className="w-full py-3 bg-eko hover:bg-eko-dark text-white font-medium rounded-lg transition-all"
                  >
                    Generate Another
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
