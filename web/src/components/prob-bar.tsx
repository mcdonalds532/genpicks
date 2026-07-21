import { formatOdds, formatPercent, type WinProbability } from "@/lib/api";
import { TeamLogo } from "@/components/team-logo";

// Roughly the height of the label row plus the bar, so the marks read as
// bookends to the block rather than as a third row of their own.
const LOGO_SIZE = 36;

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
  // The marks flank the whole block rather than sitting inline beside the
  // names, so the label row and the bar share one left and right edge:
  // each team's text lands over its own segment of the bar.
  return (
    <div className="flex items-center gap-3">
      <TeamLogo team={homeTeam} side="home" size={LOGO_SIZE} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline justify-between gap-4 text-sm">
          <span className="min-w-0 truncate">
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
      <TeamLogo team={awayTeam} side="away" size={LOGO_SIZE} />
    </div>
  );
}
