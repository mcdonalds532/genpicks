# Club marks

Drop club logo files here and they appear automatically beside team names on
the fixtures list and the match page. Nothing else needs changing.

NRL club logos are registered trademarks of their clubs, and because GenPicks
presents as a product (Pro tier, checkout flow), shipping them could imply an
affiliation or endorsement that does not exist. The marks committed here are
used solely to identify which team a prediction refers to; the site footer and
the root `LICENSE` both disclaim affiliation and exclude these files from the
project's MIT grant. Keep all three in step if you add or replace a file, and
supply only files you hold the rights to use.

## Naming

One file per club, named for the club's lowercase name with every run of
non-alphanumeric characters collapsed to a single `-`. Resolution order is
`.svg`, then `.png`, then `.webp` — so an `.svg` wins over a `.png` of the same
club regardless of directory order.

| Team (as stored in `teams.name`) | Filename |
| --- | --- |
| Brisbane Broncos | `brisbane-broncos.svg` |
| Canberra Raiders | `canberra-raiders.svg` |
| Canterbury Bankstown Bulldogs | `canterbury-bankstown-bulldogs.svg` |
| Cronulla Sutherland Sharks | `cronulla-sutherland-sharks.svg` |
| Dolphins | `dolphins.svg` |
| Gold Coast Titans | `gold-coast-titans.svg` |
| Manly Warringah Sea Eagles | `manly-warringah-sea-eagles.svg` |
| Melbourne | `melbourne.svg` |
| Newcastle Knights | `newcastle-knights.svg` |
| North Queensland Cowboys | `north-queensland-cowboys.svg` |
| Parramatta Eels | `parramatta-eels.svg` |
| Penrith Panthers | `penrith-panthers.svg` |
| South Sydney Rabbitohs | `south-sydney-rabbitohs.svg` |
| St George Illawarra Dragons | `st-george-illawarra-dragons.svg` |
| Sydney Roosters | `sydney-roosters.svg` |
| Warriors | `warriors.svg` |
| Wests Tigers | `wests-tigers.svg` |

## Behaviour

- A club with **no file** falls back to its home/away dot. Missing logos are
  not an error, and the site is fully usable with none of them present.
- Marks render at 18×18 by default and 36×36 flanking the probability bar,
  and are `alt=""`: the team name always sits beside them, so describing the
  logo would announce the club twice.
- The directory is indexed **once per server process**. In `npm run dev`,
  restart the dev server after adding files.
- Square or near-square marks work best; anything else is letterboxed by
  `object-contain` rather than distorted.
