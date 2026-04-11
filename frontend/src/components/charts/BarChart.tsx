"use client";

import { useEffect, useRef } from "react";
import { Bar } from "react-chartjs-2";
import { applyChartDefaults, getThemeColors } from "@/lib/chartDefaults";
import { useTheme } from "@/components/ThemeProvider";

interface BarChartProps {
  labels: string[];
  data: number[];
  spikeIndices?: number[];
  height?: number;
}

export default function BarChart({ labels, data, spikeIndices = [], height = 200 }: BarChartProps) {
  const { theme } = useTheme();
  const chartRef = useRef<any>(null);

  useEffect(() => {
    applyChartDefaults();
    chartRef.current?.update();
  }, [theme]);

  const c = getThemeColors();
  const lastIdx = data.length - 1;

  const bgColors = data.map((_, i) => {
    if (spikeIndices.includes(i)) return c.amber + "33";
    if (i === lastIdx) return c.cyan + "4D";
    return c.cyan + "33";
  });

  const borderColors = data.map((_, i) => {
    if (spikeIndices.includes(i)) return c.amber;
    if (i === lastIdx) return c.cyan;
    return c.cyan + "99";
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
            borderColor: borderColors,
            borderWidth: { top: 2, left: 0, right: 0, bottom: 0 },
            borderRadius: 3,
            borderSkipped: false,
          }],
        }}
        options={{
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: c.tickColor, font: { size: 9, family: c.fontFamily } },
            },
            y: {
              grid: { color: c.gridColor + "80" },
              ticks: {
                color: c.tickColor,
                font: { size: 10, family: c.fontFamily },
                callback: (v) => `$${v}`,
              },
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
