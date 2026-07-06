"""Scrapers and the raw landing zone.

Everything fetched from the network is written verbatim to data/raw/ before
any parsing. Parsers are pure functions over saved HTML so the whole clean
layer can be rebuilt offline, and fixture-based tests exercise the exact
bytes the site serves.
"""
