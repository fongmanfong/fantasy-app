"use client";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { useLeague } from "@/hooks/useLeague";
import { api, FreeAgent, LeagueSettings } from "@/lib/api";
import { cn, formatStat, getInjuryColor, getInjuryLabel } from "@/lib/utils";
import { Search } from "lucide-react";

export default function FreeAgentsPage() {
  const { activeLeague } = useLeague();
  const [freeAgents, setFreeAgents] = useState<FreeAgent[]>([]);
  const [settings, setSettings] = useState<LeagueSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [posFilter, setPosFilter] = useState("ALL");

  useEffect(() => {
    if (!activeLeague) return;
    setLoading(true);
    Promise.all([
      api.teams.freeAgents(activeLeague.id, 50),
      api.leagues.settings(activeLeague.id),
    ]).then(([fa, s]) => {
      setFreeAgents(fa.free_agents);
      setSettings(s);
    }).catch(console.error).finally(() => setLoading(false));
  }, [activeLeague]);

  const positions = ["ALL", "PG", "SG", "SF", "PF", "C"];
  const activeStats = settings?.stat_categories
    ?.filter(c => !c.is_only_display)
    .map(c => c.name)
    .slice(0, 6) || ["PTS", "REB", "AST", "ST", "BLK", "TO"];

  const filtered = freeAgents.filter(p => {
    const matchSearch = !search || p.name.toLowerCase().includes(search.toLowerCase()) ||
      p.nba_team?.toLowerCase().includes(search.toLowerCase());
    const matchPos = posFilter === "ALL" || p.positions?.includes(posFilter);
    return matchSearch && matchPos;
  });

  return (
    <AppShell>
      <div className="p-6 space-y-6 max-w-6xl mx-auto">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Free Agents</h1>
          {activeLeague && <p className="text-muted-foreground text-sm">Ranked by value · {activeLeague.name}</p>}
        </div>

        {/* Filters */}
        <div className="flex gap-3 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search players..."
              className="w-full pl-9 pr-3 py-2 bg-card border border-border rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div className="flex gap-1">
            {positions.map(p => (
              <button key={p} onClick={() => setPosFilter(p)}
                className={cn(
                  "px-3 py-2 rounded-md text-xs font-medium transition-colors",
                  posFilter === p ? "bg-primary text-primary-foreground" : "bg-card border border-border text-muted-foreground hover:text-foreground"
                )}>
                {p}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="space-y-2">
            {Array(10).fill(0).map((_, i) => (
              <div key={i} className="h-14 bg-card rounded-xl animate-pulse border border-border" />
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            {/* Header */}
            <div className="flex items-center px-4 py-2.5 border-b border-border text-xs text-muted-foreground font-medium gap-4">
              <div className="w-6 text-center">#</div>
              <div className="flex-1">Player</div>
              <div className="w-8 text-center">GP</div>
              {activeStats.map(s => (
                <div key={s} className="w-14 text-center">{s}</div>
              ))}
              <div className="w-16 text-center">Value</div>
            </div>
            <div className="divide-y divide-border">
              {filtered.map((player, i) => (
                <div key={player.player_id} className="flex items-center px-4 py-3 gap-4 hover:bg-accent/50 transition-colors">
                  <div className="w-6 text-center text-xs text-muted-foreground">{i + 1}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm text-foreground">{player.name}</span>
                      {player.injury_status && player.injury_status !== "Healthy" && (
                        <span className={cn("text-xs font-medium", getInjuryColor(player.injury_status))}>
                          {getInjuryLabel(player.injury_status)}
                        </span>
                      )}
                      {player.games_this_week > 0 && (
                        <span className="text-xs px-1.5 py-0.5 bg-blue-500/20 text-blue-400 rounded">
                          {player.games_this_week}G
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">{player.nba_team} · {player.positions?.join("/")}</p>
                  </div>
                  <div className="w-8 text-center text-xs text-muted-foreground">{player.games_played}</div>
                  {activeStats.map(stat => (
                    <div key={stat} className="w-14 text-center text-sm text-foreground">
                      {formatStat(player.stats[stat], stat.includes("%") ? 3 : 1)}
                    </div>
                  ))}
                  <div className="w-16 text-center">
                    <span className={cn(
                      "text-sm font-bold",
                      player.value_score > 5 ? "text-green-400" :
                      player.value_score > 0 ? "text-blue-400" : "text-muted-foreground"
                    )}>
                      {player.value_score > 0 ? "+" : ""}{player.value_score.toFixed(1)}
                    </span>
                  </div>
                </div>
              ))}
              {filtered.length === 0 && (
                <div className="px-4 py-8 text-center text-muted-foreground text-sm">
                  No players found.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
