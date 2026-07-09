import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Responsible gambling — GenPicks",
  description:
    "GenPicks is an educational portfolio project, not a betting service. What our numbers are, what they are not, and where to find help.",
};

// Fully static: no data, no API dependency — this page must render even
// when the prediction API is down.
export default function ResponsibleGamblingPage() {
  return (
    <div className="max-w-prose">
      <h1 className="mb-2 text-xl font-semibold tracking-tight">
        Responsible gambling
      </h1>
      <p className="mb-6 text-sm text-ink-2">
        GenPicks is a portfolio project built for educational purposes. It is
        not a bookmaker, a tipping service, or a source of betting advice.
      </p>

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium">What the numbers mean</h2>
        <p className="mb-2 text-sm text-ink-2">
          Every probability on this site is the output of a statistical model
          trained on historical match data. Models are wrong routinely and
          sometimes badly: they know nothing about late injuries, weather,
          team news, or anything else that is not in their training data. The
          &ldquo;implied odds&rdquo; shown are a mathematical restatement of
          those probabilities, not prices anyone is offering you.
        </p>
        <p className="text-sm text-ink-2">
          Bookmaker prices shown alongside are collected periodically from
          third parties and may be stale or wrong by the time you read them.
          Our own public track record shows the model trailing the closing
          market on log loss — meaning that even a well-built model does not
          beat the bookmakers&apos; prices, and neither should you expect to.
        </p>
      </section>

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium">If you choose to bet</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
          <li>You must be 18 or older, and gambling laws vary by location.</li>
          <li>Only ever stake money you can afford to lose entirely.</li>
          <li>Set a limit before you start and stop when you reach it.</li>
          <li>Never chase losses.</li>
          <li>
            Gambling is entertainment with a cost, not a way to make money.
          </li>
        </ul>
      </section>

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium">Getting help</h2>
        <p className="mb-2 text-sm text-ink-2">
          If gambling is causing problems for you or someone you know, free
          and confidential help is available 24/7:
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
          <li>
            <strong>Gambling Help Online</strong> — call{" "}
            <a href="tel:1800858858" className="underline">
              1800 858 858
            </a>{" "}
            or visit{" "}
            <a
              href="https://www.gamblinghelponline.org.au"
              className="underline"
              rel="noopener noreferrer"
            >
              gamblinghelponline.org.au
            </a>
          </li>
          <li>
            <strong>BetStop</strong> — the National Self-Exclusion Register:{" "}
            <a
              href="https://www.betstop.gov.au"
              className="underline"
              rel="noopener noreferrer"
            >
              betstop.gov.au
            </a>
          </li>
        </ul>
      </section>
    </div>
  );
}
