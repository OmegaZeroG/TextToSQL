import { useCallback, useEffect, useState } from "react";

import { storeTheme } from "../storage";

export type Theme = "light" | "dark";

/**
 * Light/dark theme. Light unless the visitor has chosen dark, in which case that
 * choice is remembered. The operating system's setting is deliberately ignored.
 * (index.html applies the saved theme before first paint, so this hook only has
 * to keep React state in sync.)
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    // Colours the phone's browser bar to match the page.
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#14201b" : "#f8f6f1");
  }, [theme]);

  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    const root = document.documentElement;
    root.classList.add("theme-switching");
    window.setTimeout(() => root.classList.remove("theme-switching"), 350);
    setTheme(next);
    storeTheme(next);
  }, [theme]);

  return { theme, toggle };
}
