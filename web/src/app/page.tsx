import Link from "next/link";
import { getUpcoming } from "@/lib/api";
import { MarketOddsLine } from "@/components/market-odds";
import { ProbBar } from "@/components/prob-bar";

export const dynamic = "force-dynamic";

function formatDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

export default async function FixturesPage() {
  const matches = await getUpcoming(20);

  if (matches === null) {
    return (
      <p className="text-sm text-muted">
        The prediction API is not reachable. Start it with{" "}
        <code className="font-mono">uvicorn genpicks.api.main:app</code>.
      </p>
    );
  }
  if (matches.length === 0) {
    return <p className="text-sm text-muted">No upcoming fixtures.</p>;
  }

  const modelVersion = matches.find((m) => m.win_probabilities)
    ?.win_probabilities?.model_version;

  return (
    <div>
      <div className="mb-6 flex items-baseline justify-between">
        <h1 className="text-xl font-semibold tracking-tight">
          Upcoming fixtures
        </h1>
        {modelVersion && (
          <span className="text-xs text-muted">model {modelVersion}</span>
        )}
      </div>
      <ul className="space-y-3">
        {matches.map((m) => (
          <li key={m.match_id}>
            <Link
              href={`/matches/${m.match_id}`}
              className="block rounded-lg border border-hairline bg-surface p-4 transition-colors hover:border-muted"
            >
              <div className="mb-2 flex items-baseline justify-between text-xs text-muted">
                <span>
                  Round {m.round} · {formatDate(m.date)}
                  {m.venue ? ` · ${m.venue}` : ""}
                </span>
                <span>try markets →</span>
              </div>
              <ProbBar
                homeTeam={m.home_team}
                awayTeam={m.away_team}
                home={m.win_probabilities?.home}
                away={m.win_probabilities?.away}
              />
              <MarketOddsLine odds={m.market_odds} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
