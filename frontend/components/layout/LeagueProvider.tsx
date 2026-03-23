"use client";
import { LeagueContext, useLeagueProvider } from "@/hooks/useLeague";

export function LeagueProvider({ children }: { children: React.ReactNode }) {
  const value = useLeagueProvider();
  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}
