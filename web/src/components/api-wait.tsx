// Route-level loading state. The API sleeps on free-tier hosting and can
// take up to a minute to wake after a quiet spell — say so instead of
// showing a blank page or an anonymous spinner.
export function ApiWait({ what }: { what: string }) {
  return (
    <div>
      <div className="mb-6 space-y-2" aria-hidden>
        <div className="h-6 w-48 animate-pulse rounded bg-hairline" />
        <div className="h-4 w-full max-w-prose animate-pulse rounded bg-hairline" />
        <div className="h-4 w-2/3 max-w-prose animate-pulse rounded bg-hairline" />
      </div>
      <div className="space-y-4" aria-hidden>
        <div className="h-28 animate-pulse rounded-lg border border-hairline bg-surface" />
        <div className="h-28 animate-pulse rounded-lg border border-hairline bg-surface" />
      </div>
      <p role="status" className="mt-6 text-sm text-muted">
        Loading {what} — if the site has been quiet, the prediction API is
        waking from its free-tier nap and can take up to a minute.
      </p>
    </div>
  );
}
