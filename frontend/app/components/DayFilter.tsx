"use client";

/**
 * The day filter (No. 272): the Admin dashboard's "All days / Today /
 * Yesterday / On a date… / From – To…" (No. 171), for every list. Days are
 * India days (Asia/Kolkata) whatever the browser's own time zone.
 *
 * A page keeps a DayChoice in its state and either
 *   - sends dayRange(choice) to its API as date_from / date_to (inclusive
 *     India days, YYYY-MM-DD), or
 *   - filters rows it already has with inDays(row's timestamp, dayRange(choice)).
 */

export type DayMode = "" | "today" | "yesterday" | "on" | "range";

export interface DayChoice {
  mode: DayMode;
  on: string;
  from: string;
  to: string;
}

export interface DayRange {
  date_from?: string;
  date_to?: string;
}

export const NO_DAY: DayChoice = { mode: "", on: "", from: "", to: "" };

const MODES: DayMode[] = ["", "today", "yesterday", "on", "range"];
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** YYYY-MM-DD in India, `offset` days from today. */
export function indiaDay(offset = 0): string {
  return new Date(Date.now() + offset * 86_400_000).toLocaleDateString("en-CA", {
    timeZone: "Asia/Kolkata",
  });
}

/** The India day (YYYY-MM-DD) a moment fell on; "" for none. */
export function indiaDayOf(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

/** "1 Nov 2026" for a YYYY-MM-DD day. */
export function showDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
}

/** A choice read back from storage, made safe (anything odd = all days). */
export function cleanDayChoice(value: unknown): DayChoice {
  if (!value || typeof value !== "object") return NO_DAY;
  const v = value as Record<string, unknown>;
  const day = (x: unknown) => (typeof x === "string" && DAY.test(x) ? x : "");
  const mode = MODES.includes(v.mode as DayMode) ? (v.mode as DayMode) : "";
  return { mode, on: day(v.on), from: day(v.from), to: day(v.to) };
}

/** "To" is before "From": nothing is applied until it is put right. */
export function dayRangeWrong(c: DayChoice): boolean {
  return c.mode === "range" && !!c.from && !!c.to && c.to < c.from;
}

/** The choice as date_from / date_to India days (both inclusive); {} = all days. */
export function dayRange(c: DayChoice): DayRange {
  if (c.mode === "today") {
    const t = indiaDay(0);
    return { date_from: t, date_to: t };
  }
  if (c.mode === "yesterday") {
    const y = indiaDay(-1);
    return { date_from: y, date_to: y };
  }
  if (c.mode === "on" && c.on) return { date_from: c.on, date_to: c.on };
  if (c.mode === "range" && !dayRangeWrong(c) && (c.from || c.to)) {
    return { ...(c.from ? { date_from: c.from } : {}), ...(c.to ? { date_to: c.to } : {}) };
  }
  return {};
}

/** Is anything actually being filtered on? */
export function dayApplied(c: DayChoice): boolean {
  const r = dayRange(c);
  return !!(r.date_from || r.date_to);
}

/** Does this moment fall on the days? No day asked = yes; no moment = no. */
export function inDays(iso: string | null | undefined, r: DayRange): boolean {
  if (!r.date_from && !r.date_to) return true;
  const day = indiaDayOf(iso);
  if (!day) return false;
  if (r.date_from && day < r.date_from) return false;
  if (r.date_to && day > r.date_to) return false;
  return true;
}

/** "Today (27 Nov 2026)", "1 Nov 2026 – 5 Nov 2026", … ; "" = all days. */
export function dayLabel(c: DayChoice): string {
  const r = dayRange(c);
  if (c.mode === "today") return `Today (${showDay(r.date_from!)})`;
  if (c.mode === "yesterday") return `Yesterday (${showDay(r.date_from!)})`;
  if (c.mode === "on" && c.on) return showDay(c.on);
  if (c.mode === "range" && r.date_from && r.date_to) return `${showDay(r.date_from)} – ${showDay(r.date_to)}`;
  if (c.mode === "range" && r.date_from) return `From ${showDay(r.date_from)}`;
  if (c.mode === "range" && r.date_to) return `Up to ${showDay(r.date_to)}`;
  return "";
}

const BOX =
  "w-full px-2 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 dark:text-white focus:ring-2 focus:ring-eko outline-none cursor-pointer";
const LABEL = "block text-xs font-medium text-gray-500";

/**
 * The select and its date boxes. "stack" (the dashboard's look): the label
 * and a "Clear filter" link above, the dates below. "row": everything on one
 * line, for a toolbar of filters.
 */
export default function DayFilter({
  label,
  value,
  onChange,
  layout = "stack",
  boxClass = BOX,
  labelClass = LABEL,
  className = "",
  id,
}: {
  label: string;
  value: DayChoice;
  onChange: (next: DayChoice) => void;
  layout?: "stack" | "row";
  boxClass?: string;
  labelClass?: string;
  className?: string;
  id?: string;
}) {
  const today = indiaDay(0);
  const wrong = dayRangeWrong(value);
  const set = (patch: Partial<DayChoice>) => onChange({ ...value, ...patch });
  const selectId = id ?? `day-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`;

  const select = (
    <select
      id={selectId}
      value={value.mode}
      onChange={(e) => set({ mode: e.target.value as DayMode })}
      className={layout === "row" ? `${boxClass} !w-auto` : boxClass}
    >
      <option value="">All days</option>
      <option value="today">Today</option>
      <option value="yesterday">Yesterday</option>
      <option value="on">On a date…</option>
      <option value="range">From – To…</option>
    </select>
  );
  const on = value.mode === "on" && (
    <input
      type="date"
      value={value.on}
      max={today}
      onChange={(e) => set({ on: e.target.value })}
      aria-label={`${label}: date`}
      className={layout === "row" ? `${boxClass} !w-auto` : `${boxClass} mt-2`}
    />
  );
  const range = value.mode === "range" && (
    <>
      <input
        type="date"
        value={value.from}
        max={value.to || today}
        onChange={(e) => set({ from: e.target.value })}
        aria-label={`${label}: from`}
        title="From"
        className={layout === "row" ? `${boxClass} !w-auto` : boxClass}
      />
      <input
        type="date"
        value={value.to}
        min={value.from || undefined}
        max={today}
        onChange={(e) => set({ to: e.target.value })}
        aria-label={`${label}: to`}
        title="To"
        className={layout === "row" ? `${boxClass} !w-auto` : boxClass}
      />
    </>
  );
  const wrongNote = wrong && (
    <p className="text-xs text-red-600 dark:text-red-400">
      &ldquo;To&rdquo; is before &ldquo;From&rdquo;.
    </p>
  );
  const clear = value.mode && (
    <button type="button" onClick={() => onChange(NO_DAY)} className="text-xs text-eko hover:underline">
      Clear filter
    </button>
  );

  if (layout === "row") {
    return (
      <div className={`flex flex-wrap items-center gap-2 ${className}`}>
        <label htmlFor={selectId} className="text-sm text-gray-600 dark:text-gray-300">
          {label}
        </label>
        {select}
        {on}
        {range}
        {clear}
        {wrongNote}
      </div>
    );
  }
  return (
    <div className={`min-w-0 ${className}`}>
      <div className="flex items-center justify-between mb-1 gap-2">
        <label htmlFor={selectId} className={labelClass.replace(/\bmb-\d+\b/, "")}>
          {label}
        </label>
        {clear}
      </div>
      {select}
      {on}
      {value.mode === "range" && <div className="mt-2 grid grid-cols-2 gap-2">{range}</div>}
      {wrong && <div className="mt-1">{wrongNote}</div>}
    </div>
  );
}
