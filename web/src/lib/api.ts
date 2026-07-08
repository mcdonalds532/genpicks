// Server-side client for the GenPicks FastAPI backend. All pages are
// dynamic server components: fetches run on the Next server per request
// (uncached by default in Next 16), so the browser never talks to the API.

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

export type WinProbability = {
  probability: number;
  implied_odds: number | null;
};

export type UpcomingMatch = {
  match_id: number;
  season: number;
  round: string;
  date: string;
  kickoff_utc: string | null;
  home_team: string | null;
  away_team: string | null;
  venue: string | null;
  win_probabilities:
    | ({ model_version: string } & { home?: WinProbability; away?: WinProbability })
    | null;
};

export type PlayerMarketEntry = {
  player: string | null;
  team: string | null;
  probability: number;
  implied_odds: number | null;
};

export type MatchMarkets = {
  match_id: number;
  home_team: string | null;
  away_team: string | null;
  date: string | null;
  h2h: { home?: WinProbability; away?: WinProbability };
  anytime_try: PlayerMarketEntry[];
  first_try: PlayerMarketEntry[];
  lineup_source: "official" | "projected" | null;
};

export type TrackRecord = Record<
  string,
  { settled: number; accuracy: number; log_loss: number }
>;

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_URL}${path}`);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null; // API offline: pages render a notice instead of crashing
  }
}

export const getUpcoming = (limit = 20) =>
  get<UpcomingMatch[]>(`/matches/upcoming?limit=${limit}`);

export const getMatchMarkets = (matchId: string) =>
  get<MatchMarkets>(`/matches/${matchId}/markets`);

export const getTrackRecord = () => get<TrackRecord>(`/track-record`);

export const formatPercent = (p: number) => `${(p * 100).toFixed(1)}%`;

export const formatOdds = (odds: number | null) =>
  odds === null ? "—" : odds.toFixed(2);
