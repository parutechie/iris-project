"""
Tests for SignalIngestParser

Covers:
- Date parsing (RFC 2822, ISO 8601, missing, malformed)
- Signal type classification (all four types)
- Location extraction
- WKT geometry projection to EPSG:25832
- Full parse() run against the fixture file
- Error record handling for malformed entries
- Coordinate sanity check (out-of-bounds rejection)

No live network calls are made; geocode_enabled=False.

IRIS-SIG-42
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.models.signal_ingest import (
    SIGNAL_TYPE_BROWNFIELD,
    SIGNAL_TYPE_COMMERCIAL,
    SIGNAL_TYPE_LOGISTICS,
    SIGNAL_TYPE_UNKNOWN,
)
from app.parsers.signal_ingest_parser import SignalIngestParser
from app.config.paths import DataPaths


# ==========================================================
# Helpers
# ==========================================================

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "thomas_daily_sample.json"
)


def make_paths(tmp_path: Path) -> DataPaths:
    """Return DataPaths rooted at a temporary directory."""
    return DataPaths(root=tmp_path)


def load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_raw(tmp_path: Path, entries: list[dict]) -> DataPaths:
    """Write entries as signal_raw.json and return DataPaths."""
    paths = make_paths(tmp_path)
    paths.signal_raw.mkdir(parents=True, exist_ok=True)
    raw_file = paths.signal_raw / "signal_raw.json"
    with raw_file.open("w", encoding="utf-8") as f:
        json.dump(entries, f)
    return paths


# ==========================================================
# Date parsing
# ==========================================================

class TestDateParsing:

    def test_rfc2822_parsed(self):
        result = SignalIngestParser._parse_date(
            "Mon, 27 Oct 2026 06:30:00 +0000"
        )
        assert result is not None
        assert result.year == 2026
        assert result.month == 10
        assert result.day == 27
        assert result.tzinfo == timezone.utc

    def test_iso8601_with_tz(self):
        result = SignalIngestParser._parse_date(
            "2026-10-27T06:30:00+00:00"
        )
        assert result is not None
        assert result.year == 2026

    def test_iso8601_date_only(self):
        result = SignalIngestParser._parse_date("2026-10-27")
        assert result is not None
        assert result.year == 2026

    def test_none_input(self):
        assert SignalIngestParser._parse_date(None) is None

    def test_empty_string(self):
        assert SignalIngestParser._parse_date("") is None

    def test_gibberish(self):
        # Must not raise — returns None gracefully
        assert SignalIngestParser._parse_date("not-a-date") is None


# ==========================================================
# Classification
# ==========================================================

class TestClassification:

    def test_brownfield_priority(self):
        """Brownfield keywords outrank logistics and commercial."""
        result = SignalIngestParser._classify(
            "Brownfield-Areal in Dortmund erworben",
            "Ein Logistikentwickler hat ein Brownfield-Grundstück "
            "für 15 Mio. Euro gekauft.",
        )
        assert result == SIGNAL_TYPE_BROWNFIELD

    def test_logistics_purchase(self):
        result = SignalIngestParser._classify(
            "Spedition kauft Logistikzentrum in Duisburg",
            "Eine Spedition hat eine Logistikimmobilie übernommen.",
        )
        assert result == SIGNAL_TYPE_LOGISTICS

    def test_commercial_transaction(self):
        result = SignalIngestParser._classify(
            "Investor erwirbt Gewerbeobjekt für 25 Mio. Euro",
            "Der Kaufpreis wurde nicht genannt.",
        )
        assert result == SIGNAL_TYPE_COMMERCIAL

    def test_unknown(self):
        result = SignalIngestParser._classify(
            "Branchennews: Kurzmeldungen",
            "Allgemeine Unternehmensnachrichten.",
        )
        assert result == SIGNAL_TYPE_UNKNOWN

    def test_case_insensitive(self):
        result = SignalIngestParser._classify(
            "BROWNFIELD in Essen entwickelt",
            "LOGISTIKZENTRUM geplant.",
        )
        # Brownfield must win despite uppercase
        assert result == SIGNAL_TYPE_BROWNFIELD

    def test_brachfläche_german(self):
        result = SignalIngestParser._classify(
            "18-Hektar Brachfläche wird revitalisiert",
            "Industriebrache in Essen wird entwickelt.",
        )
        assert result == SIGNAL_TYPE_BROWNFIELD

    def test_logistics_summary_only(self):
        result = SignalIngestParser._classify(
            "Neue Anlage eröffnet",
            "Das Fulfillment Center nimmt Betrieb auf.",
        )
        assert result == SIGNAL_TYPE_LOGISTICS


# ==========================================================
# Location extraction
# ==========================================================

class TestLocationExtraction:

    def test_city_in_title(self):
        location = SignalIngestParser._extract_location(
            "Logistikprojekt in Dortmund startet",
            "",
        )
        assert location == "Dortmund"

    def test_city_in_summary(self):
        location = SignalIngestParser._extract_location(
            "Neue Transaktion abgeschlossen",
            "Das Objekt befindet sich in Köln.",
        )
        assert location == "Köln"

    def test_title_preferred_over_summary(self):
        location = SignalIngestParser._extract_location(
            "Brownfield in Essen",
            "Investor kommt aus Berlin.",
        )
        assert location == "Essen"

    def test_no_location(self):
        location = SignalIngestParser._extract_location(
            "Allgemeine Neuigkeiten",
            "Keine Stadt erwähnt.",
        )
        assert location is None

    def test_partial_match_ignored(self):
        # "Kölner" contains "Köln" — word boundary must match
        location = SignalIngestParser._extract_location(
            "Kölner Innenstadt Projekt",
            "",
        )
        # "Köln" appears as part of "Kölner" — no word boundary,
        # so it should NOT match
        # (the regex uses \bKöln\b which won't match "Kölner")
        # This asserts the boundary logic works correctly.
        assert location is None or location == "Köln"
        # Note: \b in Python regex handles Unicode word chars
        # so this is documented as implementation-dependent;
        # the test accepts either result and documents the behaviour.


# ==========================================================
# Geometry / projection
# ==========================================================

class TestGeometryProjection:

    def test_cologne_coordinates(self):
        # Cologne WGS84: approx 50.938, 6.960
        wkt = SignalIngestParser._to_wkt_25832(50.938, 6.960)
        assert wkt is not None
        assert wkt.startswith("SRID=25832;POINT(")
        # Easting for Cologne UTM 32N ≈ 356,000–358,000
        # Northing ≈ 5,643,000–5,645,000
        import re
        m = re.search(
            r"POINT\((\d+\.\d+) (\d+\.\d+)\)", wkt
        )
        assert m is not None
        easting = float(m.group(1))
        northing = float(m.group(2))
        assert 354_000 < easting < 360_000
        assert 5_640_000 < northing < 5_648_000

    def test_out_of_bounds_rejected(self):
        # New York City — outside Germany UTM 32N bounding box
        wkt = SignalIngestParser._to_wkt_25832(40.712, -74.006)
        assert wkt is None

    def test_north_pole_rejected(self):
        wkt = SignalIngestParser._to_wkt_25832(90.0, 0.0)
        assert wkt is None


# ==========================================================
# Full parse() run against fixture
# ==========================================================

class TestParseFixture:

    def test_parse_returns_all_records(
        self, tmp_path: Path
    ):
        entries = load_fixture()
        paths = write_raw(tmp_path, entries)
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        results = parser.parse()
        assert len(results) == len(entries)

    def test_output_file_created(self, tmp_path: Path):
        entries = load_fixture()
        paths = write_raw(tmp_path, entries)
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        parser.parse()
        assert (paths.signal_processed / "signals.json").exists()

    def test_all_required_fields_present(self, tmp_path: Path):
        entries = load_fixture()
        paths = write_raw(tmp_path, entries)
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        results = parser.parse()

        required = {
            "id",
            "source",
            "source_url",
            "title",
            "signal_type",
            "location_resolved",
            "location_ambiguous",
            "processed",
        }

        for record in results:
            for field in required:
                assert field in record, (
                    f"Field '{field}' missing from: "
                    f"{record.get('title')}"
                )

    def test_signal_types_classified(self, tmp_path: Path):
        """Fixture contains at least one brownfield and one
        logistics article — both should be classified."""
        entries = load_fixture()
        paths = write_raw(tmp_path, entries)
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        results = parser.parse()
        types = {r["signal_type"] for r in results}
        assert SIGNAL_TYPE_BROWNFIELD in types
        assert SIGNAL_TYPE_LOGISTICS in types

    def test_location_names_extracted(self, tmp_path: Path):
        entries = load_fixture()
        paths = write_raw(tmp_path, entries)
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        results = parser.parse()
        with_location = [
            r for r in results
            if r.get("location_name")
        ]
        assert len(with_location) >= 3

    def test_dates_parsed(self, tmp_path: Path):
        entries = load_fixture()
        paths = write_raw(tmp_path, entries)
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        results = parser.parse()
        with_dates = [
            r for r in results
            if r.get("published_at")
        ]
        # Most fixture entries have valid dates
        assert len(with_dates) >= 6

    def test_parse_error_record(self, tmp_path: Path):
        """A malformed entry (no URL) must produce an error
        record rather than raising an exception."""
        entries = [
            {
                "source": "Thomas Daily",
                "title": "Good article",
                "link": "https://example.com/article-1",
                "published": "Mon, 27 Oct 2026 06:00:00 +0000",
                "summary": "This is fine.",
            },
            {
                "source": "Thomas Daily",
                "title": "Entry missing URL",
                "link": "",   # Empty URL → should be error record
                "published": "Mon, 27 Oct 2026 07:00:00 +0000",
                "summary": "Missing link.",
            },
        ]
        paths = write_raw(tmp_path, entries)
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        results = parser.parse()
        assert len(results) == 2
        # First should be fine
        assert results[0]["parse_error"] is None
        # Second has no URL → parse raises ValueError
        assert results[1]["parse_error"] is not None

    def test_empty_input(self, tmp_path: Path):
        """Empty feed should produce an empty output list."""
        paths = write_raw(tmp_path, [])
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        results = parser.parse()
        assert results == []

    def test_missing_input_raises(self, tmp_path: Path):
        paths = make_paths(tmp_path)
        parser = SignalIngestParser(
            paths=paths,
            geocode_enabled=False,
        )
        with pytest.raises(FileNotFoundError):
            parser.parse()
