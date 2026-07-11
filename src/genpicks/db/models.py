"""Core relational schema.

Design notes:

- Every real-world entity that appears under multiple names in source data
  (teams, venues, players) has a canonical row plus an alias table. Ingestion
  resolves raw strings through aliases so downstream tables only ever hold
  canonical ids. Venues especially: NRL stadiums change sponsor names often,
  and home-advantage / travel features require one id per physical location.
- Aliases are unique per (source, alias): two sources may spell a name the
  same way, and one source may reuse a name for different entities over time
  is NOT supported — that case needs manual curation at ingestion.
- Raw scraped payloads live outside the database (data/raw/); these tables
  hold only cleaned, validated data and must be rebuildable from raw.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    abbreviation: Mapped[str | None] = mapped_column(String(10))

    aliases: Mapped[list["TeamAlias"]] = relationship(back_populates="team")


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("source", "alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    alias: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(50))

    team: Mapped[Team] = relationship(back_populates="aliases")


class Venue(Base):
    """One row per physical location, regardless of current sponsor name."""

    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(50))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    aliases: Mapped[list["VenueAlias"]] = relationship(back_populates="venue")


class VenueAlias(Base):
    __tablename__ = "venue_aliases"
    __table_args__ = (UniqueConstraint("source", "alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"))
    alias: Mapped[str] = mapped_column(String(150), index=True)
    source: Mapped[str] = mapped_column(String(50))

    venue: Mapped[Venue] = relationship(back_populates="aliases")


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150), index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date)

    aliases: Mapped[list["PlayerAlias"]] = relationship(back_populates="player")


class PlayerAlias(Base):
    __tablename__ = "player_aliases"
    __table_args__ = (UniqueConstraint("source", "alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    alias: Mapped[str] = mapped_column(String(150), index=True)
    source: Mapped[str] = mapped_column(String(50))

    player: Mapped[Player] = relationship(back_populates="aliases")


# --------------------------------------------------------------------------
# Facts
# --------------------------------------------------------------------------


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("source", "source_key"),
        Index("ix_matches_season_round", "season", "round"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    season: Mapped[int]
    round: Mapped[str] = mapped_column(String(20))  # "1".."27", "QF", "EF", "SF", "PF", "GF"
    # Local calendar date at the venue. kickoff_utc additionally needs the
    # venue's timezone (Vegas, NZ, and no-DST Queensland make a blanket
    # AEST assumption wrong), so it stays null until that mapping exists;
    # rest-day features should use match_date.
    match_date: Mapped[date | None] = mapped_column(Date)
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id"))
    home_score: Mapped[int | None]  # null until the match has been played
    away_score: Mapped[int | None]
    source: Mapped[str] = mapped_column(String(50))
    source_key: Mapped[str] = mapped_column(String(100))


class MatchSourceKey(Base):
    """A source's identifier for a match we already hold canonically.

    matches.source/source_key records who created the row (rugbyleagueproject);
    additional sources (nrl.com, betfair, tab) attach their ids here after
    reconciliation so their data can be joined without re-matching by
    teams/date every time.
    """

    __tablename__ = "match_source_keys"
    __table_args__ = (UniqueConstraint("source", "source_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    source: Mapped[str] = mapped_column(String(50))
    source_key: Mapped[str] = mapped_column(String(100))


class PlayerMatchStats(Base):
    """One row per player per match appearance."""

    __tablename__ = "player_match_stats"
    __table_args__ = (UniqueConstraint("match_id", "player_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    position: Mapped[str | None] = mapped_column(String(30))
    jersey_number: Mapped[int | None]
    minutes_played: Mapped[int | None]
    tries: Mapped[int | None]
    try_assists: Mapped[int | None]
    line_breaks: Mapped[int | None]
    tackle_breaks: Mapped[int | None]
    run_metres: Mapped[int | None]
    tackles: Mapped[int | None]
    missed_tackles: Mapped[int | None]
    offloads: Mapped[int | None]
    errors: Mapped[int | None]


class TryEvent(Base):
    """One row per try scored, ordered within the match.

    scoring_order starts at 1 for the first try of the match — this ordering
    is what the first-try-scorer model trains on. player_id is nullable to
    represent penalty tries or historical records with unknown scorers.
    """

    __tablename__ = "try_events"
    __table_args__ = (UniqueConstraint("match_id", "scoring_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    scoring_order: Mapped[int]
    minute: Mapped[int | None]


class TeamListEntry(Base):
    """One named player on an official pre-match team list.

    A match's entries are replaced wholesale each ingest, so the table always
    holds the newest published list (late changes overwrite); historical
    snapshots live in data/raw/. player_name is the string as published;
    player_id stays null when the name cannot be resolved through the alias
    tables (e.g. a debutant with no appearance history) — such players are
    skipped by the prediction lineup, never invented as new Player rows,
    because the played-match ingest owns player creation.
    """

    __tablename__ = "team_list_entries"
    __table_args__ = (Index("ix_team_list_entries_match", "match_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    player_name: Mapped[str] = mapped_column(String(150))
    position: Mapped[str | None] = mapped_column(String(30))  # canonical vocabulary
    jersey_number: Mapped[int | None]
    source: Mapped[str] = mapped_column(String(50))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------


class User(Base):
    """A website account, created on first OAuth sign-in.

    Rows are written only by the Next.js server through the internal
    user-sync endpoint (shared-key protected), never by ingestion. Stripe
    fields stay null until the test-mode checkout flow fills them in;
    subscription_status mirrors Stripe's status string ("active",
    "canceled", ...) and null means never subscribed.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[str] = mapped_column(String(30), unique=True)
    email: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(150))
    avatar_url: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    subscription_status: Mapped[str | None] = mapped_column(String(30))


# --------------------------------------------------------------------------
# Odds and predictions
# --------------------------------------------------------------------------

# Market identifiers used in odds_snapshots.market and predictions.market:
#   "h2h"          — match winner
#   "anytime_try"  — player to score a try at any time
#   "first_try"    — player to score the first try
MARKET_H2H = "h2h"
MARKET_ANYTIME_TRY = "anytime_try"
MARKET_FIRST_TRY = "first_try"


class OddsSnapshot(Base):
    """A price observed at a bookmaker/exchange at a point in time.

    selection_name preserves the raw string from the source; team_id/player_id
    are filled in once the selection is resolved through the alias tables and
    stay null when it cannot be resolved (no data is thrown away).
    """

    __tablename__ = "odds_snapshots"
    __table_args__ = (Index("ix_odds_match_market_time", "match_id", "market", "captured_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))  # "betfair", "tab", ...
    market: Mapped[str] = mapped_column(String(30))
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    selection_name: Mapped[str] = mapped_column(String(150))
    price_decimal: Mapped[float] = mapped_column(Numeric(8, 3))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict | None] = mapped_column(JSON)


class Prediction(Base):
    """Model output, versioned and append-only to build a public track record."""

    __tablename__ = "predictions"
    __table_args__ = (Index("ix_predictions_match_market", "match_id", "market"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version: Mapped[str] = mapped_column(String(50))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    market: Mapped[str] = mapped_column(String(30))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    probability: Mapped[float] = mapped_column(Float)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # which lineup this generation was computed from: "projected" (last
    # played match) or "official" (ingested team list); null on h2h rows
    # written before availability became a model feature (reads as
    # projected). A projected generation is superseded — by appending,
    # never updating — once the official list arrives; readers take the
    # newest generation.
    lineup_source: Mapped[str | None] = mapped_column(String(20))
