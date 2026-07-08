"""Get-or-create entity resolution through the alias tables.

A Resolver is bound to one source (e.g. "rlp") and one session. Lookups are
cached per instance, so a season-long ingest does one query per distinct
alias at most.

Alias choice per entity type:
- players: the source's stable numeric id ONLY. Names are never player
  aliases — two players can share a name.
- venues: the source's stable numeric id, plus every display name seen.
  Sponsor renames therefore collapse onto one physical venue automatically,
  because the id alias resolves first.
- teams: the source's slug, plus the short display name.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from genpicks.db.models import (
    Player,
    PlayerAlias,
    Team,
    TeamAlias,
    Venue,
    VenueAlias,
)
from genpicks.ingest.names import prettify_player_name, team_name_from_slug


def adopt_orphan_player(session: Session, source: str, full_name: str) -> Player | None:
    """A same-name player no row from `source` has claimed yet.

    Sources can meet the same debutant in either order — NRL.com shows real
    minutes for a match where RLP's scoresheet lists only a reserve slot, and
    RLP first credits the player rounds later under a fresh id (observed:
    Xavier Savage, 2021). Whichever source arrives second must claim the
    existing human instead of minting a second Player that double-counts them
    forever. Names alone are never trusted as aliases, but for the narrow
    orphan case (no alias from this source) exact-name adoption is safe;
    ambiguity (two orphans sharing the name) declines and the caller creates
    a new player as before.
    """
    orphans = session.scalars(
        select(Player).where(
            Player.full_name == full_name,
            ~select(PlayerAlias.id)
            .where(
                PlayerAlias.player_id == Player.id,
                PlayerAlias.source == source,
            )
            .exists(),
        )
    ).all()
    return orphans[0] if len(orphans) == 1 else None


class Resolver:
    def __init__(self, session: Session, source: str) -> None:
        self.session = session
        self.source = source
        self._cache: dict[tuple[type, str], int] = {}

    def team(self, slug: str, display_name: str) -> Team:
        team = self._resolve(Team, TeamAlias, "team_id", slug)
        if team is None:
            team = Team(name=team_name_from_slug(slug))
            self.session.add(team)
            self.session.flush()
            self._record_alias(Team, TeamAlias, "team_id", team.id, slug)
        if display_name and display_name != slug:
            self._ensure_alias(Team, TeamAlias, "team_id", team.id, display_name)
        return team

    def venue(
        self, source_id: str, display_name: str | None, city: str | None = None
    ) -> Venue:
        venue = self._resolve(Venue, VenueAlias, "venue_id", source_id)
        if venue is None:
            name = display_name or f"{self.source} venue {source_id}"
            # Distinct source ids can share a display name and still be
            # different venues (the old and rebuilt Sydney Football Stadium
            # are both "Allianz" on RLP); canonical names must stay unique.
            if self.session.scalar(select(Venue).where(Venue.name == name)):
                name = f"{name} ({self.source} {source_id})"
            venue = Venue(name=name, city=city)
            self.session.add(venue)
            self.session.flush()
            self._record_alias(Venue, VenueAlias, "venue_id", venue.id, source_id)
        if city and venue.city is None:
            venue.city = city
        if display_name:
            self._ensure_alias(Venue, VenueAlias, "venue_id", venue.id, display_name)
        return venue

    def player(self, source_id: str, display_name: str) -> Player:
        player = self._resolve(Player, PlayerAlias, "player_id", source_id)
        if player is None:
            player = adopt_orphan_player(
                self.session, self.source, prettify_player_name(display_name)
            )
        if player is None:
            player = Player(full_name=prettify_player_name(display_name))
            self.session.add(player)
            self.session.flush()
        self._ensure_alias(Player, PlayerAlias, "player_id", player.id, source_id)
        return player

    # -- internals ---------------------------------------------------------

    def _resolve(self, entity_cls, alias_cls, fk_name: str, alias: str):
        key = (entity_cls, alias)
        if key not in self._cache:
            row = self.session.scalar(
                select(alias_cls).where(
                    alias_cls.source == self.source, alias_cls.alias == alias
                )
            )
            if row is None:
                return None
            self._cache[key] = getattr(row, fk_name)
        return self.session.get(entity_cls, self._cache[key])

    def _record_alias(
        self, entity_cls, alias_cls, fk_name: str, entity_id: int, alias: str
    ) -> None:
        self.session.add(
            alias_cls(**{fk_name: entity_id, "alias": alias, "source": self.source})
        )
        self.session.flush()
        self._cache[(entity_cls, alias)] = entity_id

    def _ensure_alias(
        self, entity_cls, alias_cls, fk_name: str, entity_id: int, alias: str
    ) -> None:
        """Add the alias unless it already exists (pointing wherever it points)."""
        if (entity_cls, alias) in self._cache:
            return
        existing = self.session.scalar(
            select(alias_cls).where(
                alias_cls.source == self.source, alias_cls.alias == alias
            )
        )
        if existing is None:
            self._record_alias(entity_cls, alias_cls, fk_name, entity_id, alias)
        else:
            self._cache[(entity_cls, alias)] = getattr(existing, fk_name)
