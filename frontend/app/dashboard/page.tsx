"use client";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { useLeague } from "@/hooks/useLeague";
import { api, MyTeamSummary, MatchupAnalysis } from "@/lib/api";
import { cn, formatStat, getInjuryColor, getInjuryLabel } from "@/lib/utils";
import { AlertCircle, TrendingUp, TrendingDown, Minus } from "lucide-react";

export default function DashboardPage() {
  const { activeLeague } = useLeague();
  const [myTeam, setMyTeam] = useState<MyTeamSummary | null>(null);
  const [matchup, setMatchup] = useState<MatchupAnalysis | null>(null);
  const [period, setPeriod] = useState("last_14");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!activeLeague) return;
    setLoading(true);
    Promise.all([
      api.teams.myTeam(activeLeague.id, period),
      api.teams.matchup(activeLeague.id),
    ]).then(([team, mu]) => {
      setMyTeam(team);
      setMatchup(mu);
    }).catch(console.error).finally(() => setLoading(false));
  }, [activeLeague, period]);

  if (!activeLeague) {
    return (
      <AppShell>
        <div className="flex items-center justify-center h-full">
          <p className="text-muted-foreground">No league selected. Add one in Settings.</p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="p-6 space-y-6 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">{myTeam?.team_name || "My Team"}</h1>
            <p className="text-muted-foreground text-sm">
              {activeLeague.name} · Week {activeLeague.current_week}
              {myTeam && ` · ${myTeam.wins}W-${myTeam.losses}L${myTeam.ties ? `-${myTeam.ties}T` : ""} · #${myTeam.standing}`}
            </p>
          </div>
          <div className="flex gap-2">
            {["last_7", "last_14", "last_30", "season"].map((p) => (
              <button key={p} onClick={() => setPeriod(p)}
                className={cn(
                  "px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
                  period === p ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"
                )}>
                {p === "season" ? "Season" : p.replace("last_", "L")}
              </button>
            ))}
          </div>
        </div>

        {/* Matchup Banner */}
        {matchup && !("error" in matchup) && (
          <div className={cn(
            "rounded-xl p-4 border",
            matchup.summary.winning ? "bg-green-500/10 border-green-500/30" : "bg-red-500/10 border-red-500/30"
          )}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Week {matchup.week} Matchup</p>
                <p className="font-semibold text-foreground mt-0.5">
                  vs. {matchup.opponent}
                </p>
              </div>
              <div className="text-right">
                {matchup.summary.winning_cats !== undefined ? (
                  <p className={cn("text-2xl font-bold", matchup.summary.winning ? "text-green-500" : "text-red-500")}>
                    {matchup.summary.winning_cats} – {matchup.summary.losing_cats}
                    {matchup.summary.tied_cats ? ` (${matchup.summary.tied_cats}T)` : ""}
                  </p>
                ) : (
                  <p className={cn("text-2xl font-bold", matchup.summary.winning ? "text-green-500" : "text-red-500")}>
                    {matchup.summary.my_score?.toFixed(1)} – {matchup.summary.opp_score?.toFixed(1)}
                  </p>
                )}
                <p className={cn("text-sm font-medium", matchup.summary.winning ? "text-green-500" : "text-red-500")}>
                  {matchup.summary.winning ? "Winning" : "Losing"}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Roster */}
        {loading ? (
          <div className="space-y-3">
            {Array(8).fill(0).map((_, i) => (
              <div key={i} className="h-16 bg-card rounded-xl animate-pulse border border-border" />
            ))}
          </div>
        ) : myTeam ? (
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <h2 className="font-semibold text-foreground">Roster</h2>
            </div>
            <div className="divide-y divide-border">
              {myTeam.players.map((player) => {
                const isActive = !["BN", "IL", "IL+"].includes(player.roster_position);
                const topStats = Object.entries(player.stats).slice(0, 5);
                return (
                  <div key={player.player_id} className={cn(
                    "flex items-center gap-4 px-4 py-3 hover:bg-accent/50 transition-colors",
                    !isActive && "opacity-60"
                  )}>
                    <div className="w-20 flex-shrink-0">
                      <span className={cn(
                        "text-xs font-medium px-2 py-0.5 rounded",
                        isActive ? "bg-primary/20 text-primary" : "bg-muted text-muted-foreground"
                      )}>
                        {player.roster_position}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-foreground text-sm">{player.name}</span>
                        {player.injury_status && player.injury_status !== "Healthy" && (
                          <span className={cn("text-xs font-medium", getInjuryColor(player.injury_status))}>
                            {getInjuryLabel(player.injury_status)}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {player.nba_team} · {player.positions.join("/")}
                      </p>
                    </div>
                    <div className="flex items-center gap-4 text-right">
                      {topStats.map(([stat, val]) => (
                        <div key={stat} className="hidden sm:block">
                          <p className="text-xs text-muted-foreground">{stat}</p>
                          <p className="text-sm font-medium text-foreground">{formatStat(val)}</p>
                        </div>
                      ))}
                      <div>
                        <p className="text-xs text-muted-foreground">Value</p>
                        <p className={cn(
                          "text-sm font-bold",
                          player.value_score > 0 ? "text-green-400" :
                          player.value_score < -2 ? "text-red-400" : "text-muted-foreground"
                        )}>
                          {player.value_score > 0 ? "+" : ""}{player.value_score.toFixed(1)}
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
