import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import {
  createCheckoutUrl,
  formatMatchDate,
  formatOdds,
  formatPercent,
  getMatchMarkets,
  type MatchMarkets,
  type PlayerMarketEntry,
} from "@/lib/api";
import { teamAbbr } from "@/lib/team-names";
import { FactorBars } from "@/components/factor-bars";
import { ProbBar } from "@/components/prob-bar";

export const dynamic = "force-dynamic";

// The identical getMatchMarkets fetch below in the page body is memoized
// by Next within the request, so the title costs no extra API call.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const session = await auth();
  const markets = await getMatchMarkets(id, session?.genpicksUserId);
  if (!markets?.home_team || !markets?.away_team) return {};
  return {
    title: `${markets.home_team} v ${markets.away_team} — GenPicks`,
    description: `Model win probabilities, implied odds, and player try-scorer markets for ${markets.home_team} v ${markets.away_team}.`,
  };
}

// Ranked single-measure table: the in-row bar is magnitude, so it uses one
// hue (not per-row colors); length is scaled to the table's top entry and
// every value is also printed as text.
function MarketTable({
  title,
  entries,
  homeTeam,
}: {
  title: string;
  entries: PlayerMarketEntry[];
  homeTeam: string | null;
}) {
  const max = entries.length ? entries[0].probability : 1;
  return (
    <section className="rounded-lg border border-hairline bg-surface p-4">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {entries.length === 0 ? (
        <p className="text-sm text-muted">No prices generated.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="pb-2 font-normal">Player</th>
              <th className="pb-2 font-normal" aria-hidden />
              <th className="pb-2 pr-3 text-right font-normal">Prob.</th>
              <th className="pb-2 text-right font-normal">Odds</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={`${e.player}-${e.team}`} className="border-t border-hairline">
                <td className="py-1.5 pr-2">
                  <span
                    aria-hidden
                    className={`mr-1.5 inline-block h-2 w-2 rounded-full ${
                      e.team === homeTeam ? "bg-series-home" : "bg-series-away"
                    }`}
                  />
                  {e.player}
                  <span
                    className="ml-1 whitespace-nowrap text-xs text-muted"
                    title={e.team ?? undefined}
                  >
                    {teamAbbr(e.team)}
                  </span>
                </td>
                <td className="w-14 py-1.5 pr-3">
                  <div className="h-1.5 w-full">
                    <div
                      className="h-full rounded-[3px] bg-bar-hue"
                      style={{ width: `${(e.probability / max) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-ink-2">
                  {formatPercent(e.probability)}
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  ${formatOdds(e.implied_odds)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

// Shown in place of the try-scorer tables when the API withheld them.
// The real enforcement is server-side in the API; this is just its UI.
function LockedMarkets({
  markets,
  signedIn,
  matchId,
}: {
  markets: MatchMarkets;
  signedIn: boolean;
  matchId: string;
}) {
  const total =
    markets.try_market_counts.anytime_try + markets.try_market_counts.first_try;
  return (
    <section className="rounded-lg border border-hairline bg-surface p-6 text-center">
      <h2 className="mb-1 text-sm font-semibold">
        Player try markets are a Pro feature
      </h2>
      <p className="mx-auto mb-4 max-w-md text-sm text-muted">
        {total > 0
          ? `${total} model prices for this match — anytime and first try scorer, with implied odds — unlock with a GenPicks Pro subscription.`
          : "Anytime and first try scorer prices unlock with a GenPicks Pro subscription."}
      </p>
      {signedIn ? (
        <form
          action={async () => {
            "use server";
            const session = await auth();
            const path = `/matches/${matchId}`;
            if (!session?.genpicksUserId) redirect(path);
            const h = await headers();
            const origin = `${h.get("x-forwarded-proto") ?? "http"}://${h.get("host")}`;
            const url = await createCheckoutUrl(
              session.genpicksUserId,
              origin,
              path,
            );
            redirect(url ?? `${path}?billing=unavailable`);
          }}
        >
          <button
            type="submit"
            className="rounded-md border border-hairline px-4 py-2 text-sm font-medium hover:text-ink"
          >
            Subscribe — demo checkout
          </button>
          <p className="mt-2 text-xs text-muted">
            Portfolio demo: Stripe test mode, no real payments. Use card
            number 4242 4242 4242 4242 with any future expiry and CVC.
          </p>
        </form>
      ) : (
        <form
          action={async () => {
            "use server";
            await signIn("github", { redirectTo: `/matches/${matchId}` });
          }}
        >
          <button
            type="submit"
            className="rounded-md border border-hairline px-4 py-2 text-sm font-medium hover:text-ink"
          >
            Sign in with GitHub to get started
          </button>
        </form>
      )}
    </section>
  );
}

export default async function MatchPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ subscribed?: string; billing?: string }>;
}) {
  const { id } = await params;
  const { subscribed, billing } = await searchParams;
  const session = await auth();
  const markets = await getMatchMarkets(id, session?.genpicksUserId);
  if (markets === null) notFound();

  // post-checkout return states: the webhook can lag the redirect by a
  // few seconds, so "paid but still locked" gets its own message
  const banner =
    subscribed === "1"
      ? markets.try_markets_locked
        ? "Payment received — your subscription is activating. Refresh in a few seconds."
        : "GenPicks Pro is active — player try markets unlocked."
      : billing === "unavailable"
        ? "Checkout is currently unavailable — please try again shortly."
        : null;

  return (
    <div>
      {banner !== null && (
        <p className="mb-4 rounded-md border border-hairline bg-surface px-4 py-2.5 text-sm text-ink-2">
          {banner}
        </p>
      )}
      <div className="mb-6">
        {markets.date !== null && (
          <p className="mb-1 text-xs text-muted">
            {formatMatchDate(markets.date)}
          </p>
        )}
        <h1 className="mb-4 text-xl font-semibold tracking-tight">
          {markets.home_team} v {markets.away_team}
        </h1>
        <div className="rounded-lg border border-hairline bg-surface p-4">
          <ProbBar
            homeTeam={markets.home_team}
            awayTeam={markets.away_team}
            home={markets.h2h.home}
            away={markets.h2h.away}
            marketOdds={markets.market_odds}
          />
        </div>
      </div>
      {markets.h2h_explanation !== null && (
        <div className="mb-6">
          <FactorBars
            explanation={markets.h2h_explanation}
            homeTeam={markets.home_team}
            awayTeam={markets.away_team}
          />
        </div>
      )}
      {markets.try_markets_locked ? (
        <LockedMarkets
          markets={markets}
          signedIn={session?.user != null}
          matchId={id}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <MarketTable
            title="Anytime try scorer"
            entries={markets.anytime_try ?? []}
            homeTeam={markets.home_team}
          />
          <MarketTable
            title="First try scorer"
            entries={markets.first_try ?? []}
            homeTeam={markets.home_team}
          />
        </div>
      )}
      {!markets.try_markets_locked && markets.lineup_source !== null && (
        <p className="mt-4 text-xs text-muted">
          {markets.lineup_source === "official"
            ? "Player markets use the officially named team lists."
            : "Player markets use lineups projected from each team's most recent match; they update when official team lists are published."}
        </p>
      )}
    </div>
  );
}
