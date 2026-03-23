import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatStat(value: number | undefined, decimals = 1): string {
  if (value === undefined || value === null) return "—";
  return value.toFixed(decimals);
}

export function getInjuryColor(status: string): string {
  switch (status?.toUpperCase()) {
    case "O": return "text-red-500";
    case "GTD": return "text-yellow-500";
    case "DTD": return "text-orange-500";
    case "IR": return "text-red-700";
    default: return "text-green-500";
  }
}

export function getInjuryLabel(status: string): string {
  switch (status?.toUpperCase()) {
    case "O": return "Out";
    case "GTD": return "GTD";
    case "DTD": return "DTD";
    case "IR": return "IR";
    case "HEALTHY": return "Active";
    default: return status || "Active";
  }
}
