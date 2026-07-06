"""Raw-to-clean transforms: parsed scraper output into the relational schema.

All entity references pass through the alias tables (see db.models notes).
Loaders are idempotent upserts keyed on source ids, so re-running ingestion
over the same raw files is always safe.
"""
