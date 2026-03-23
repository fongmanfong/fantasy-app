const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

// Auth
export const api = {
  auth: {
    saveCredentials: (clientId: string, clientSecret: string) =>
      request("/auth/yahoo/credentials", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
      }),
    getLoginUrl: () => request<{ auth_url: string }>("/auth/yahoo/login"),
    getStatus: () => request<{ has_credentials: boolean; is_authenticated: boolean }>("/auth/yahoo/status"),
    submitOobCode: (code: string) =>
      request("/auth/yahoo/oob-callback", { method: "POST", body: JSON.stringify({ code }) }),
  },

  leagues: {
    list: () => request<League[]>("/leagues/"),
    add: (yahooLeagueId: string) =>
      request("/leagues/", { method: "POST", body: JSON.stringify({ yahoo_league_id: yahooLeagueId }) }),
    remove: (id: number) => request(`/leagues/${id}`, { method: "DELETE" }),
    sync: (id: number) => request(`/leagues/${id}/sync`, { method: "POST" }),
    syncNews: () => request("/leagues/news/sync", { method: "POST" }),
    syncStatus: (id: number) => request<SyncLog[]>(`/leagues/${id}/sync/status`),
    settings: (id: number) => request<LeagueSettings>(`/leagues/${id}/settings`),
    getSyncInterval: () => request<{ hours: number }>("/leagues/app/sync-interval"),
    setSyncInterval: (hours: number) =>
      request("/leagues/app/sync-interval", { method: "POST", body: JSON.stringify({ hours }) }),
  },

  teams: {
    list: (leagueId: number) => request<Team[]>(`/teams/league/${leagueId}`),
    myTeam: (leagueId: number, period = "last_14") =>
      request<MyTeamSummary>(`/teams/my-team/${leagueId}?stat_period=${period}`),
    roster: (teamId: number, leagueId: number, period = "last_14") =>
      request<RosterResponse>(`/teams/${teamId}/roster?league_id=${leagueId}&stat_period=${period}`),
    freeAgents: (leagueId: number, topN = 25) =>
      request<{ free_agents: FreeAgent[]; count: number }>(`/teams/free-agents/${leagueId}?top_n=${topN}`),
    matchup: (leagueId: number) => request<MatchupAnalysis>(`/teams/matchup/${leagueId}`),
  },

  agent: {
    chat: (messages: ChatMessage[], leagueId: number) =>
      request<{ response: string }>("/agent/chat", {
        method: "POST",
        body: JSON.stringify({ messages, league_id: leagueId }),
      }),
    recommendations: (leagueId: number) =>
      request<{ recommendations: string }>("/agent/recommendations", {
        method: "POST",
        body: JSON.stringify({ league_id: leagueId }),
      }),
  },
};

// Types
export interface League {
  id: number;
  yahoo_league_id: string;
  name: string;
  season: number;
  num_teams: number;
  current_week: number;
  scoring_type: string;
}

export interface LeagueSettings {
  stat_categories: StatCategory[];
  stat_weights: Record<string, number>;
  roster_positions: Record<string, number>;
  playoff_start_week: number;
  waiver_type: string;
}

export interface StatCategory {
  stat_id: string;
  name: string;
  display_name: string;
  is_only_display: boolean;
}

export interface SyncLog {
  sync_type: string;
  status: string;
  message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface Team {
  id: number;
  yahoo_team_id: string;
  name: string;
  manager_name: string;
  is_my_team: boolean;
  wins: number;
  losses: number;
  ties: number;
  standing: number;
}

export interface PlayerOnRoster {
  player_id: number;
  yahoo_player_id: string;
  name: string;
  nba_team: string;
  positions: string[];
  roster_position: string;
  injury_status: string;
  value_score: number;
  weekly_score: number;
  stats: Record<string, number>;
}

export interface MyTeamSummary {
  team_name: string;
  wins: number;
  losses: number;
  ties: number;
  standing: number;
  players: PlayerOnRoster[];
}

export interface RosterResponse {
  team: string;
  players: PlayerOnRoster[];
}

export interface FreeAgent {
  player_id: number;
  name: string;
  nba_team: string;
  positions: string[];
  injury_status: string;
  value_score: number;
  weekly_score: number;
  games_this_week: number;
  games_played: number;
  stats: Record<string, number>;
}

export interface CategoryResult {
  my_value: number;
  opp_value: number;
  status: "winning" | "losing" | "tied";
  diff: number;
}

export interface MatchupAnalysis {
  week: number;
  my_team: string;
  opponent: string;
  scoring_type: string;
  categories: Record<string, CategoryResult>;
  summary: {
    winning_cats?: number;
    losing_cats?: number;
    tied_cats?: number;
    winning: boolean;
    my_score?: number;
    opp_score?: number;
    margin?: number;
  };
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
