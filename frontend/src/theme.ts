// Theme controller: Light / Dark / System.
//
// The stored preference is one of "light" | "dark" | "system". The *resolved*
// theme (what's actually applied) is always "light" or "dark" and is written to
// the <html data-theme> attribute, which drives the CSS variable palette in
// styles.css. An inline script in index.html applies the same logic before first
// paint to avoid a flash of the wrong theme; this module keeps it in sync at
// runtime and reacts to OS-level changes while the preference is "system".

export type ThemePref = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const KEY = "repassist.theme";
const media = () => window.matchMedia("(prefers-color-scheme: dark)");

export function getThemePref(): ThemePref {
  const v = localStorage.getItem(KEY);
  return v === "light" || v === "dark" || v === "system" ? v : "system";
}

export function resolveTheme(pref: ThemePref = getThemePref()): ResolvedTheme {
  if (pref === "system") return media().matches ? "dark" : "light";
  return pref;
}

function apply(resolved: ResolvedTheme) {
  document.documentElement.setAttribute("data-theme", resolved);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", resolved === "dark" ? "#17191c" : "#0b0b0b");
}

export function setThemePref(pref: ThemePref) {
  localStorage.setItem(KEY, pref);
  apply(resolveTheme(pref));
  window.dispatchEvent(new CustomEvent("themechange", { detail: pref }));
}

// React to OS theme changes while the preference is "system". Safe to call once
// at startup; returns an unsubscribe fn.
export function watchSystemTheme(): () => void {
  const m = media();
  const onChange = () => { if (getThemePref() === "system") apply(resolveTheme("system")); };
  m.addEventListener?.("change", onChange);
  return () => m.removeEventListener?.("change", onChange);
}
