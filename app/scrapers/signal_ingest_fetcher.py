"""
Signal Ingest Fetcher

Downloads the Thomas Daily RSS feed and saves the raw
articles to disk as a JSON file for the downstream parser.

Source
------
Thomas Daily (https://www.thomas-daily.de) is a German-
language B2B news service covering commercial real-estate
transactions, logistics property deals, and brownfield
development projects.  Their RSS feed at:

    https://www.thomas-daily.de/rss/feed/

publishes new entries every morning and is publicly
accessible without authentication.

Fallback behaviour
------------------
If the live feed is unreachable (network error, HTTP error,
empty response) and FIXTURE_FALLBACK_ENABLED is True the
fetcher loads a representative fixture file so the pipeline
can run and be demonstrated offline.

DataPaths controls the output workspace so each pipeline
run remains isolated.

IRIS-SIG-42
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import feedparser
import requests

from app.config.data_sources import get_data_source
from app.config.paths import DataPaths

logger = logging.getLogger(__name__)

# ----------------------------------------------------------
# Module-level constants
# ----------------------------------------------------------

SOURCE_KEY = "thomas_daily"

#: Path to the bundled sample fixture used when the live
#: feed cannot be reached (relative to this file).
_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "thomas_daily_sample.json"
)

#: When True the fetcher falls back to the fixture file
#: instead of raising an error on network failure.
FIXTURE_FALLBACK_ENABLED: bool = True

#: HTTP request timeout in seconds.
REQUEST_TIMEOUT: int = 15


class SignalIngestFetcher:
    """
    Downloads the Thomas Daily RSS feed.

    Input  : live RSS feed (or fixture fallback)
    Output : <run>/raw/signal_ingest/signal_raw.json

    Each entry in the output list contains:
        source     – source slug
        title      – article headline
        link       – canonical article URL
        published  – RFC 2822 publication date string
        summary    – article excerpt / description
    """

    def __init__(
        self,
        paths: DataPaths | None = None,
    ):
        self.paths = paths or DataPaths()

        self.source = get_data_source(SOURCE_KEY)

        # --------------------------------------------------
        # Output
        # --------------------------------------------------

        self.output_dir = self.paths.signal_raw

        self.output_file = (
            self.output_dir / "signal_raw.json"
        )

    # ======================================================
    # PUBLIC API
    # ======================================================

    def fetch(self) -> list[dict]:
        """
        Fetch the RSS feed, save raw entries to disk,
        and return the list of raw article dicts.

        Raises
        ------
        RuntimeError
            When the live feed fails and the fixture
            fallback is disabled.
        """

        print("--------------------------------")
        print("Fetching Thomas Daily RSS feed...")

        if not self.source.urls:
            raise ValueError(
                f"No URL configured for source: "
                f"{self.source.name}"
            )

        url = self.source.urls[0]

        print(f"URL    : {url}")

        articles = self._fetch_live(url)

        if not articles:

            logger.warning(
                "Live feed returned no entries for %s",
                url,
            )

            if FIXTURE_FALLBACK_ENABLED:

                print(
                    "Live feed empty or unreachable — "
                    "loading fixture fallback."
                )

                articles = self._load_fixture()

            else:

                raise RuntimeError(
                    f"Live feed returned no entries: {url}"
                )

        self._save(articles)

        print("--------------------------------")
        print(
            f"Articles Fetched : {len(articles)}"
        )
        print(self.output_file)

        return articles

    # ======================================================
    # PRIVATE: live fetch
    # ======================================================

    def _fetch_live(
        self,
        url: str,
    ) -> list[dict]:
        """
        Attempt to retrieve the RSS feed.

        Returns an empty list (rather than raising) on any
        network-level error so the caller can apply the
        fallback policy.
        """

        try:

            # feedparser will follow redirects; pass a
            # pre-fetched response to honour our timeout.

            response = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": (
                        "IRIS-SIG-42 signal ingest / "
                        "feedparser"
                    ),
                },
            )

            response.raise_for_status()

            feed = feedparser.parse(response.content)

        except requests.RequestException as exc:

            logger.warning(
                "Network error fetching %s: %s",
                url,
                exc,
            )

            return []

        except Exception as exc:

            logger.warning(
                "Unexpected error parsing feed %s: %s",
                url,
                exc,
            )

            return []

        if feed.bozo and not feed.entries:

            logger.warning(
                "Feed parse error for %s: %s",
                url,
                feed.bozo_exception,
            )

            return []

        articles = []

        for entry in feed.entries:

            articles.append(
                self._normalize_entry(entry)
            )

        return articles

    # ======================================================
    # PRIVATE: fixture fallback
    # ======================================================

    def _load_fixture(self) -> list[dict]:
        """
        Load the bundled sample fixture.

        This allows the pipeline to run and be tested
        without live network access.
        """

        if not _FIXTURE_PATH.exists():

            raise FileNotFoundError(
                "Fixture file not found: "
                f"{_FIXTURE_PATH}\n"
                "Set FIXTURE_FALLBACK_ENABLED=False or "
                "create the fixture file."
            )

        with _FIXTURE_PATH.open(
            "r",
            encoding="utf-8",
        ) as handle:

            data = json.load(handle)

        if not isinstance(data, list):

            raise ValueError(
                "Fixture must be a JSON list: "
                f"{_FIXTURE_PATH}"
            )

        logger.info(
            "Loaded %d articles from fixture %s",
            len(data),
            _FIXTURE_PATH,
        )

        return data

    # ======================================================
    # PRIVATE: entry normalizer
    # ======================================================

    @staticmethod
    def _normalize_entry(
        entry,
    ) -> dict:
        """
        Convert a feedparser entry into a plain dict with
        the canonical field names used by the parser.
        """

        return {
            "source": "Thomas Daily",

            "title": (
                entry.get("title") or ""
            ).strip(),

            "link": (
                entry.get("link") or ""
            ).strip(),

            "published": (
                entry.get("published")
                or entry.get("updated")
                or ""
            ),

            "summary": (
                entry.get("summary")
                or entry.get("description")
                or ""
            ).strip(),
        }

    # ======================================================
    # PRIVATE: save
    # ======================================================

    def _save(
        self,
        articles: list[dict],
    ) -> None:
        """Persist raw articles to disk."""

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.output_file.open(
            "w",
            encoding="utf-8",
        ) as handle:

            json.dump(
                articles,
                handle,
                indent=4,
                ensure_ascii=False,
            )
