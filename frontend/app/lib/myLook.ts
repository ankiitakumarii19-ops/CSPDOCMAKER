"use client";

/**
 * Each person's own look (No. 240, SaaS upgrade Stage 2) — the one place
 * that turns a person's choices into styles.
 *
 * Order: the app's built-in look → the workspace's Display choice (Setup →
 * Display; lib/useMyAccess.ts) → the person's own choices (this file).
 *
 * Their choices become ONE <style id="my-look"> element on their own page,
 * built from what the server returned for them (GET /api/profile/appearance).
 * Nothing goes into shared CSS files or shared state: another person's
 * screen never sees it. Removing the element = the workspace's look again.
 *
 * So the next visit paints in it at once (no flash), the built stylesheet is
 * also kept in this browser under "myLook:<email>" and put back by the
 * script in app/layout.tsx before the page is drawn — per person, so two
 * people sharing a browser each get their own.
 */

import { api } from "./api";

export type Appearance = Partial<{
  mode: "light" | "dark" | "system";
  background: string;
  menu: string;
  accent: string;
  button: string;
  card: string;
  border: string;
  font: "inter" | "roboto" | "poppins" | "open_sans" | "lato" | "system";
  text_size: number;
  heading_size: number;
  weight: "light" | "normal" | "medium";
  line_spacing: "tight" | "normal" | "relaxed" | "loose";
  menu_state: "expanded" | "collapsed";
  menu_side: "left" | "right";
  density: "compact" | "comfortable" | "spacious";
  cards: "rounded" | "square";
  table_density: "compact" | "normal" | "spacious";
  high_contrast: boolean;
  motion: "standard" | "reduce" | "device";
  scale: number;
  focus_outline: boolean;
}>;

export interface AppearanceOption {
  key: keyof Appearance;
  label: string;
  group: "appearance" | "typography" | "layout" | "accessibility";
  kind: "pick" | "number" | "switch" | "colour";
  help: string;
  values?: { value: string; name: string }[];
  low?: number;
  high?: number;
  step?: number;
  unit?: string;
}

export interface AppearanceView {
  /** No. 240 (Stage 3): false = the workspace keeps colours and font. */
  own_colours_allowed?: boolean;
  appearance: Appearance;
  updated_at: string | null;
  options: AppearanceOption[];
  warnings: string[];
}

const STYLE_ID = "my-look";
const FONT_ID = "my-look-font";

const FONT_STACK: Record<string, string> = {
  inter: "Inter, sans-serif",
  roboto: "Roboto, sans-serif",
  poppins: "Poppins, sans-serif",
  open_sans: "'Open Sans', sans-serif",
  lato: "Lato, sans-serif",
  system: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
};
// Inter is already loaded by globals.css; the others only when chosen.
const FONT_FAMILY: Record<string, string> = {
  roboto: "Roboto", poppins: "Poppins", open_sans: "Open+Sans", lato: "Lato",
};

// Tailwind's own sizes (rem), which the person's text / heading size scale.
const BODY_SIZES: Record<string, number> = { xs: 0.75, sm: 0.875, base: 1 };
const HEADING_SIZES: Record<string, number> = {
  lg: 1.125, xl: 1.25, "2xl": 1.5, "3xl": 1.875, "4xl": 2.25,
};
const LEADING: Record<string, number> = { tight: 1.25, relaxed: 1.65, loose: 1.9 };

const HEX = /^#[0-9a-f]{6}$/i;

/** Mix a #rrggbb colour toward black (amount < 0) or white (amount > 0). */
function shade(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const parts = [n >> 16, (n >> 8) & 255, n & 255].map((c) =>
    Math.round(amount < 0 ? c * (1 + amount) : c + (255 - c) * amount)
  );
  return `#${parts.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

function colour(value: unknown): string | null {
  return typeof value === "string" && HEX.test(value) ? value.toLowerCase() : null;
}

// No. 240 (Stage 3): Settings -> "People may pick their own colours". Off:
// the person's colours and font are not shown (light / dark, sizes, layout
// and accessibility still are). Mirrors services/my_look.WORKSPACE_LOCKABLE.
export const WORKSPACE_LOCKABLE = ["background", "menu", "accent", "button", "card", "border", "font"] as const;
let ownColours = true;

export function setOwnColoursAllowed(allowed: boolean) {
  if (ownColours === allowed) return;
  ownColours = allowed;
  applyMyLook(saved);
  remember(saved);
}

export function ownColoursAllowed(): boolean {
  return ownColours;
}

function shown(look: Appearance): Appearance {
  if (ownColours) return look;
  const copy = { ...look } as Record<string, unknown>;
  for (const k of WORKSPACE_LOCKABLE) delete copy[k];
  return copy as Appearance;
}

export interface Paint {
  css: string;
  /** true = dark, false = light, null = as the device / workspace has it. */
  dark: boolean | null;
  /** "system" — follow the device. */
  followDevice: boolean;
  font: string | null;
}

/** The stylesheet for a set of choices. Pure: easy to check, and the same
 *  text is what the pre-paint script puts back. */
export function paintFor(look: Appearance): Paint {
  const vars: string[] = [];
  const rules: string[] = [];

  // ---- Colours ----
  const accent = colour(look.accent);
  if (accent) {
    vars.push(`--color-eko:${accent}`, `--color-eko-dark:${shade(accent, -0.16)}`,
      `--color-eko-light:${shade(accent, 0.9)}`);
  }
  const button = colour(look.button);
  if (button) {
    rules.push(`button.bg-eko,a.bg-eko{background-color:${button}}`,
      `button.bg-eko:hover,a.bg-eko:hover{background-color:${shade(button, -0.16)}}`);
  }
  const background = colour(look.background);
  // `when` narrows it (":not(.dark)" = light mode only). The logo strip on
  // top of the menu goes with it, unless the workspace gave it a second
  // colour (Setup -> Display).
  const menuRules = (menu: string, when = "") => {
    const lift = shade(menu, 0.1);
    const at = `html${when} `;
    rules.push(`${at}[data-shell-menu]{background-color:${menu}}`,
      `${at}[data-shell-menu] .bg-navy-800,${at}[data-shell-menu] .hover\\:bg-navy-800:hover,` +
      `html${when}:not([data-brand-2]) [data-shell-brand]{background-color:${lift}}`);
  };
  // 27 Nov: a person who picked an accent or page background but left
  // "Side menu" empty saw the menu stay in the workspace look's colour (e.g.
  // Sunset brown beside a purple page). Now the menu follows their colour,
  // as a dark shade of it (the same depth the Display looks use, readable
  // with the menu's light text). Its own box, when set, still wins. Taken
  // from the page background only in light mode, where that colour shows.
  const menu = colour(look.menu);
  if (menu) menuRules(menu);
  else if (accent) menuRules(shade(accent, -0.8));
  else if (background) menuRules(shade(background, -0.8), ":not(.dark)");

  if (background) {
    rules.push(`html:not(.dark) body,html:not(.dark) .bg-gray-50{background-color:${background}}`);
  }
  const card = colour(look.card);
  if (card) {
    rules.push(`html:not(.dark) :is(.rounded-xl,.rounded-2xl).bg-white{background-color:${card}}`);
  }
  const border = colour(look.border);
  if (border) {
    rules.push(`html:not(.dark) :is(.border-gray-100,.border-gray-200,.border-gray-300){border-color:${border}}`);
  }

  // ---- Typography ----
  const font = look.font && FONT_STACK[look.font] ? look.font : null;
  if (font) vars.push(`--font-sans:${FONT_STACK[font]}`);
  const text = typeof look.text_size === "number" ? look.text_size / 100 : 1;
  const heading = typeof look.heading_size === "number" ? look.heading_size / 100 : 1;
  if (text !== 1) {
    for (const [k, rem] of Object.entries(BODY_SIZES)) vars.push(`--text-${k}:${+(rem * text).toFixed(4)}rem`);
  }
  if (text !== 1 || heading !== 1) {
    for (const [k, rem] of Object.entries(HEADING_SIZES))
      vars.push(`--text-${k}:${+(rem * text * heading).toFixed(4)}rem`);
  }
  if (look.weight === "light") rules.push("body{font-weight:300}");
  if (look.weight === "medium") rules.push("body{font-weight:500}");
  const leading = look.line_spacing ? LEADING[look.line_spacing] : undefined;
  if (leading) {
    rules.push(`html{line-height:${leading}}`);
    for (const k of [...Object.keys(BODY_SIZES), ...Object.keys(HEADING_SIZES)])
      vars.push(`--text-${k}--line-height:${leading}`);
  }

  // ---- Layout ----
  if (look.density === "compact") vars.push("--spacing:0.21rem");
  if (look.density === "spacious") vars.push("--spacing:0.29rem");
  if (look.cards === "square") {
    rules.push(":is(.rounded,.rounded-md,.rounded-lg,.rounded-xl,.rounded-2xl){border-radius:2px}");
  }
  if (look.table_density === "compact") rules.push(":is(td,th){padding-top:0.25rem;padding-bottom:0.25rem}");
  if (look.table_density === "spacious") rules.push(":is(td,th){padding-top:0.9rem;padding-bottom:0.9rem}");
  // The Admin pages' side menu, on a laptop or larger (a drawer below).
  if (look.menu_state === "collapsed") {
    rules.push("@media (min-width:1024px){" +
      "[data-shell-menu]{width:4.5rem}" +
      "[data-shell-menu] nav{padding-left:0.5rem;padding-right:0.5rem}" +
      "[data-shell-menu] nav button{font-size:0;justify-content:center;gap:0;padding-left:0;padding-right:0}" +
      "[data-shell-menu] nav button i{font-size:1rem}" +
      "[data-shell-menu] nav > div,[data-shell-menu] [data-shell-name],[data-shell-menu] [data-shell-foot]{display:none}" +
      "}");
  }
  if (look.menu_side === "right") {
    rules.push("@media (min-width:1024px){[data-shell]{flex-direction:row-reverse}}");
  }

  // ---- Accessibility ----
  if (look.high_contrast) {
    rules.push("html:not(.dark){--color-gray-400:#4b5563 !important;--color-gray-500:#374151 !important;--color-gray-600:#1f2937 !important}",
      "html.dark{--color-gray-400:#e5e7eb !important;--color-gray-500:#d1d5db !important;--color-gray-600:#e5e7eb !important}",
      "html:not(.dark) :is(.border-gray-100,.border-gray-200){border-color:#6b7280}",
      "html.dark :is(.border-gray-700,.border-gray-800){border-color:#9ca3af}");
  }
  const still = "*,*::before,*::after{animation-duration:0.01ms !important;animation-iteration-count:1 !important;transition-duration:0.01ms !important;scroll-behavior:auto !important}";
  if (look.motion === "reduce") rules.push(still);
  if (look.motion === "device") rules.push(`@media (prefers-reduced-motion: reduce){${still}}`);
  if (typeof look.scale === "number" && look.scale !== 100) rules.push(`html{font-size:${look.scale}%}`);
  if (look.focus_outline) {
    rules.push(":focus-visible{outline:3px solid var(--color-eko) !important;outline-offset:2px !important}");
  }

  // !important on the variables: the workspace's own colour is set on <html>
  // directly (useMyAccess), and the person's choice must win over it.
  const head = vars.length ? `:root{${vars.map((v) => `${v} !important`).join(";")}}` : "";
  return {
    css: head + rules.join(""),
    dark: look.mode === "dark" ? true : look.mode === "light" ? false : null,
    followDevice: look.mode === "system",
    font: font && FONT_FAMILY[font] ? FONT_FAMILY[font] : null,
  };
}

function fontHref(family: string): string {
  return `https://fonts.googleapis.com/css2?family=${family}:wght@300;400;500;600;700&display=swap`;
}

function myEmail(): string | null {
  try {
    const raw = localStorage.getItem("user");
    const email = raw ? (JSON.parse(raw) as { email?: string }).email : null;
    return email ? email.toLowerCase() : null;
  } catch {
    return null;
  }
}

/** Put a set of choices on this page (also used for the live preview). */
export function applyMyLook(look: Appearance) {
  if (typeof document === "undefined") return;
  const paint = paintFor(shown(look));
  const root = document.documentElement;

  let style = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!paint.css) {
    style?.remove();
  } else {
    if (!style) {
      style = document.createElement("style");
      style.id = STYLE_ID;
      document.head.appendChild(style);
    }
    if (style.textContent !== paint.css) style.textContent = paint.css;
  }

  let link = document.getElementById(FONT_ID) as HTMLLinkElement | null;
  if (!paint.font) {
    link?.remove();
  } else {
    const href = fontHref(paint.font);
    if (!link) {
      link = document.createElement("link");
      link.id = FONT_ID;
      link.rel = "stylesheet";
      document.head.appendChild(link);
    }
    if (link.href !== href) link.href = href;
  }

  // Light / dark: the person's choice, kept where the header button and the
  // pre-paint script already look ("theme"). Neon is always dark (No. 229).
  if (root.getAttribute("data-ui-style") !== "neon") {
    if (paint.dark !== null) root.classList.toggle("dark", paint.dark);
    else if (paint.followDevice) root.classList.toggle("dark", matchMedia("(prefers-color-scheme: dark)").matches);
  }
}

/** Remember the person's SAVED look in this browser, for the next visit. */
function remember(look: Appearance) {
  const email = myEmail();
  if (!email) return;
  const paint = paintFor(shown(look));
  try {
    if (look.mode === "dark" || look.mode === "light") localStorage.setItem("theme", look.mode);
    else if (look.mode === "system") localStorage.removeItem("theme");
    if (paint.css || paint.font) {
      localStorage.setItem(`myLook:${email}`,
        JSON.stringify({ css: paint.css, font: paint.font ? fontHref(paint.font) : null }));
    } else {
      localStorage.removeItem(`myLook:${email}`);
    }
  } catch {
    // A private window: the look still applies, it is just not remembered.
  }
}

let saved: Appearance = {};
let loading: Promise<Appearance> | null = null;

/** The person's saved look, as last read or saved. */
export function savedLook(): Appearance {
  return saved;
}

/** Read the saved look once per page load and put it on the page. */
export function loadMyLook(): Promise<Appearance> {
  if (!loading) {
    loading = api
      .myAppearance()
      .then((v) => {
        saved = v.appearance || {};
        ownColours = v.own_colours_allowed !== false;
        applyMyLook(saved);
        remember(saved);
        return saved;
      })
      .catch((e) => {
        // The workspace's look stays; the page still works.
        console.warn("myLook: could not read your saved look", e);
        loading = null;
        return saved;
      });
  }
  return loading;
}

/** After a save, reset or the header's light / dark button. */
export function keepSavedLook(look: Appearance) {
  saved = look;
  loading = Promise.resolve(look);
  applyMyLook(look);
  remember(look);
}

/** Signing out: nothing of this person's look stays on the page. */
export function clearMyLook() {
  saved = {};
  loading = null;
  if (typeof document === "undefined") return;
  document.getElementById(STYLE_ID)?.remove();
  document.getElementById(FONT_ID)?.remove();
}
