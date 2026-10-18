/** Light, dark or the system's: kept in localStorage, applied as `.dark` on `<html>`. */
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";
const STORAGE_KEY = "tri-al-theme"; // index.html reads it too, before the first paint

type ThemeState = { theme: Theme; resolved: "light" | "dark"; setTheme: (theme: Theme) => void };

const ThemeContext = createContext<ThemeState | null>(null);

function stored(): Theme {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function systemDark(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(stored);
  const [system, setSystem] = useState<"light" | "dark">(() => (systemDark() ? "dark" : "light"));
  const resolved = theme === "system" ? system : theme;

  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const query = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSystem(query.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolved === "dark");
  }, [resolved]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      if (next === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private windows may refuse storage; the theme still applies until reload.
    }
  }, []);

  return <ThemeContext value={{ theme, resolved, setTheme }}>{children}</ThemeContext>;
}

export function useTheme(): ThemeState {
  const state = useContext(ThemeContext);
  if (!state) throw new Error("useTheme needs a ThemeProvider");
  return state;
}
