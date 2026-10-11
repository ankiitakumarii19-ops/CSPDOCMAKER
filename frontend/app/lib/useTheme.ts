"use client";

import { useSyncExternalStore } from "react";

/** The theme lives as a class on <html>, applied before paint by the inline
 *  script in layout.tsx. Reading it through the DOM keeps one source of
 *  truth; a MutationObserver keeps React in step. */
function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
  return () => observer.disconnect();
}

function current(): "dark" | "light" {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function onServer(): "dark" | "light" {
  return "light";
}

/** Returns the theme and a toggle. Reading via useSyncExternalStore rather
 *  than an effect avoids a cascading render on every mount. */
export function useTheme(): ["dark" | "light", () => void] {
  const theme = useSyncExternalStore(subscribe, current, onServer);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    try {
      localStorage.setItem("theme", next);
    } catch {
      // Private browsing: the choice will not persist.
    }
  };

  return [theme, toggle];
}
