"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

type Theme = "dark" | "light";

interface ThemeContextValue {
  theme: Theme;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("bl-theme") as Theme | null;
    if (stored) {
      setTheme(stored);
      document.documentElement.className = `theme-${stored}`;
    } else {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const detected = prefersDark ? "dark" : "light";
      setTheme(detected);
      document.documentElement.className = `theme-${detected}`;
    }
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const stored = localStorage.getItem("bl-theme");
    if (stored) return; // user overrode, don't listen to system

    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      const t = e.matches ? "dark" : "light";
      setTheme(t);
      document.documentElement.className = `theme-${t}`;
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [mounted]);

  const toggle = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("bl-theme", next);
    document.documentElement.className = `theme-${next}`;
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
