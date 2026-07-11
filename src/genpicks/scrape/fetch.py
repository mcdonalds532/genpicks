"""Rate-limited, cache-first HTTP fetching into the raw landing zone.

The cache is the contract: a URL is fetched at most once unless force=True,
and the saved file is exactly what the server returned. Backfills are
therefore resumable and re-parsing never touches the network.
"""

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "GenPicksBot/0.1 (portfolio project; contact: sli0433722618@gmail.com)"

RETRIABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """A URL could not be retrieved after retries."""


class Fetcher:
    def __init__(
        self,
        raw_root: Path,
        *,
        min_interval: float = 2.0,
        max_attempts: int = 3,
        user_agent: str = USER_AGENT,
        headers: dict[str, str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.raw_root = raw_root
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent, **(headers or {})},
            follow_redirects=True,
            timeout=30.0,
        )
        self._last_request_at = 0.0

    def get(self, url: str, cache_path: str, *, force: bool = False) -> str:
        """Return the body of `url`, reading from / writing to the raw store.

        cache_path is relative to raw_root, e.g. "rlp/seasons/nrl-2025-results.html".
        """
        target = self.raw_root / cache_path
        if target.exists() and not force:
            return target.read_text(encoding="utf-8")

        body = self._fetch(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(target)
        logger.info("fetched %s -> %s (%d bytes)", url, cache_path, len(body))
        return body

    def _fetch(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            try:
                response = self._client.get(url)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    return response.text
                if response.status_code not in RETRIABLE_STATUS:
                    raise FetchError(f"{url} returned {response.status_code}")
                last_error = FetchError(f"{url} returned {response.status_code}")
            time.sleep(2.0 * attempt)
        raise FetchError(f"{url} failed after {self.max_attempts} attempts") from last_error

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()
