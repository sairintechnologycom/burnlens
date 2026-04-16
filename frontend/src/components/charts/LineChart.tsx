"use client";

import { useEffect, useRef } from "react";
import { Line } from "react-chartjs-2";
import { applyChartDefaults, getThemeColors } from "@/lib/chartDefaults";
import { useTheme } from "@/components/ThemeProvider";

interface LineChartProps {
  labels: string[];
  data: number[];
  height?: number;
}

export default function LineChart({ labels, data, height = 200 }: LineChartProps) {
  const { theme } = useTheme();
  const chartRef = useRef<any>(null);

  useEffect(() => {
    applyChartDefaults();
    chartRef.current?.update();
  }, [theme]);

  const c = getThemeColors();

  return (
    <div className="chart-container" style={{ height }}>
      <Line
        ref={chartRef}
        data={{
          labels,
          datasets: [{
            data,
            borderColor: c.cyan,
            borderWidth: 1.5,
            pointRadius: 3,
            pointBackgroundColor: c.cyan,
            fill: false,
            tension: 0.3,
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
