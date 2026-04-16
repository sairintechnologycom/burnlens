import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Tooltip,
  Filler,
} from "chart.js";

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  Tooltip,
  Filler
);

export function getThemeColors() {
  if (typeof window === "undefined") {
    return {
      gridColor: "rgba(30,36,51,0.5)",
      tickColor: "#2a3347",
      labelColor: "#4d5a74",
      fontFamily: "var(--font-mono)",
      cyan: "#22d3b8",
      amber: "#f5a623",
      red: "#f04060",
      green: "#22c98a",
      bg: "#08090d",
    };
  }
  const s = getComputedStyle(document.documentElement);
  const get = (v: string) => s.getPropertyValue(v).trim();
  return {
    gridColor: get("--border") || "#1e2433",
    tickColor: get("--dim") || "#2a3347",
    labelColor: get("--muted") || "#4d5a74",
    fontFamily: "var(--font-mono)",
    cyan: get("--cyan") || "#22d3b8",
    amber: get("--amber") || "#f5a623",
    red: get("--red") || "#f04060",
    green: get("--green") || "#22c98a",
    bg: get("--bg") || "#08090d",
  };
}

export function applyChartDefaults() {
  const c = getThemeColors();
  ChartJS.defaults.font.family = c.fontFamily;
  ChartJS.defaults.font.size = 11;
  ChartJS.defaults.color = c.labelColor;
  ChartJS.defaults.plugins.legend = { ...ChartJS.defaults.plugins.legend, display: false };
  ChartJS.defaults.plugins.tooltip = {
    ...ChartJS.defaults.plugins.tooltip,
    backgroundColor: c.bg,
    borderColor: c.gridColor,
    borderWidth: 1,
    titleFont: { family: c.fontFamily, size: 11 },
    bodyFont: { family: c.fontFamily, size: 11 },
    cornerRadius: 4,
    padding: 8,
  };
}
