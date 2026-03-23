"use client";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { useLeague } from "@/hooks/useLeague";
import { api, Team } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function LeaguePage() {
  const { activeLeague } = useLeague();
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!activeLeague) return;
    setLoading(true);
    api.teams.list(activeLeague.id)
      .then(setTeams)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [activeLeague]);

  return (
    <AppShell>
      <div className="p-6 space-y-6 max-w-3xl mx-auto">
        <div>
          <h1 className="text-2xl font-bold text-foreground">League Standings</h1>
          {activeLeague && <p className="text-muted-foreground text-sm">{activeLeague.name} · {activeLeague.num_teams} teams</p>}
        </div>

        {loading ? (
          <div className="space-y-3">
            {Array(10).fill(0).map((_, i) => (
              <div key={i} className="h-14 bg-card rounded-xl animate-pulse border border-border" />
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <div className="grid grid-cols-12 px-4 py-2.5 border-b border-border text-xs text-muted-foreground font-medium">
              <div className="col-span-1">#</div>
              <div className="col-span-7">Team</div>
              <div className="col-span-2 text-center">W</div>
              <div className="col-span-2 text-center">L</div>
            </div>
            <div className="divide-y divide-border">
              {teams.map((team, i) => (
                <div key={team.id} className={cn(
                  "grid grid-cols-12 px-4 py-3 items-center hover:bg-accent/50 transition-colors",
                  team.is_my_team && "bg-primary/5"
                )}>
                  <div className="col-span-1 text-sm font-medium text-muted-foreground">{team.standing || i + 1}</div>
                  <div className="col-span-7">
                    <div className="flex items-center gap-2">
                      <span className={cn("font-medium text-sm", team.is_my_team ? "text-primary" : "text-foreground")}>
                        {team.name}
                      </span>
                      {team.is_my_team && (
                        <span className="text-xs px-1.5 py-0.5 bg-primary/20 text-primary rounded">You</span>
                      )}
                    </div>
                    {team.manager_name && (
                      <p className="text-xs text-muted-foreground">{team.manager_name}</p>
                    )}
                  </div>
                  <div className="col-span-2 text-center">
                    <span className="text-sm font-semibold text-green-400">{team.wins}</span>
                  </div>
                  <div className="col-span-2 text-center">
                    <span className="text-sm font-semibold text-red-400">{team.losses}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
