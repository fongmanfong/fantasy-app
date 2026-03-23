"use client";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { useLeague } from "@/hooks/useLeague";
import { api, MatchupAnalysis } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function MatchupPage() {
  const { activeLeague } = useLeague();
  const [matchup, setMatchup] = useState<MatchupAnalysis | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!activeLeague) return;
    setLoading(true);
    api.teams.matchup(activeLeague.id)
      .then(setMatchup)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [activeLeague]);

  return (
    <AppShell>
      <div className="p-6 space-y-6 max-w-4xl mx-auto">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Matchup</h1>
          {activeLeague && <p className="text-muted-foreground text-sm">{activeLeague.name} · Week {activeLeague.current_week}</p>}
        </div>

        {loading ? (
          <div className="space-y-4">
            <div className="h-32 bg-card rounded-xl animate-pulse border border-border" />
            <div className="h-64 bg-card rounded-xl animate-pulse border border-border" />
          </div>
        ) : matchup && !("error" in matchup) ? (
          <div className="space-y-6">
            {/* Score Header */}
            <div className="bg-card border border-border rounded-xl p-6">
              <div className="flex items-center justify-between">
                <div className="text-center flex-1">
                  <p className="text-sm text-muted-foreground mb-1">My Team</p>
                  <p className="text-xl font-bold text-foreground">{matchup.my_team}</p>
                  {matchup.summary.winning_cats !== undefined ? (
                    <p className={cn("text-4xl font-bold mt-2", matchup.summary.winning ? "text-green-500" : "text-muted-foreground")}>
                      {matchup.summary.winning_cats}
                    </p>
                  ) : (
                    <p className={cn("text-4xl font-bold mt-2", matchup.summary.winning ? "text-green-500" : "text-muted-foreground")}>
                      {matchup.summary.my_score?.toFixed(1)}
                    </p>
                  )}
                </div>
                <div className="text-center px-6">
                  <p className="text-muted-foreground text-2xl font-light">vs</p>
                  <p className={cn(
                    "text-sm font-semibold mt-1 px-3 py-0.5 rounded-full",
                    matchup.summary.winning ? "bg-green-500/20 text-green-500" : "bg-red-500/20 text-red-500"
                  )}>
                    {matchup.summary.winning ? "Winning" : "Losing"}
                  </p>
                </div>
                <div className="text-center flex-1">
                  <p className="text-sm text-muted-foreground mb-1">Opponent</p>
                  <p className="text-xl font-bold text-foreground">{matchup.opponent}</p>
                  {matchup.summary.losing_cats !== undefined ? (
                    <p className={cn("text-4xl font-bold mt-2", !matchup.summary.winning ? "text-red-500" : "text-muted-foreground")}>
                      {matchup.summary.losing_cats}
                    </p>
                  ) : (
                    <p className={cn("text-4xl font-bold mt-2", !matchup.summary.winning ? "text-red-500" : "text-muted-foreground")}>
                      {matchup.summary.opp_score?.toFixed(1)}
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Category Breakdown */}
            {Object.keys(matchup.categories).length > 0 && (
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-3 border-b border-border">
                  <h2 className="font-semibold text-foreground">Categories</h2>
                </div>
                <div className="divide-y divide-border">
                  {Object.entries(matchup.categories).map(([cat, data]) => (
                    <div key={cat} className="flex items-center px-4 py-3 gap-4">
                      <div className="w-12 text-right">
                        <span className={cn(
                          "text-sm font-semibold",
                          data.status === "winning" ? "text-green-400" :
                          data.status === "losing" ? "text-red-400" : "text-yellow-400"
                        )}>
                          {data.my_value.toFixed(cat.includes("%") ? 3 : 1)}
                        </span>
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <div className={cn(
                            "h-2 rounded-full transition-all",
                            data.status === "winning" ? "bg-green-500" :
                            data.status === "losing" ? "bg-red-500" : "bg-yellow-500"
                          )} style={{
                            width: `${Math.min(100, data.status === "winning"
                              ? 70 + Math.abs(data.diff) * 5
                              : Math.max(10, 50 - Math.abs(data.diff) * 5)
                            )}%`
                          }} />
                        </div>
                      </div>
                      <div className="w-12 text-center">
                        <span className={cn(
                          "text-xs font-bold px-2 py-0.5 rounded",
                          data.status === "winning" ? "bg-green-500/20 text-green-500" :
                          data.status === "losing" ? "bg-red-500/20 text-red-500" :
                          "bg-yellow-500/20 text-yellow-500"
                        )}>
                          {cat}
                        </span>
                      </div>
                      <div className="w-12 text-left">
                        <span className="text-sm text-muted-foreground">
                          {data.opp_value.toFixed(cat.includes("%") ? 3 : 1)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-8 text-center">
            <p className="text-muted-foreground">No matchup data available. Try syncing your league.</p>
          </div>
        )}
      </div>
    </AppShell>
  );
}
