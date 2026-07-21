import type { H2hExplanation } from "@/lib/api";

// Diverging factor bars for the win-probability explanation. Direction is
// identity, not polarity: a bar pulling toward the home side wears the
// validated home hue and extends left (where ProbBar puts the home team),
// toward the away side the away hue, extending right. Identity never rides
// on color alone (the relief rule): every row names its direction in text,
// and weights are printed as numbers. Bars are scaled to the strongest
// factor of this match, so length reads within the panel only.
export function FactorBars({
  explanation,
  homeTeam,
  awayTeam,
}: {
  explanation: H2hExplanation | null;
  homeTeam: string | null;
  awayTeam: string | null;
}) {
  const factors = explanation?.factors ?? [];
  if (factors.length === 0) return null;
  const max = Math.max(...factors.map((f) => Math.abs(f.logit)));
  if (max === 0) return null;

  return (
    <section className="rounded-lg border border-hairline bg-surface p-4">
      <h2 className="mb-1 text-sm font-semibold">Why this price</h2>
      <p className="mb-3 text-xs text-muted">
        How much each factor pulled the model&apos;s win probability toward{" "}
        {homeTeam} (left) or {awayTeam} (right), from its view of this match.
      </p>
      <div className="space-y-2">
        {factors.map((f) => {
          const towardHome = f.logit >= 0;
          const width = (Math.abs(f.logit) / max) * 100;
          const team = towardHome ? homeTeam : awayTeam;
          return (
            <div
              key={f.factor}
              className="grid grid-cols-[minmax(5.5rem,9rem)_1fr_minmax(6rem,auto)] items-center gap-x-3 text-xs"
            >
              <span className="truncate text-ink-2">{f.label}</span>
              <div
                role="img"
                aria-label={`${f.label}: ${
                  f.logit === 0
                    ? "no pull either way"
                    : `${Math.round(f.share * 100)}% of the total pull, toward ${team}`
                }`}
                className="relative flex h-1.5"
              >
                <span
                  aria-hidden
                  className="absolute inset-y-[-3px] left-1/2 w-px bg-hairline"
                />
                <span className="flex w-1/2 justify-end">
                  {towardHome && f.logit !== 0 && (
                    <span
                      className="h-full rounded-l-[3px] bg-series-home"
                      style={{ width: `${width}%` }}
                    />
                  )}
                </span>
                <span className="flex w-1/2">
                  {!towardHome && (
                    <span
                      className="h-full rounded-r-[3px] bg-series-away"
                      style={{ width: `${width}%` }}
                    />
                  )}
                </span>
              </div>
              <span className="truncate text-right tabular-nums text-muted">
                {f.logit === 0 ? (
                  "—"
                ) : (
                  <>
                    <span className="text-ink-2">
                      {Math.round(f.share * 100)}%
                    </span>{" "}
                    to {team}
                  </>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
