/** Theme preference: system / light / dark. The resolved value lives on <html data-theme>. */
export type ThemePref = "system" | "light" | "dark";

const KEY = "bk.theme";
const media = () => window.matchMedia("(prefers-color-scheme: dark)");

export function themePref(): ThemePref {
  return (localStorage.getItem(KEY) as ThemePref | null) ?? "system";
}

export function applyTheme(pref: ThemePref = themePref()): void {
  const dark = pref === "dark" || (pref === "system" && media().matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function setThemePref(pref: ThemePref): void {
  localStorage.setItem(KEY, pref);
  applyTheme(pref);
}

/** Follow OS changes while the preference is “system”. */
export function watchSystemTheme(): () => void {
  const m = media();
  const onChange = () => themePref() === "system" && applyTheme("system");
  m.addEventListener("change", onChange);
  return () => m.removeEventListener("change", onChange);
}
