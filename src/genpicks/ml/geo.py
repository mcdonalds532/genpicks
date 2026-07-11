"""City-level geography for travel features.

Venue rows all carry a city (34 distinct across 53 venues), so coordinates
are kept per city, not per stadium: the signal is Auckland-to-Townsville,
not which side of a metro area the ground sits on. Teams map to a home city
by canonical DB name; a venue counts as "at home" within METRO_KM so that
metro-sprawl grounds (Wollongong and Campbelltown for Sydney clubs, Gosford)
are not mistaken for away trips.

Unknown cities or teams yield NaN travel features rather than raising:
XGBoost treats missing natively, and a future expansion team or new venue
must not crash the weekly refresh.
"""

import math

# Approximate CBD coordinates; city-level precision is deliberate.
CITY_COORDS: dict[str, tuple[float, float]] = {
    "Adelaide": (-34.93, 138.60),
    "Auckland": (-36.85, 174.76),
    "Bathurst": (-33.42, 149.58),
    "Brisbane": (-27.47, 153.03),
    "Bundaberg": (-24.87, 152.35),
    "Cairns": (-16.92, 145.77),
    "Campbelltown": (-34.07, 150.81),
    "Canberra": (-35.28, 149.13),
    "Christchurch": (-43.53, 172.64),
    "Coffs Harbour": (-30.30, 153.11),
    "Darwin": (-12.46, 130.84),
    "Dubbo": (-32.24, 148.60),
    "Dunedin": (-45.87, 170.50),
    "Gladstone": (-23.84, 151.26),
    "Gold Coast": (-28.00, 153.43),
    "Gosford": (-33.43, 151.34),
    "Hamilton": (-37.79, 175.28),
    "Las Vegas": (36.17, -115.14),
    "Mackay": (-21.14, 149.19),
    "Melbourne": (-37.81, 144.96),
    "Mudgee": (-32.59, 149.59),
    "Napier": (-39.49, 176.92),
    "New Plymouth": (-39.06, 174.08),
    "Newcastle": (-32.93, 151.78),
    "Palmerston North": (-40.35, 175.61),
    "Perth": (-31.95, 115.86),
    "Rockhampton": (-23.38, 150.51),
    "Sydney": (-33.87, 151.21),
    "Tamworth": (-31.09, 150.93),
    "Toowoomba": (-27.56, 151.95),
    "Townsville": (-19.26, 146.82),
    "Wagga Wagga": (-35.11, 147.37),
    "Wellington": (-41.29, 174.78),
    "Wollongong": (-34.43, 150.89),
}

# Canonical teams.name -> home city. The Dragons split home games between
# Kogarah (Sydney) and Wollongong; either choice stays "at home" under
# METRO_KM so the pick only affects a ~70 km travel figure.
TEAM_HOME_CITY: dict[str, str] = {
    "Brisbane Broncos": "Brisbane",
    "Canberra Raiders": "Canberra",
    "Canterbury Bankstown Bulldogs": "Sydney",
    "Cronulla Sutherland Sharks": "Sydney",
    "Dolphins": "Brisbane",
    "Gold Coast Titans": "Gold Coast",
    "Manly Warringah Sea Eagles": "Sydney",
    "Melbourne": "Melbourne",
    "Newcastle Knights": "Newcastle",
    "North Queensland Cowboys": "Townsville",
    "Parramatta Eels": "Sydney",
    "Penrith Panthers": "Sydney",
    "South Sydney Rabbitohs": "Sydney",
    "St George Illawarra Dragons": "Wollongong",
    "Sydney Roosters": "Sydney",
    "Warriors": "Auckland",
    "Wests Tigers": "Sydney",
}

# Within this distance a venue is the team's own patch, not a road trip.
METRO_KM = 100.0

_EARTH_RADIUS_KM = 6371.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def travel_km(team_name: str, venue_city: str | None) -> float:
    """Distance from a team's home city to the venue city; NaN if unknown."""
    home_city = TEAM_HOME_CITY.get(team_name)
    if home_city is None or venue_city is None or venue_city not in CITY_COORDS:
        return math.nan
    return haversine_km(CITY_COORDS[home_city], CITY_COORDS[venue_city])
