import fs from "node:fs";
import path from "node:path";

// Club marks are supplied by the site owner (they are club trademarks, not
// ours to vendor) and dropped into web/public/logos as <slug>.<ext>. Any
// team without a file falls back to the plain home/away dot, so the site
// renders correctly with none, some, or all of them present.
const LOGO_DIR = path.join(process.cwd(), "public", "logos");
const EXTENSIONS = [".svg", ".png", ".webp"];

export const teamSlug = (team: string) =>
  team
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

// The production and local databases do not agree on every teams.name:
// production stores the bare "Cronulla" where the local dataset stores
// "Cronulla Sutherland Sharks", so the slug alone missed the file and the
// club showed its fallback dot on the deployed site only. Aliases map the
// variants onto one filename rather than duplicating the asset — add here
// if another club's name drifts between the two.
const SLUG_ALIASES: Record<string, string> = {
  cronulla: "cronulla-sutherland-sharks",
};

// Indexed once per server process: the directory is a handful of static
// files that only change on deploy. In dev, restart to pick up new drops.
let index: Map<string, string> | null = null;

function logoIndex(): Map<string, string> {
  if (index !== null) return index;
  const found = new Map<string, string>();
  let entries: string[];
  try {
    entries = fs.readdirSync(LOGO_DIR);
  } catch {
    // No logos directory at all — every team falls back to its dot.
    index = found;
    return found;
  }
  for (const entry of entries) {
    const ext = path.extname(entry).toLowerCase();
    if (!EXTENSIONS.includes(ext)) continue;
    // First extension wins in EXTENSIONS order, so an .svg beats a .png
    // of the same club rather than depending on readdir order.
    const slug = path.basename(entry, path.extname(entry));
    const existing = found.get(slug);
    if (
      existing === undefined ||
      EXTENSIONS.indexOf(ext) <
        EXTENSIONS.indexOf(path.extname(existing).toLowerCase())
    ) {
      found.set(slug, `/logos/${entry}`);
    }
  }
  index = found;
  return found;
}

/** Public URL of a club's mark, or null when no file has been supplied. */
export function teamLogoSrc(team: string | null): string | null {
  if (team === null) return null;
  const slug = teamSlug(team);
  return logoIndex().get(SLUG_ALIASES[slug] ?? slug) ?? null;
}
