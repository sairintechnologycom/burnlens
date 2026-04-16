"use client";

import React, { createContext, useContext, useState } from "react";

type Period = "7d" | "30d" | "90d";

interface PeriodContextValue {
  period: Period;
  setPeriod: (p: Period) => void;
  days: number;
}

const PeriodContext = createContext<PeriodContextValue>({
  period: "7d",
  setPeriod: () => {},
  days: 7,
});

const PERIOD_DAYS: Record<Period, number> = { "7d": 7, "30d": 30, "90d": 90 };

export function PeriodProvider({ children }: { children: React.ReactNode }) {
  const [period, setPeriod] = useState<Period>("7d");
  return (
    <PeriodContext.Provider value={{ period, setPeriod, days: PERIOD_DAYS[period] }}>
      {children}
    </PeriodContext.Provider>
  );
}

export function usePeriod() {
  return useContext(PeriodContext);
}
