import { useCallback, useEffect, useState } from "react";

import { loadTheme, storeTheme } from "../storage";

export type Theme = "light" | "dark";

/**
 * Light/dark theme. Follows the OS until the user picks one explicitly; after
 * that their choice is remembered. (index.html applies the saved theme before
 * first paint, so this hook only has to keep React state in sync.)
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );
  const [chosen, setChosen] = useState<boolean>(() => loadTheme() !== null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    if (chosen) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setTheme(query.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [chosen]);

  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    const root = document.documentElement;
    root.classList.add("theme-switching");
    window.setTimeout(() => root.classList.remove("theme-switching"), 350);
    setTheme(next);
    setChosen(true);
    storeTheme(next);
  }, [theme]);

  return { theme, toggle };
}
