"""Display-name cleanup for canonical rows.

Canonical names are cosmetic — resolution always goes through alias tables
keyed on stable source ids — so these are best-effort and safe to refine
later without re-keying anything.
"""

import re


def prettify_player_name(display: str) -> str:
    """RLP renders surnames in caps: "Roger TUIVASA-SHECK" -> "Roger Tuivasa-Sheck".

    All-caps tokens of one or two letters (initials like "KL") are kept as-is.
    """
    tokens = []
    for token in display.split():
        if token.isupper() and len(token) > 2:
            token = re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), token)
        tokens.append(token)
    return " ".join(tokens)


def team_name_from_slug(slug: str) -> str:
    """Fallback canonical name: "cronulla-sutherland-sharks" -> "Cronulla Sutherland Sharks"."""
    return " ".join(part.capitalize() for part in slug.split("-"))
