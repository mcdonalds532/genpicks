import { formatOdds, formatPercent, type WinProbability } from "@/lib/api";

// Two-segment win-probability bar. Identity is carried by the validated
// home/away hues AND by always-visible text labels (the relief rule: the
// away hue sits under 3:1 on the light surface, so color never works
// alone). The 2px gap between segments is the palette's surface spacer.
export function ProbBar({
  homeTeam,
  awayTeam,
  home,
  away,
}: {
  homeTeam: string | null;
  awayTeam: string | null;
  home?: WinProbability;
  away?: WinProbability;
}) {
  if (!home || !away) {
    return <p className="text-sm text-muted">No prediction yet</p>;
  }
  const homePct = Math.round(home.probability * 1000) / 10;
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-4 text-sm">
        <span className="min-w-0 truncate">
          <span
            aria-hidden
            className="mr-1.5 inline-block h-2 w-2 rounded-full bg-series-home align-baseline"
          />
          <span className="font-medium">{homeTeam}</span>{" "}
          <span className="tabular-nums text-ink-2">
            {formatPercent(home.probability)}
          </span>{" "}
          <span className="tabular-nums text-muted">
            ${formatOdds(home.implied_odds)}
          </span>
        </span>
        <span className="min-w-0 truncate text-right">
          <span className="tabular-nums text-muted">
            ${formatOdds(away.implied_odds)}
          </span>{" "}
          <span className="tabular-nums text-ink-2">
            {formatPercent(away.probability)}
          </span>{" "}
          <span className="font-medium">{awayTeam}</span>
          <span
            aria-hidden
            className="ml-1.5 inline-block h-2 w-2 rounded-full bg-series-away align-baseline"
          />
        </span>
      </div>
      <div
        role="img"
        aria-label={`${homeTeam} ${formatPercent(home.probability)}, ${awayTeam} ${formatPercent(away.probability)}`}
        className="flex h-2.5 w-full gap-[2px]"
      >
        <div
          className="rounded-[4px] bg-series-home"
          style={{ width: `${homePct}%` }}
        />
        <div className="flex-1 rounded-[4px] bg-series-away" />
      </div>
    </div>
  );
}
