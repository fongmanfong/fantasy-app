"use client";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { useLeague } from "@/hooks/useLeague";
import { api, SyncLog } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Plus, Trash2, CheckCircle, XCircle, Clock } from "lucide-react";

export default function SettingsPage() {
  const { leagues, activeLeague, refreshLeagues } = useLeague();
  const [syncInterval, setSyncInterval] = useState(6);
  const [syncLogs, setSyncLogs] = useState<SyncLog[]>([]);
  const [newLeagueId, setNewLeagueId] = useState("");
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.leagues.getSyncInterval().then(d => setSyncInterval(d.hours)).catch(() => {});
    if (activeLeague) {
      api.leagues.syncStatus(activeLeague.id).then(setSyncLogs).catch(() => {});
    }
  }, [activeLeague]);

  async function handleAddLeague() {
    if (!newLeagueId.trim()) return;
    setAdding(true);
    setMessage("");
    try {
      await api.leagues.add(newLeagueId.trim());
      await refreshLeagues();
      setNewLeagueId("");
      setMessage("League added! Syncing in background...");
    } catch (e: any) {
      setMessage(`Error: ${e.message}`);
    } finally {
      setAdding(false);
    }
  }

  async function handleRemoveLeague(id: number) {
    if (!confirm("Remove this league?")) return;
    try {
      await api.leagues.remove(id);
      await refreshLeagues();
    } catch (e: any) {
      setMessage(`Error: ${e.message}`);
    }
  }

  async function handleSaveInterval() {
    setSaving(true);
    try {
      await api.leagues.setSyncInterval(syncInterval);
      setMessage("Sync interval updated.");
    } catch (e: any) {
      setMessage(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  const syncStatusIcon = (status: string) => {
    if (status === "success") return <CheckCircle className="w-4 h-4 text-green-500" />;
    if (status === "error") return <XCircle className="w-4 h-4 text-red-500" />;
    return <Clock className="w-4 h-4 text-yellow-500 animate-pulse" />;
  };

  return (
    <AppShell>
      <div className="p-6 space-y-8 max-w-2xl mx-auto">
        <h1 className="text-2xl font-bold text-foreground">Settings</h1>

        {message && (
          <div className="bg-primary/10 border border-primary/30 rounded-lg px-4 py-3 text-sm text-foreground">
            {message}
          </div>
        )}

        {/* Leagues */}
        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-foreground">Leagues</h2>
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            {leagues.length > 0 && (
              <div className="divide-y divide-border">
                {leagues.map(league => (
                  <div key={league.id} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="font-medium text-sm text-foreground">{league.name}</p>
                      <p className="text-xs text-muted-foreground">
                        ID: {league.yahoo_league_id} · {league.scoring_type} · {league.num_teams} teams
                      </p>
                    </div>
                    <button
                      onClick={() => handleRemoveLeague(league.id)}
                      className="p-2 text-muted-foreground hover:text-red-500 transition-colors rounded-md hover:bg-red-500/10"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className={cn("px-4 py-3", leagues.length > 0 && "border-t border-border")}>
              <div className="flex gap-2">
                <input
                  value={newLeagueId}
                  onChange={e => setNewLeagueId(e.target.value)}
                  placeholder="League ID (e.g. 28641)"
                  className="flex-1 px-3 py-2 bg-input border border-border rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <button
                  onClick={handleAddLeague}
                  disabled={adding || !newLeagueId.trim()}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  {adding ? "Adding..." : "Add League"}
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Sync Schedule */}
        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-foreground">Sync Schedule</h2>
          <div className="bg-card border border-border rounded-xl p-4 space-y-4">
            <div>
              <label className="text-sm font-medium text-foreground block mb-1.5">Data sync interval</label>
              <div className="flex gap-3 items-center">
                <div className="flex gap-1">
                  {[1, 3, 6, 12, 24].map(h => (
                    <button key={h} onClick={() => setSyncInterval(h)}
                      className={cn(
                        "px-3 py-2 rounded-md text-xs font-medium transition-colors",
                        syncInterval === h ? "bg-primary text-primary-foreground" :
                        "bg-muted text-muted-foreground hover:text-foreground"
                      )}>
                      {h}h
                    </button>
                  ))}
                </div>
                <button
                  onClick={handleSaveInterval}
                  disabled={saving}
                  className="px-3 py-2 bg-accent text-foreground rounded-md text-xs font-medium hover:bg-accent/80 disabled:opacity-50 transition-colors"
                >
                  {saving ? "Saving..." : "Save"}
                </button>
              </div>
              <p className="text-xs text-muted-foreground mt-2">Player news refreshes every 3 hours regardless.</p>
            </div>
          </div>
        </section>

        {/* Yahoo Credentials */}
        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-foreground">Yahoo API</h2>
          <div className="bg-card border border-border rounded-xl p-4">
            <p className="text-sm text-muted-foreground mb-3">
              Need to update your Yahoo credentials or re-authenticate?
            </p>
            <a
              href="/setup"
              className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-foreground rounded-md text-sm font-medium hover:bg-accent/80 transition-colors"
            >
              Re-run Setup
            </a>
          </div>
        </section>

        {/* Sync Log */}
        {activeLeague && syncLogs.length > 0 && (
          <section className="space-y-4">
            <h2 className="text-lg font-semibold text-foreground">Sync Log</h2>
            <div className="bg-card border border-border rounded-xl overflow-hidden">
              <div className="divide-y divide-border">
                {syncLogs.slice(0, 8).map((log, i) => (
                  <div key={i} className="flex items-start gap-3 px-4 py-3">
                    <div className="mt-0.5">{syncStatusIcon(log.status)}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground capitalize">{log.sync_type}</span>
                        <span className={cn(
                          "text-xs px-1.5 py-0.5 rounded",
                          log.status === "success" ? "bg-green-500/20 text-green-500" :
                          log.status === "error" ? "bg-red-500/20 text-red-500" :
                          "bg-yellow-500/20 text-yellow-500"
                        )}>
                          {log.status}
                        </span>
                      </div>
                      {log.message && <p className="text-xs text-red-400 mt-0.5 truncate">{log.message}</p>}
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {log.started_at ? new Date(log.started_at).toLocaleString() : ""}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}
