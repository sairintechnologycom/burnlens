"use client";

import { useEffect, useRef } from "react";
import { Bar } from "react-chartjs-2";
import { applyChartDefaults, getThemeColors } from "@/lib/chartDefaults";
import { useTheme } from "@/components/ThemeProvider";

interface VerticalBarProps {
  labels: string[];
  values: number[];
  barColors: string[];
  height?: number;
}

// Phase 10 Plan 04 — Vertical bar chart wrapper for the Settings → Usage card
// daily breakdown. Mirrors HorizontalBar.tsx in lifecycle (canvas ref + theme
// reapply on theme change). Per-bar `backgroundColor` array enables the
// cumulative-threshold coloring (cyan / amber / red) required by D-19.
export default function VerticalBar({
  labels,
  values,
  barColors,
  height = 200,
}: VerticalBarProps) {
  const { theme } = useTheme();
  const chartRef = useRef<any>(null);

  useEffect(() => {
    applyChartDefaults();
    chartRef.current?.update();
  }, [theme]);

  const c = getThemeColors();

  return (
    <div className="chart-container" style={{ height }}>
      <Bar
        ref={chartRef}
        data={{
          labels,
          datasets: [
            {
              type: 'bar' as const,
              data: values,
              backgroundColor: barColors,
              borderRadius: 2,
              barThickness: 10,
              maxBarThickness: 14,
            },
          ],
        }}
        options={{
          // Default indexAxis is 'x' which gives vertical bars.
          maintainAspectRatio: false,
          responsive: true,
          plugins: {
            legend: { display: false },
            tooltip: { enabled: true },
          },
          scales: {
            y: {
              beginAtZero: true,
              ticks: {
                color: c.tickColor,
                font: { size: 10, family: c.fontFamily },
                precision: 0,
              },
              grid: { color: c.gridColor + "80" },
            },
            x: {
              grid: { display: false },
              ticks: {
                color: c.labelColor,
                font: { size: 10, family: c.fontFamily },
              },
            },
          },
          animation: { duration: 400 },
        }}
      />
    </div>
  );
}
