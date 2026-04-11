"use client";

import { useEffect, useRef } from "react";
import { Bar } from "react-chartjs-2";
import { applyChartDefaults, getThemeColors } from "@/lib/chartDefaults";
import { useTheme } from "@/components/ThemeProvider";

interface HorizontalBarProps {
  labels: string[];
  data: number[];
  height?: number;
  flaggedIndices?: number[];
}

export default function HorizontalBar({ labels, data, height = 300, flaggedIndices = [] }: HorizontalBarProps) {
  const { theme } = useTheme();
  const chartRef = useRef<any>(null);

  useEffect(() => {
    applyChartDefaults();
    chartRef.current?.update();
  }, [theme]);

  const c = getThemeColors();

  const bgColors = data.map((_, i) => {
    if (flaggedIndices.includes(i)) return c.amber + "33";
    if (i === 0) return c.cyan + "66";
    return c.cyan + "33";
  });

  return (
    <div className="chart-container" style={{ height }}>
      <Bar
        ref={chartRef}
        data={{
          labels,
          datasets: [{
            data,
            backgroundColor: bgColors,
            borderRadius: 3,
          }],
        }}
        options={{
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              grid: { color: c.gridColor + "80" },
              ticks: {
                color: c.tickColor,
                font: { size: 10, family: c.fontFamily },
                callback: (v) => `$${v}`,
              },
            },
            y: {
              grid: { display: false },
              ticks: { color: c.labelColor, font: { size: 11, family: c.fontFamily } },
            },
          },
          plugins: {
            tooltip: {
              callbacks: {
                label: (ctx) => `$${Number(ctx.raw).toFixed(2)}`,
              },
            },
          },
        }}
      />
    </div>
  );
}
