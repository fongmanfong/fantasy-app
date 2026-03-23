"use client";
import { useState, useEffect, createContext, useContext } from "react";
import { api, League } from "@/lib/api";

interface LeagueContextType {
  leagues: League[];
  activeLeague: League | null;
  setActiveLeague: (league: League) => void;
  refreshLeagues: () => Promise<void>;
  isLoading: boolean;
}

export const LeagueContext = createContext<LeagueContextType>({
  leagues: [],
  activeLeague: null,
  setActiveLeague: () => {},
  refreshLeagues: async () => {},
  isLoading: true,
});

export function useLeague() {
  return useContext(LeagueContext);
}

export function useLeagueProvider() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [activeLeague, setActiveLeagueState] = useState<League | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshLeagues = async () => {
    try {
      const data = await api.leagues.list();
      setLeagues(data);
      if (data.length > 0 && !activeLeague) {
        const saved = localStorage.getItem("activeLeagueId");
        const found = saved ? data.find((l) => l.id === parseInt(saved)) : null;
        setActiveLeagueState(found || data[0]);
      }
    } catch (e) {
      console.error("Failed to load leagues:", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    refreshLeagues();
  }, []);

  const setActiveLeague = (league: League) => {
    setActiveLeagueState(league);
    localStorage.setItem("activeLeagueId", String(league.id));
  };

  return { leagues, activeLeague, setActiveLeague, refreshLeagues, isLoading };
}
