import { teamLogoSrc } from "@/lib/team-logos";

// The club mark when one has been supplied, otherwise the original
// home/away dot. The dot is the load-bearing element: blue/green is the
// validated home-vs-away encoding, and it must survive a club having no
// logo, so the fallback is never an empty space.
//
// alt="" throughout — every use sits directly beside the team name in
// text, so a described logo would just announce the club twice.
export function TeamLogo({
  team,
  side,
  className = "",
}: {
  team: string | null;
  side: "home" | "away";
  className?: string;
}) {
  const src = teamLogoSrc(team);
  const dotHue = side === "home" ? "bg-series-home" : "bg-series-away";

  if (src === null) {
    return (
      <span
        aria-hidden
        className={`inline-block h-2 w-2 rounded-full align-baseline ${dotHue} ${className}`}
      />
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- fixed 18px club mark, not worth the image optimizer
    <img
      src={src}
      alt=""
      width={18}
      height={18}
      className={`inline-block h-[18px] w-[18px] shrink-0 object-contain align-text-bottom ${className}`}
    />
  );
}
