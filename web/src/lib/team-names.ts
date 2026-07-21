// Shorter ways to name a club, for the surfaces where the full stored name
// crowds out the numbers beside it: the nickname alone on the fixture cards
// ("Eels", "Storm"), and a three-letter code in the try-scorer tables, where
// the tag sits inline after a player's name. Full names still carry the page
// headings and every aria-label, so neither form is the only naming.
//
// Matched on keywords rather than the whole name because the production and
// local databases do not agree on every teams.name (production stores the
// bare "Cronulla" where the local dataset stores "Cronulla Sutherland
// Sharks") — see the same drift handled in ./team-logos. Matching either the
// city or the nickname covers both without enumerating every variant, and
// it means a club stored without its nickname ("Melbourne") still gets one.
//
// Order matters: "South Sydney Rabbitohs" must be claimed before the plain
// "Sydney" rule reaches it.
const RULES: Array<[RegExp, string, string]> = [
  [/\b(south-sydney|rabbitohs)\b/, "SOU", "Rabbitohs"],
  [/\b(sydney-roosters|roosters)\b/, "SYD", "Roosters"],
  [/\b(parramatta|eels)\b/, "PAR", "Eels"],
  [/\b(penrith|panthers)\b/, "PEN", "Panthers"],
  [/\b(melbourne|storm)\b/, "MEL", "Storm"],
  [/\b(newcastle|knights)\b/, "NEW", "Knights"],
  [/\b(canberra|raiders)\b/, "CAN", "Raiders"],
  [/\b(wests?|tigers)\b/, "WES", "Tigers"],
  [/\b(canterbury|bankstown|bulldogs)\b/, "BUL", "Bulldogs"],
  [/\b(warriors)\b/, "WAR", "Warriors"],
  [/\b(north-queensland|cowboys)\b/, "NQL", "Cowboys"],
  [/\b(brisbane|broncos)\b/, "BRI", "Broncos"],
  [/\b(manly|warringah|sea-eagles)\b/, "MAN", "Sea Eagles"],
  [/\b(cronulla|sutherland|sharks)\b/, "CRO", "Sharks"],
  [/\b(st-george|illawarra|dragons)\b/, "STG", "Dragons"],
  [/\b(gold-coast|titans)\b/, "GOL", "Titans"],
  [/\b(dolphins)\b/, "DOL", "Dolphins"],
];

const slugify = (team: string) =>
  team
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

// A club we have no rule for falls back to its full stored name in both
// forms: an expansion side reads long on the card, which is far better than
// an invented code or a nickname guessed off the city.
function lookup(team: string | null, field: 1 | 2): string | null {
  if (team === null) return null;
  const slug = slugify(team);
  for (const rule of RULES) {
    if (rule[0].test(slug)) return rule[field];
  }
  return team;
}

/** Three-letter code, e.g. "South Sydney Rabbitohs" -> "SOU". */
export const teamAbbr = (team: string | null) => lookup(team, 1);

/** Nickname without the region, e.g. "Parramatta Eels" -> "Eels". */
export const teamNickname = (team: string | null) => lookup(team, 2);
