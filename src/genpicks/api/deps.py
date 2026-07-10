"""Shared FastAPI dependencies."""

from fastapi import Header, HTTPException

from genpicks.config import get_settings

_engine = None
_session_factory = None


def get_session():
    global _engine, _session_factory
    if _session_factory is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        _engine = create_engine(get_settings().database_url)
        _session_factory = sessionmaker(_engine)
    with _session_factory() as session:
        yield session


def is_internal(key: str | None) -> bool:
    """True when the caller presented the shared Next.js-server key.

    Fails closed: with no key configured, nothing is internal and gated
    content stays locked for everyone.
    """
    configured = get_settings().internal_api_key
    return bool(configured) and key == configured


def require_internal(x_internal_key: str | None = Header(default=None)) -> None:
    if not is_internal(x_internal_key):
        raise HTTPException(401, "invalid internal key")
