import { getTrackRecord } from "@/lib/api";

export const dynamic = "force-dynamic";

// Stat tiles, deliberately not charts: three headline numbers per model
// version. Values are proportional figures; the grid keeps them scannable.
export default async function TrackRecordPage() {
  const record = await getTrackRecord();

  if (record === null) {
    return (
      <p className="text-sm text-muted">The prediction API is not reachable.</p>
    );
  }
  const versions = Object.entries(record);

  return (
    <div>
      <h1 className="mb-2 text-xl font-semibold tracking-tight">
        Track record
      </h1>
      <p className="mb-6 max-w-prose text-sm text-ink-2">
        Every prediction is written to an append-only log before kickoff and
        scored against the final result once the match settles. Nothing is
        retracted or rewritten.
      </p>
      {versions.length === 0 ? (
        <p className="text-sm text-muted">
          No settled predictions yet — the current round&apos;s picks are on
          the books and will appear here once results are in.
        </p>
      ) : (
        versions.map(([version, stats]) => (
          <section key={version} className="mb-6">
            <h2 className="mb-3 text-sm font-medium text-ink-2">{version}</h2>
            <div className="grid grid-cols-3 gap-4">
              <div className="rounded-lg border border-hairline bg-surface p-4">
                <p className="text-xs text-muted">Settled picks</p>
                <p className="mt-1 text-2xl font-semibold">{stats.settled}</p>
              </div>
              <div className="rounded-lg border border-hairline bg-surface p-4">
                <p className="text-xs text-muted">Winner accuracy</p>
                <p className="mt-1 text-2xl font-semibold">
                  {(stats.accuracy * 100).toFixed(1)}%
                </p>
              </div>
              <div className="rounded-lg border border-hairline bg-surface p-4">
                <p className="text-xs text-muted">Log loss</p>
                <p className="mt-1 text-2xl font-semibold">
                  {stats.log_loss.toFixed(4)}
                </p>
                <p className="mt-1 text-xs text-muted">
                  lower is better · 0.693 = coin flip
                </p>
              </div>
            </div>
          </section>
        ))
      )}
    </div>
  );
}
