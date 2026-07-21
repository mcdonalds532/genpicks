import { teamLogoSrc } from "@/lib/team-logos";

// The club mark when one has been supplied, otherwise the original
// home/away dot. The dot is the load-bearing element: blue/green is the
// validated home-vs-away encoding, and it must survive a club having no
// logo, so the fallback is never an empty space.
//
// The mark and the dot share one fixed-size box, so a club without a file
// occupies exactly the same room as one with a crest and nothing beside
// it shifts. The dot keeps its own small size inside that box rather than
// scaling with it — blown up to 36px it reads as a bug, not an encoding.
//
// aria-hidden throughout — every use sits directly beside the team name in
// text, so a described logo would just announce the club twice.
export function TeamLogo({
  team,
  side,
  size = 18,
  className = "",
}: {
  team: string | null;
  side: "home" | "away";
  size?: number;
  className?: string;
}) {
  const src = teamLogoSrc(team);
  const dotHue = side === "home" ? "bg-series-home" : "bg-series-away";

  return (
    <span
      aria-hidden
      className={`inline-flex shrink-0 items-center justify-center ${className}`}
      style={{ width: size, height: size }}
    >
      {src === null ? (
        <span className={`block h-2 w-2 rounded-full ${dotHue}`} />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- fixed-size club mark, not worth the image optimizer
        <img
          src={src}
          alt=""
          width={size}
          height={size}
          className="h-full w-full object-contain"
        />
      )}
    </span>
  );
}
