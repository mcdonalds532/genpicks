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
  market_odds: MarketOdds;
};

export type MarketOdds = {
  home: { price: number; bookmaker: string | null } | null;
  away: { price: number; bookmaker: string | null } | null;
  bookmakers: number;
  captured_at: string;
} | null;

export type PlayerMarketEntry = {
  player: string | null;
  team: string | null;
  probability: number;
  implied_odds: number | null;
};

// Grouped SHAP contributions from the h2h model, in log-odds space:
// positive logit pulls toward the home side, negative toward the away
// side; share is the factor's fraction of the total absolute pull.
export type H2hExplanation = {
  factors: { factor: string; label: string; logit: number; share: number }[];
  bias: number;
};

export type MatchMarkets = {
  match_id: number;
  home_team: string | null;
  away_team: string | null;
  date: string | null;
  h2h: { home?: WinProbability; away?: WinProbability };
  // null on matches predicted before explanations shipped
  h2h_explanation: H2hExplanation | null;
  // null when locked: the API withholds try markets unless the request
  // proves an entitled viewer (internal key + subscribed user id)
  anytime_try: PlayerMarketEntry[] | null;
  first_try: PlayerMarketEntry[] | null;
  try_markets_locked: boolean;
  try_market_counts: { anytime_try: number; first_try: number };
  market_odds: MarketOdds;
  lineup_source: "official" | "projected" | null;
};

export type TrackRecord = Record<
  string,
  { settled: number; accuracy: number; log_loss: number }
>;

async function get<T>(path: string, headers?: Record<string, string>): Promise<T | null> {
  try {
    const res = await fetch(`${API_URL}${path}`, { headers });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null; // API offline: pages render a notice instead of crashing
  }
}

export const getUpcoming = (limit = 20) =>
  get<UpcomingMatch[]>(`/matches/upcoming?limit=${limit}`);

// The signed-in viewer's user id travels with the internal key; the API
// decides entitlement against the subscription in the database.
export const getMatchMarkets = (matchId: string, userId?: number | null) =>
  get<MatchMarkets>(
    `/matches/${matchId}/markets`,
    userId == null
      ? undefined
      : {
          "X-Internal-Key": process.env.GENPICKS_INTERNAL_API_KEY ?? "",
          "X-User-Id": String(userId),
        },
  );

export const getTrackRecord = () => get<TrackRecord>(`/track-record`);

// Asks the API for a Stripe hosted-checkout URL (test mode — demo checkout).
// Returns null when billing is unconfigured or the API is unreachable.
export async function createCheckoutUrl(
  userId: number,
  origin: string,
  returnPath: string,
): Promise<string | null> {
  try {
    const res = await fetch(`${API_URL}/internal/billing/checkout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Internal-Key": process.env.GENPICKS_INTERNAL_API_KEY ?? "",
      },
      body: JSON.stringify({
        user_id: userId,
        success_url: `${origin}${returnPath}?subscribed=1`,
        cancel_url: `${origin}${returnPath}`,
      }),
    });
    if (!res.ok) return null;
    return ((await res.json()) as { url: string }).url;
  } catch {
    return null;
  }
}

export const formatPercent = (p: number) => `${(p * 100).toFixed(1)}%`;

export const formatOdds = (odds: number | null) =>
  odds === null ? "—" : odds.toFixed(2);

// Match dates arrive as bare "YYYY-MM-DD" (no zone). Anchoring at local
// midnight keeps the displayed day from slipping backwards, which parsing
// the bare string as UTC would do for anyone west of Greenwich.
export const formatMatchDate = (iso: string | null) =>
  iso === null
    ? null
    : new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", {
        weekday: "short",
        day: "numeric",
        month: "short",
      });
