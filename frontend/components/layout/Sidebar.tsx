"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useLeague } from "@/hooks/useLeague";
import {
  LayoutDashboard, Swords, Users, UserSearch,
  Lightbulb, MessageSquare, Settings, ChevronDown,
  RefreshCw, Trophy,
} from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";

const navItems = [
  { href: "/dashboard", label: "My Team", icon: LayoutDashboard },
  { href: "/matchup", label: "Matchup", icon: Swords },
  { href: "/league", label: "League", icon: Trophy },
  { href: "/free-agents", label: "Free Agents", icon: UserSearch },
  { href: "/recommendations", label: "Recommendations", icon: Lightbulb },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { leagues, activeLeague, setActiveLeague } = useLeague();
  const [leagueOpen, setLeagueOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);

  async function handleSync() {
    if (!activeLeague || syncing) return;
    setSyncing(true);
    try {
      await api.leagues.sync(activeLeague.id);
    } finally {
      setTimeout(() => setSyncing(false), 2000);
    }
  }

  return (
    <aside className="w-60 min-h-screen bg-card border-r border-border flex flex-col">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-border">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-primary-foreground font-bold text-sm">
            IQ
          </div>
          <span className="font-semibold text-lg text-foreground">Fantasy IQ</span>
        </div>
      </div>

      {/* League Selector */}
      <div className="px-3 py-3 border-b border-border">
        <button
          onClick={() => setLeagueOpen(!leagueOpen)}
          className="w-full flex items-center justify-between px-3 py-2 rounded-md hover:bg-accent text-sm transition-colors"
        >
          <div className="flex flex-col items-start min-w-0">
            <span className="text-xs text-muted-foreground">League</span>
            <span className="font-medium truncate text-foreground">
              {activeLeague?.name || "Select league"}
            </span>
          </div>
          <ChevronDown className={cn("w-4 h-4 text-muted-foreground transition-transform", leagueOpen && "rotate-180")} />
        </button>

        {leagueOpen && leagues.length > 0 && (
          <div className="mt-1 rounded-md border border-border bg-popover overflow-hidden">
            {leagues.map((league) => (
              <button
                key={league.id}
                onClick={() => { setActiveLeague(league); setLeagueOpen(false); }}
                className={cn(
                  "w-full text-left px-3 py-2 text-sm hover:bg-accent transition-colors",
                  activeLeague?.id === league.id && "bg-accent text-primary"
                )}
              >
                <div className="font-medium">{league.name}</div>
                <div className="text-xs text-muted-foreground">{league.scoring_type} · {league.num_teams} teams</div>
              </button>
            ))}
            <Link
              href="/settings"
              onClick={() => setLeagueOpen(false)}
              className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:bg-accent transition-colors border-t border-border"
            >
              + Add league
            </Link>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors",
              pathname === href
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:text-foreground hover:bg-accent"
            )}
          >
            <Icon className="w-4 h-4" />
            {label}
          </Link>
        ))}
      </nav>

      {/* Sync Button */}
      <div className="px-3 py-4 border-t border-border">
        <button
          onClick={handleSync}
          disabled={!activeLeague || syncing}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("w-4 h-4", syncing && "animate-spin")} />
          {syncing ? "Syncing..." : "Sync Now"}
        </button>
      </div>
    </aside>
  );
}
