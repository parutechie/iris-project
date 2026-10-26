"""
Signal Ingest Parser

Normalizes raw feed entries and produces structured signal
records ready for database loading.

Responsibilities
----------------
1. Parse publication dates to timezone-aware datetimes.
2. Classify each article into a signal type:
       commercial_transaction | logistics_purchase |
       brownfield_deal        | unknown
3. Extract location names mentioned in the article.
4. Geocode location names to EPSG:25832 point geometries
   using the Nominatim (OpenStreetMap) geocoding API.
5. Write the normalised records to disk.

Input  : <run>/raw/signal_ingest/signal_raw.json
Output : <run>/processed/signal_ingest/signals.json

Geocoding notes
---------------
- Nominatim is used because it is free and requires no API
  key, complying with the "lawful access only" requirement.
- Usage policy: max 1 request per second; a 1.1-second
  delay is enforced between geocoding calls.
- Coordinates are returned as WGS84 (EPSG:4326) by
  Nominatim and then projected to EPSG:25832 with pyproj.
- When multiple candidates are returned the first result
  is used and location_ambiguous is set to True.
- When no result is found the geometry fields remain None
  and location_notes records the reason.

IRIS-SIG-42
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer

from app.config.paths import DataPaths
from app.database.models.signal_ingest import (
    SIGNAL_TYPE_BROWNFIELD,
    SIGNAL_TYPE_COMMERCIAL,
    SIGNAL_TYPE_LOGISTICS,
    SIGNAL_TYPE_UNKNOWN,
)

logger = logging.getLogger(__name__)

# ==========================================================
# Projection helper
# ==========================================================

# WGS84 → EPSG:25832 (UTM zone 32N, Germany)
_WGS84_TO_UTM32 = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:25832",
    always_xy=True,
)


# ==========================================================
# Signal classification keywords
# ==========================================================

#: Keywords that indicate a commercial real-estate
#: transaction (buy/sell of industrial property).
_COMMERCIAL_KEYWORDS = [
    "erworben",         # acquired
    "kauft",            # buys
    "gekauft",          # bought
    "ankauf",           # acquisition
    "transaktion",      # transaction
    "verkauf",          # sale / sell
    "veräußert",        # divested
    "investiert",       # invests
    "investment",
    "mio. euro",        # monetary amount
    "millionen euro",
    "übernimmt",        # acquires / takes over
    "übernommen",
    "signing",
    "deal",
    "kaufpreis",        # purchase price
]

#: Keywords indicating a logistics purchase or
#: logistics infrastructure acquisition.
_LOGISTICS_KEYWORDS = [
    "spedition",        # haulage company
    "logistikzentrum",  # logistics centre
    "logistikimmobilie",
    "logistikhalle",    # logistics hall
    "logistikpark",
    "fulfillment",
    "umschlaghalle",    # transhipment hall
    "kontraktlogistik", # contract logistics
    "distributionszentrum",
    "lager",            # warehouse
    "lagerfläche",
    "supply chain",
    "freight",
    "transport",
]

#: Keywords indicating a brownfield / industrial redevelopment.
_BROWNFIELD_KEYWORDS = [
    "brownfield",
    "brachfläche",      # brownfield site (German)
    "industriebrache",  # industrial wasteland
    "brache",
    "revitalisierung",  # revitalisation
    "konversion",       # conversion
    "altlasten",        # contaminated land
    "ehemaligen industrieareal",  # former industrial area
    "gewerbegebiet",    # commercial/industrial zone
    "ehemaliges areal",
]

# ==========================================================
# Location extraction
# ==========================================================

#: German federal states and major NRW cities used as
#: candidate location strings to extract from text.
_LOCATION_HINTS = [
    # NRW cities (primary target region)
    "Dortmund",
    "Duisburg",
    "Düsseldorf",
    "Köln",
    "Cologne",
    "Essen",
    "Bochum",
    "Wuppertal",
    "Bielefeld",
    "Bonn",
    "Münster",
    "Aachen",
    "Gelsenkirchen",
    "Mönchengladbach",
    "Oberhausen",
    "Hamm",
    "Hagen",
    "Leverkusen",
    "Krefeld",
    "Solingen",
    "Osnabrück",
    "Paderborn",
    "Siegen",
    "Neuss",
    "Elsdorf",
    "Bergheim",
    # Major German cities (other states)
    "Berlin",
    "Hamburg",
    "München",
    "Munich",
    "Frankfurt",
    "Stuttgart",
    "Leipzig",
    "Bremen",
    "Hannover",
    "Nürnberg",
    "Dresden",
]


class SignalIngestParser:
    """
    Parses raw feed entries into normalised signal records.

    Parameters
    ----------
    paths
        DataPaths controlling the workspace.  Defaults to
        the standard ``data/`` directory.
    geocode_enabled
        When True (default) Nominatim geocoding is called
        for every extracted location.  Set to False during
        unit tests to avoid live HTTP calls.
    """

    def __init__(
        self,
        paths: DataPaths | None = None,
        geocode_enabled: bool = True,
    ):
        self.paths = paths or DataPaths()

        self.geocode_enabled = geocode_enabled

        # --------------------------------------------------
        # Input
        # --------------------------------------------------

        self.input_file = (
            self.paths.signal_raw / "signal_raw.json"
        )

        # --------------------------------------------------
        # Output
        # --------------------------------------------------

        self.output_dir = self.paths.signal_processed

        self.output_file = (
            self.output_dir / "signals.json"
        )

    # ======================================================
    # PUBLIC API
    # ======================================================

    def parse(self) -> list[dict]:
        """
        Load raw articles, normalise and classify each
        one, geocode locations, and write output to disk.

        Returns
        -------
        list[dict]
            The normalised signal records.
        """

        print("--------------------------------")
        print("Parsing signal ingest records...")

        if not self.input_file.exists():
            raise FileNotFoundError(
                "Signal raw input not found: "
                f"{self.input_file}"
            )

        with self.input_file.open(
            "r",
            encoding="utf-8",
        ) as handle:
            raw = json.load(handle)

        if not isinstance(raw, list):
            raise ValueError(
                "Expected a JSON list in "
                f"{self.input_file}"
            )

        signals = []

        for entry in raw:

            try:
                record = self._parse_entry(entry)
                signals.append(record)

            except Exception as exc:

                logger.warning(
                    "Failed to parse entry '%s': %s",
                    entry.get("title", "<no title>"),
                    exc,
                )

                signals.append(
                    self._error_record(entry, exc)
                )

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.output_file.open(
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                signals,
                handle,
                indent=4,
                ensure_ascii=False,
                default=str,
            )

        print("--------------------------------")

        types = {}

        for s in signals:
            t = s.get("signal_type", SIGNAL_TYPE_UNKNOWN)
            types[t] = types.get(t, 0) + 1

        for t, count in types.items():
            print(f"  {t}: {count}")

        print(f"Total Signals : {len(signals)}")
        print(self.output_file)

        return signals

    # ======================================================
    # PRIVATE: parse a single entry
    # ======================================================

    def _parse_entry(
        self,
        entry: dict,
    ) -> dict:
        """Normalise and classify a single feed entry."""

        title = (entry.get("title") or "").strip()
        summary = (entry.get("summary") or "").strip()
        url = (entry.get("link") or "").strip()
        source = (entry.get("source") or "Thomas Daily").strip()

        if not title:
            raise ValueError("Entry has no title")

        if not url:
            raise ValueError("Entry has no URL")

        # --------------------------------------------------
        # Publication date
        # --------------------------------------------------

        published_at = self._parse_date(
            entry.get("published")
        )

        # --------------------------------------------------
        # Signal classification
        # --------------------------------------------------

        signal_type = self._classify(title, summary)

        # --------------------------------------------------
        # Location extraction
        # --------------------------------------------------

        location_name = self._extract_location(
            title, summary
        )

        # --------------------------------------------------
        # Geocoding
        # --------------------------------------------------

        lat = None
        lon = None
        wkt = None
        resolved = False
        ambiguous = False
        notes = None

        if location_name:

            if self.geocode_enabled:

                lat, lon, resolved, ambiguous, notes = (
                    self._geocode(location_name)
                )

                if resolved and lat is not None:
                    wkt = self._to_wkt_25832(lat, lon)

            else:
                notes = "Geocoding disabled."

        return {
            "id": str(uuid.uuid4()),
            "source": source,
            "source_url": url,
            "title": title,
            "summary": summary or None,
            "published_at": (
                published_at.isoformat()
                if published_at
                else None
            ),
            "signal_type": signal_type,
            "location_name": location_name,
            "location_resolved": resolved,
            "location_ambiguous": ambiguous,
            "location_notes": notes,
            "latitude": lat,
            "longitude": lon,
            "geometry_wkt": wkt,
            "processed": False,
            "parse_error": None,
        }

    # ======================================================
    # PRIVATE: error record
    # ======================================================

    @staticmethod
    def _error_record(
        entry: dict,
        exc: Exception,
    ) -> dict:
        """Produce a minimal record that preserves the raw
        URL so the loader can deduplicate on re-run."""

        url = (entry.get("link") or "").strip()

        return {
            "id": str(uuid.uuid4()),
            "source": (
                entry.get("source") or "Thomas Daily"
            ),
            "source_url": url or f"unknown:{uuid.uuid4()}",
            "title": (
                entry.get("title") or "<parse error>"
            ),
            "summary": None,
            "published_at": None,
            "signal_type": SIGNAL_TYPE_UNKNOWN,
            "location_name": None,
            "location_resolved": False,
            "location_ambiguous": False,
            "location_notes": None,
            "latitude": None,
            "longitude": None,
            "geometry_wkt": None,
            "processed": False,
            "parse_error": f"{type(exc).__name__}: {exc}",
        }

    # ======================================================
    # PRIVATE: date parser
    # ======================================================

    @staticmethod
    def _parse_date(
        value: str | None,
    ) -> datetime | None:
        """
        Parse an RFC 2822 or ISO 8601 publication date.

        Returns None (rather than raising) for unparseable
        dates so records are not silently dropped.
        """

        if not value:
            return None

        value = value.strip()

        # RFC 2822 (most RSS feeds)
        try:
            dt = parsedate_to_datetime(value)
            return dt.astimezone(timezone.utc)

        except Exception:
            pass

        # ISO 8601 fallback
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt

            except ValueError:
                continue

        logger.warning(
            "Could not parse date: '%s'",
            value,
        )

        return None

    # ======================================================
    # PRIVATE: classification
    # ======================================================

    @staticmethod
    def _classify(
        title: str,
        summary: str,
    ) -> str:
        """
        Classify the article into one of the three target
        signal types using keyword matching.

        The classification priority is:
            1. brownfield_deal     (most specific)
            2. logistics_purchase  (operational asset)
            3. commercial_transaction (general deal)
            4. unknown             (no match)
        """

        text = (title + " " + summary).lower()

        if any(kw in text for kw in _BROWNFIELD_KEYWORDS):
            return SIGNAL_TYPE_BROWNFIELD

        if any(kw in text for kw in _LOGISTICS_KEYWORDS):
            return SIGNAL_TYPE_LOGISTICS

        if any(kw in text for kw in _COMMERCIAL_KEYWORDS):
            return SIGNAL_TYPE_COMMERCIAL

        return SIGNAL_TYPE_UNKNOWN

    # ======================================================
    # PRIVATE: location extraction
    # ======================================================

    @staticmethod
    def _extract_location(
        title: str,
        summary: str,
    ) -> str | None:
        """
        Return the first city name found in the text.

        The title is scanned before the summary so the most
        prominent location is preferred.
        """

        text = title + " " + summary

        for city in _LOCATION_HINTS:
            # word-boundary match to avoid partial hits
            pattern = rf"\b{re.escape(city)}\b"
            if re.search(pattern, text, re.IGNORECASE):
                return city

        return None

    # ======================================================
    # PRIVATE: geocoding (Nominatim)
    # ======================================================

    @staticmethod
    def _geocode(
        location_name: str,
    ) -> tuple[float | None, float | None, bool, bool, str | None]:
        """
        Resolve a location name to WGS84 coordinates via
        the Nominatim OpenStreetMap geocoding API.

        Parameters
        ----------
        location_name : str
            The place name to geocode.

        Returns
        -------
        tuple of (lat, lon, resolved, ambiguous, notes)
        """

        base_url = (
            "https://nominatim.openstreetmap.org/search"
        )

        params: dict[str, Any] = {
            "q": location_name + ", Germany",
            "format": "json",
            "limit": 3,
            "accept-language": "de",
        }

        headers = {
            "User-Agent": (
                "IRIS-SIG-42 signal ingest geocoder "
                "(lawful access, max 1 req/s)"
            )
        }

        try:
            # Nominatim usage policy: 1 request/second.
            time.sleep(1.1)

            response = requests.get(
                base_url,
                params=params,
                headers=headers,
                timeout=10,
            )

            response.raise_for_status()

            results = response.json()

        except requests.RequestException as exc:

            return (
                None,
                None,
                False,
                False,
                f"Geocoding request failed: {exc}",
            )

        except Exception as exc:

            return (
                None,
                None,
                False,
                False,
                f"Geocoding error: {exc}",
            )

        if not results:

            return (
                None,
                None,
                False,
                False,
                f"No geocoding result for '{location_name}'",
            )

        first = results[0]

        try:
            lat = float(first["lat"])
            lon = float(first["lon"])

        except (KeyError, ValueError) as exc:

            return (
                None,
                None,
                False,
                False,
                f"Invalid coordinates in response: {exc}",
            )

        ambiguous = len(results) > 1

        notes = None

        if ambiguous:
            candidates = "; ".join(
                r.get("display_name", "")[:80]
                for r in results
            )
            notes = (
                f"Ambiguous: {len(results)} candidates. "
                f"Used first. Others: {candidates}"
            )

        return lat, lon, True, ambiguous, notes

    # ======================================================
    # PRIVATE: project to EPSG:25832
    # ======================================================

    @staticmethod
    def _to_wkt_25832(
        lat: float,
        lon: float,
    ) -> str | None:
        """
        Convert WGS84 lat/lon to EPSG:25832 and return a
        WKT POINT string suitable for ST_GeomFromText.

        Invalid coordinates (outside UTM 32N coverage) are
        rejected and None is returned.
        """

        try:
            easting, northing = _WGS84_TO_UTM32.transform(
                lon, lat
            )

        except Exception as exc:

            logger.warning(
                "Projection failed for (%s, %s): %s",
                lat, lon, exc,
            )

            return None

        # Basic sanity check for Germany in UTM 32N
        if not (
            280_000 < easting < 920_000
            and 5_200_000 < northing < 6_100_000
        ):
            logger.warning(
                "Coordinates (%s, %s) → (%s, %s) "
                "fall outside expected Germany UTM 32N "
                "bounding box — geometry rejected.",
                lat, lon, easting, northing,
            )
            return None

        return f"SRID=25832;POINT({easting:.3f} {northing:.3f})"
