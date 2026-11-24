"use client";

/**
 * Setup — Display (No. 228, No. 229)
 *
 * The Super Admin picks how the app looks for everyone in the workspace, in
 * two independent choices that combine:
 *   * Look (9): colours, side-menu colour, font, spacing and text size
 *     (setting "ui_theme"; app/globals.css data-ui-theme);
 *   * Design style (15): shapes, shadows and surfaces — claymorphism,
 *     glassmorphism, brutalism, minimalism … (setting "ui_style";
 *     app/globals.css data-ui-style).
 * Both are workspace settings (history and undo on Settings); each person's
 * own light / dark choice stays theirs (Neon always uses dark).
 */

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { ApiError } from "../lib/api";
import { applyStyle, applyTheme, forgetMyAccess } from "../lib/useMyAccess";

interface Look {
  key: string;
  name: string;
  about: string;
  accent: string;
  menu: string;
  radius: number;
  font?: string;
  size: number;
}

// What each look is, for the previews. app/globals.css is what applies it.
const LOOKS: Look[] = [
  { key: "classic", name: "Eko classic", about: "The app as it has always looked: Eko green, dark navy menu.", accent: "#00B259", menu: "#1e293b", radius: 10, size: 13 },
  { key: "ocean", name: "Ocean blue", about: "Calm blue with a deep blue menu and softer corners.", accent: "#2563eb", menu: "#12305c", radius: 14, size: 13 },
  { key: "royal", name: "Royal purple", about: "Purple highlights on a dark violet menu.", accent: "#7c3aed", menu: "#2a1b4d", radius: 10, size: 13 },
  { key: "sunset", name: "Sunset orange", about: "Warm orange with a warm dark menu.", accent: "#ea580c", menu: "#3b2418", radius: 14, size: 13 },
  { key: "rose", name: "Rose", about: "Rose-red highlights on a deep wine menu.", accent: "#e11d48", menu: "#3a1424", radius: 10, size: 13 },
  { key: "forest", name: "Forest", about: "Deep green with a forest menu and a plain system font.", accent: "#15803d", menu: "#1b3326", radius: 10, font: "'Segoe UI', Roboto, system-ui, sans-serif", size: 13 },
  { key: "graphite", name: "Graphite", about: "No colour: slate grey, near-black menu, sharp corners.", accent: "#475569", menu: "#27272a", radius: 4, size: 13 },
  { key: "compact", name: "Compact", about: "Eko colours, tighter spacing and smaller text: more on one screen.", accent: "#00B259", menu: "#1e293b", radius: 6, size: 11 },
  { key: "large", name: "Large and clear", about: "Bigger text, more space and stronger green: easiest to read.", accent: "#008a45", menu: "#1e293b", radius: 14, size: 15 },
];

interface Style {
  key: string;
  name: string;
  about: string;
  page: CSSProperties;
  card: CSSProperties;
  button: CSSProperties;
  font?: string;
  dark?: boolean;
}

const A = "var(--color-eko)";

// What each design style is, for the previews. app/globals.css applies it.
const STYLES: Style[] = [
  { key: "standard", name: "Standard", about: "The app as it has always looked: clean cards, light borders.",
    page: { background: "#f8fafc" }, card: { background: "#fff", border: "1px solid #e5e7eb", borderRadius: 12 },
    button: { background: A, borderRadius: 8 } },
  { key: "clay", name: "Claymorphism", about: "Soft, puffy, rounded shapes like modelling clay.",
    page: { background: "#f3effa" }, card: { background: "#fff", borderRadius: 24, boxShadow: "8px 8px 18px rgba(0,0,0,.1), inset -4px -4px 10px rgba(0,0,0,.05), inset 4px 4px 10px #fff" },
    button: { background: A, borderRadius: 16, boxShadow: "3px 3px 8px rgba(0,0,0,.15), inset 2px 2px 4px rgba(255,255,255,.45)" } },
  { key: "neumorph", name: "Neumorphism", about: "One soft surface; shapes rise out of it with light and shadow.",
    page: { background: "#e7eaf0" }, card: { background: "#e7eaf0", borderRadius: 18, boxShadow: "7px 7px 14px #c5c9d3, -7px -7px 14px #fff" },
    button: { background: A, borderRadius: 10, boxShadow: "3px 3px 7px rgba(0,0,0,.18), -3px -3px 7px #fff" } },
  { key: "glass", name: "Glassmorphism", about: "Frosted-glass cards over a soft colour gradient.",
    page: { background: "linear-gradient(135deg, #b9f3d6, #f8fafc 45%, #e0e7ff)" }, card: { background: "rgba(255,255,255,.55)", border: "1px solid rgba(255,255,255,.8)", borderRadius: 18, backdropFilter: "blur(8px)", boxShadow: "0 6px 20px rgba(31,38,135,.12)" },
    button: { background: A, borderRadius: 10 } },
  { key: "maximal", name: "Maximalism", about: "Bold and layered: thick colour borders, gradients, big shadows.",
    page: { background: "radial-gradient(circle at 10% 10%, #b9f3d6, transparent 45%), radial-gradient(circle at 90% 20%, #fde68a, transparent 45%), #fffdf7" }, card: { background: "#fff", border: `3px solid ${A}`, borderRadius: 18, boxShadow: "6px 6px 0 #065f46" },
    button: { background: `linear-gradient(90deg, ${A}, #f59e0b)`, borderRadius: 8, boxShadow: "3px 3px 0 #111827" } },
  { key: "minimal", name: "Minimalism", about: "Nothing extra: white space, hairlines, no shadows.",
    page: { background: "#fff" }, card: { background: "#fff", border: "1px solid rgba(0,0,0,.06)", borderRadius: 8 },
    button: { background: A, borderRadius: 6 } },
  { key: "brutal", name: "Brutalism", about: "Raw and loud: thick black lines, hard shadows, square corners, typewriter font.",
    page: { background: "#fff8e1" }, card: { background: "#fff", border: "3px solid #000", borderRadius: 0, boxShadow: "5px 5px 0 #000" },
    button: { background: A, border: "2px solid #000", borderRadius: 0, boxShadow: "3px 3px 0 #000" }, font: "ui-monospace, Consolas, monospace" },
  { key: "flat", name: "Flat", about: "Solid tinted surfaces, no shadows, small corners.",
    page: { background: "#f8fafc" }, card: { background: "#eefaf3", borderRadius: 6 },
    button: { background: A, borderRadius: 4 } },
  { key: "material", name: "Material", about: "Paper cards lifted by shadows, pill-shaped buttons.",
    page: { background: "#f5f5f5" }, card: { background: "#fff", borderRadius: 12, boxShadow: "0 1px 3px rgba(0,0,0,.12), 0 4px 14px rgba(0,0,0,.08)" },
    button: { background: A, borderRadius: 999, boxShadow: "0 2px 5px rgba(0,0,0,.2)" }, font: "Roboto, 'Segoe UI', sans-serif" },
  { key: "skeuo", name: "Skeuomorphism", about: "Real-world feel: glossy buttons, bevelled cards, textured page.",
    page: { background: "repeating-linear-gradient(45deg, #f1ede4 0 2px, #ece7dc 2px 4px)" }, card: { background: "linear-gradient(#fff, #f2f2f2)", border: "1px solid #cfcfcf", borderRadius: 10, boxShadow: "inset 0 1px 0 #fff, 0 3px 6px rgba(0,0,0,.18)" },
    button: { background: `linear-gradient(to bottom, rgba(255,255,255,.35), rgba(0,0,0,.15)), ${A}`, border: "1px solid rgba(0,0,0,.3)", borderRadius: 8 } },
  { key: "neon", name: "Neon", about: "Glowing lines in the dark (always dark mode).",
    page: { background: "#05060d" }, card: { background: "#0b0d18", border: `1px solid ${A}`, borderRadius: 12, boxShadow: `0 0 12px ${A}` },
    button: { background: A, borderRadius: 8, boxShadow: `0 0 12px ${A}` }, dark: true },
  { key: "retro", name: "Retro 80s", about: "Sunset gradients, pink lines and cyan offset shadows.",
    page: { background: "linear-gradient(180deg, #ffe3f6, #f3e8ff 50%, #dffcff)" }, card: { background: "#fff", border: "2px solid #ff4fbf", borderRadius: 6, boxShadow: "5px 5px 0 #00d5ff" },
    button: { background: "linear-gradient(90deg, #ff4fbf, #8b5cf6, #00d5ff)", borderRadius: 6 } },
  { key: "paper", name: "Paper / editorial", about: "Like a printed page: serif type, warm paper, fine rules.",
    page: { background: "#f6f1e6" }, card: { background: "#fffdf7", border: "1px solid #d8cfbd", borderRadius: 2 },
    button: { background: A, borderRadius: 2 }, font: "Georgia, 'Times New Roman', serif" },
  { key: "bento", name: "Bento grid", about: "Big rounded tiles on a soft grey page.",
    page: { background: "#eef0f4" }, card: { background: "#fff", borderRadius: 24 },
    button: { background: A, borderRadius: 14 } },
  { key: "aurora", name: "Aurora", about: "A soft northern-lights glow behind light, frosted cards.",
    page: { background: "radial-gradient(ellipse at 20% 0%, #b9f3d6, transparent 55%), radial-gradient(ellipse at 80% 10%, #ddd6fe, transparent 55%), radial-gradient(ellipse at 50% 100%, #a5f3fc, transparent 55%), #f8fafc" }, card: { background: "rgba(255,255,255,.78)", borderRadius: 18, boxShadow: "0 10px 30px rgba(15,23,42,.08)" },
    button: { background: A, borderRadius: 10 } },
];

function LookPreview({ look }: { look: Look }) {
  return (
    <div
      className="flex h-28 overflow-hidden border border-gray-200 dark:border-gray-700 bg-gray-50"
      style={{ borderRadius: look.radius, fontFamily: look.font }}
    >
      <div className="w-1/4 p-2 space-y-1.5" style={{ background: look.menu }}>
        <div className="h-1.5 rounded bg-white/70 w-3/4" />
        <div className="h-1.5 rounded w-full" style={{ background: look.accent }} />
        <div className="h-1.5 rounded bg-white/30 w-2/3" />
        <div className="h-1.5 rounded bg-white/30 w-3/4" />
      </div>
      <div className="flex-1 p-2 space-y-1.5">
        <div className="font-semibold text-gray-800" style={{ fontSize: look.size }}>Dashboard</div>
        <div className="bg-white border border-gray-200 p-1.5" style={{ borderRadius: look.radius }}>
          <div className="text-gray-500" style={{ fontSize: look.size - 2 }}>CSPs total</div>
          <div className="font-bold text-gray-900" style={{ fontSize: look.size + 2 }}>1,284</div>
        </div>
        <span
          className="inline-block text-white px-2 py-0.5"
          style={{ background: look.accent, borderRadius: look.radius, fontSize: look.size - 2 }}
        >
          Save
        </span>
      </div>
    </div>
  );
}

function StylePreview({ style }: { style: Style }) {
  const text = style.dark ? "#e5e7eb" : "#111827";
  const soft = style.dark ? "#9ca3af" : "#6b7280";
  return (
    <div className="h-28 overflow-hidden rounded-md p-3 flex gap-3 items-center" style={{ ...style.page, fontFamily: style.font }}>
      <div className="flex-1 p-2.5" style={style.card}>
        <div style={{ fontSize: 11, color: soft }}>CSPs total</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: text }}>1,284</div>
      </div>
      <span className="text-white text-xs font-semibold px-3 py-1.5" style={style.button}>
        Save
      </span>
    </div>
  );
}

function Card({
  chosen,
  canChange,
  busy,
  name,
  about,
  preview,
  onChoose,
}: {
  chosen: boolean;
  canChange: boolean;
  busy: boolean;
  name: string;
  about: string;
  preview: React.ReactNode;
  onChoose: () => void;
}) {
  return (
    <div
      className={`rounded-xl border bg-white dark:bg-gray-800 p-4 space-y-3 ${
        chosen ? "border-eko ring-2 ring-eko/40" : "border-gray-200 dark:border-gray-700"
      }`}
    >
      {preview}
      <div>
        <div className="flex items-center gap-2">
          <span className="font-semibold text-gray-900 dark:text-white">{name}</span>
          {chosen && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-eko-light text-eko-dark">In use</span>
          )}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{about}</p>
      </div>
      {canChange && !chosen && (
        <button
          className="px-3 py-1.5 rounded-lg text-sm font-semibold bg-eko hover:bg-eko-dark text-white disabled:opacity-50"
          disabled={busy}
          onClick={onChoose}
        >
          Use this
        </button>
      )}
    </div>
  );
}

export default function Display() {
  const [theme, setTheme] = useState<string | null>(null);
  const [style, setStyle] = useState<string | null>(null);
  const [canChange, setCanChange] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .workspaceSettings()
      .then((v) => {
        if (!alive) return;
        const t = v.settings.find((x) => x.key === "ui_theme");
        const s = v.settings.find((x) => x.key === "ui_style");
        setTheme(String(t?.value ?? "classic"));
        setStyle(String(s?.value ?? "standard"));
        setCanChange(Boolean(t?.can_change));
      })
      .catch((e) => alive && setError((e as ApiError).detail || "Could not load the display."));
    return () => {
      alive = false;
    };
  }, []);

  async function save(key: "ui_theme" | "ui_style", value: string, name: string) {
    setBusy(true);
    setError("");
    try {
      await api.changeSetting(key, value);
      if (key === "ui_theme") {
        applyTheme(value);
        setTheme(value);
      } else {
        applyStyle(value);
        setStyle(value);
      }
      forgetMyAccess();
      setMessage(`“${name}” is now in use for everyone in this workspace.`);
    } catch (e) {
      setError((e as ApiError).detail || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8 max-w-6xl">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white">Display</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Choose how the app looks for everyone in this workspace: a <strong>look</strong> (colours) and a{" "}
          <strong>design style</strong> (shapes, shadows and surfaces) — any look goes with any style. Each
          person still picks light or dark for themselves. Undo any time: Settings → History.
        </p>
        {!canChange && theme && <p className="text-xs text-gray-500 mt-1">Only the Super Admin can change the display.</p>}
      </div>
      {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
      {message && <div className="text-sm text-eko-dark dark:text-eko">{message}</div>}
      {!theme && !error && <div className="text-sm text-gray-500">Loading…</div>}

      {theme && style && (
        <>
          <section className="space-y-3">
            <h3 className="text-base font-bold text-gray-900 dark:text-white">Design style ({STYLES.length})</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {STYLES.map((s) => (
                <Card
                  key={s.key}
                  chosen={style === s.key}
                  canChange={canChange}
                  busy={busy}
                  name={s.name}
                  about={s.about}
                  preview={<StylePreview style={s} />}
                  onChoose={() => save("ui_style", s.key, s.name)}
                />
              ))}
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="text-base font-bold text-gray-900 dark:text-white">Look — colours ({LOOKS.length})</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {LOOKS.map((l) => (
                <Card
                  key={l.key}
                  chosen={theme === l.key}
                  canChange={canChange}
                  busy={busy}
                  name={l.name}
                  about={l.about}
                  preview={<LookPreview look={l} />}
                  onChoose={() => save("ui_theme", l.key, l.name)}
                />
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
