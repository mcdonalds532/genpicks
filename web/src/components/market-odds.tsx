import { type MarketOdds } from "@/lib/api";

// One quiet line of live sportsbook context under the model's numbers:
// best available decimal price per side across the latest odds snapshot.
export function MarketOddsLine({ odds }: { odds: MarketOdds }) {
  if (!odds || (!odds.home && !odds.away)) return null;
  const side = (s: { price: number; bookmaker: string | null } | null) =>
    s === null ? "—" : `$${s.price.toFixed(2)}${s.bookmaker ? ` (${s.bookmaker})` : ""}`;
  return (
    <p className="mt-1.5 text-xs text-muted">
      Best market odds — home{" "}
      <span className="tabular-nums text-ink-2">{side(odds.home)}</span> · away{" "}
      <span className="tabular-nums text-ink-2">{side(odds.away)}</span>
      {odds.bookmakers > 1 ? ` · ${odds.bookmakers} bookmakers` : ""}
    </p>
  );
}
