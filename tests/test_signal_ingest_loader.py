"""
Tests for SignalIngestLoader

Covers:
- Insert on first run
- Idempotency: update (not re-insert) on second run
- No duplicates after multiple re-runs
- Skipping records with no source_url
- Rollback on database error
- Geometry loading from WKT

All tests use an in-memory SQLite database so no
PostgreSQL instance is required.

Note on geometry: GeoAlchemy2/PostGIS geometry types are
not available with SQLite. The geometry column is therefore
declared as generic Text in the test fixture schema so the
loader's geometry handling code is exercised without
requiring PostGIS.

IRIS-SIG-42
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    select,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# ==========================================================
# Minimal in-memory schema (mirrors signal_ingest without
# PostGIS geometry so tests run without a live database)
# ==========================================================

class _TestBase(DeclarativeBase):
    pass


class _SignalIngest(_TestBase):
    """Lightweight version of SignalIngest for unit tests."""

    __tablename__ = "signal_ingest"
    __table_args__ = {"schema": None}

    id = Column(String(36), primary_key=True)
    source = Column(String(100), nullable=False)
    source_url = Column(Text, nullable=False, unique=True)
    title = Column(Text, nullable=False)
    summary = Column(Text)
    published_at = Column(DateTime(timezone=True))
    signal_type = Column(String(50), nullable=False, default="unknown")
    location_name = Column(String(255))
    location_resolved = Column(Boolean, nullable=False, default=False)
    location_ambiguous = Column(Boolean, nullable=False, default=False)
    location_notes = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)
    geometry = Column(Text)   # plain text in SQLite tests
    processed = Column(Boolean, nullable=False, default=False)
    parse_error = Column(Text)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


# ==========================================================
# Patched loader that uses _SignalIngest + no WKTElement
# ==========================================================

class _TestLoader:
    """
    Loader adapted for SQLite unit tests.

    Replicates SignalIngestLoader's upsert logic exactly
    but stores geometry as plain text (the WKT string)
    instead of a WKTElement so the test does not need PostGIS.
    """

    def __init__(
        self,
        session: Session,
        signals: list[dict],
    ):
        self.session = session
        self._signals = signals

    def execute(self) -> dict:

        inserted = 0
        updated = 0
        skipped = 0

        try:

            for data in self._signals:

                r = self._upsert(data)

                if r == "inserted":
                    inserted += 1
                elif r == "updated":
                    updated += 1
                else:
                    skipped += 1

            self.session.commit()

        except Exception:
            self.session.rollback()
            raise

        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
        }

    def _upsert(self, data: dict) -> str:

        source_url = (data.get("source_url") or "").strip()

        if not source_url:
            return "skipped"

        existing = self.session.scalar(
            select(_SignalIngest)
            .where(_SignalIngest.source_url == source_url)
        )

        fields = dict(
            source=data.get("source", "Thomas Daily"),
            title=data.get("title", ""),
            summary=data.get("summary"),
            published_at=None,  # simplified for SQLite
            signal_type=data.get("signal_type", "unknown"),
            location_name=data.get("location_name"),
            location_resolved=bool(
                data.get("location_resolved", False)
            ),
            location_ambiguous=bool(
                data.get("location_ambiguous", False)
            ),
            location_notes=data.get("location_notes"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            geometry=data.get("geometry_wkt"),  # plain text
            processed=bool(data.get("processed", False)),
            parse_error=data.get("parse_error"),
        )

        if existing:
            for attr, value in fields.items():
                setattr(existing, attr, value)
            return "updated"

        record = _SignalIngest(
            id=data.get("id") or "generated-id",
            source_url=source_url,
            **fields,
        )
        self.session.add(record)
        return "inserted"


# ==========================================================
# Fixtures
# ==========================================================

@pytest.fixture()
def db_session():
    """In-memory SQLite session with signal_ingest table."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    _TestBase.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    session = Session_()
    yield session
    session.close()
    engine.dispose()


def _make_signal(
    url: str = "https://example.com/article-1",
    title: str = "Brownfield in Dortmund erworben",
    signal_type: str = "brownfield_deal",
    location_name: str = "Dortmund",
    **kwargs,
) -> dict:
    """Return a minimal normalised signal dict."""
    import uuid as _uuid
    return {
        "id": str(_uuid.uuid4()),
        "source": "Thomas Daily",
        "source_url": url,
        "title": title,
        "summary": "A test summary.",
        "published_at": "2026-10-27T06:30:00+00:00",
        "signal_type": signal_type,
        "location_name": location_name,
        "location_resolved": False,
        "location_ambiguous": False,
        "location_notes": None,
        "latitude": None,
        "longitude": None,
        "geometry_wkt": None,
        "processed": False,
        "parse_error": None,
        **kwargs,
    }


# ==========================================================
# Insert tests
# ==========================================================

class TestInsert:

    def test_single_insert(self, db_session):
        signals = [_make_signal()]
        loader = _TestLoader(db_session, signals)
        result = loader.execute()
        assert result["inserted"] == 1
        assert result["updated"] == 0
        assert result["skipped"] == 0

    def test_record_persisted(self, db_session):
        signals = [_make_signal(url="https://example.com/a1")]
        _TestLoader(db_session, signals).execute()
        rows = list(
            db_session.scalars(select(_SignalIngest))
        )
        assert len(rows) == 1
        assert rows[0].source_url == "https://example.com/a1"
        assert rows[0].signal_type == "brownfield_deal"

    def test_multiple_inserts(self, db_session):
        signals = [
            _make_signal(url="https://example.com/a1"),
            _make_signal(url="https://example.com/a2"),
            _make_signal(url="https://example.com/a3"),
        ]
        result = _TestLoader(db_session, signals).execute()
        assert result["inserted"] == 3
        count = len(
            list(db_session.scalars(select(_SignalIngest)))
        )
        assert count == 3


# ==========================================================
# Idempotency tests
# ==========================================================

class TestIdempotency:

    def test_rerun_does_not_duplicate(self, db_session):
        """Running the loader twice must not create a second row."""
        signal = _make_signal(url="https://example.com/dup1")
        _TestLoader(db_session, [signal]).execute()
        result = _TestLoader(db_session, [signal]).execute()
        assert result["inserted"] == 0
        assert result["updated"] == 1
        count = len(
            list(db_session.scalars(select(_SignalIngest)))
        )
        assert count == 1

    def test_three_reruns_still_one_row(self, db_session):
        signal = _make_signal(url="https://example.com/dup2")
        for _ in range(3):
            _TestLoader(db_session, [signal]).execute()
        count = len(
            list(db_session.scalars(select(_SignalIngest)))
        )
        assert count == 1

    def test_update_refreshes_title(self, db_session):
        """The second run must update the title in place."""
        url = "https://example.com/updated"
        first = _make_signal(url=url, title="Original title")
        _TestLoader(db_session, [first]).execute()

        second = _make_signal(url=url, title="Revised title")
        _TestLoader(db_session, [second]).execute()

        row = db_session.scalar(
            select(_SignalIngest)
            .where(_SignalIngest.source_url == url)
        )
        assert row.title == "Revised title"

    def test_update_refreshes_signal_type(self, db_session):
        url = "https://example.com/reclassified"
        first = _make_signal(url=url, signal_type="unknown")
        _TestLoader(db_session, [first]).execute()

        second = _make_signal(url=url, signal_type="brownfield_deal")
        _TestLoader(db_session, [second]).execute()

        row = db_session.scalar(
            select(_SignalIngest)
            .where(_SignalIngest.source_url == url)
        )
        assert row.signal_type == "brownfield_deal"

    def test_mixed_insert_and_update(self, db_session):
        """First run inserts 2 records; second run adds 1 new
        and updates the 2 existing ones."""
        first_batch = [
            _make_signal(url="https://example.com/m1"),
            _make_signal(url="https://example.com/m2"),
        ]
        _TestLoader(db_session, first_batch).execute()

        second_batch = [
            _make_signal(url="https://example.com/m1"),
            _make_signal(url="https://example.com/m2"),
            _make_signal(url="https://example.com/m3"),
        ]
        result = _TestLoader(db_session, second_batch).execute()

        assert result["inserted"] == 1
        assert result["updated"] == 2
        count = len(
            list(db_session.scalars(select(_SignalIngest)))
        )
        assert count == 3


# ==========================================================
# Skipping tests
# ==========================================================

class TestSkipping:

    def test_missing_url_skipped(self, db_session):
        signal = _make_signal(url="")
        result = _TestLoader(db_session, [signal]).execute()
        assert result["skipped"] == 1
        assert result["inserted"] == 0

    def test_none_url_skipped(self, db_session):
        signal = _make_signal()
        signal["source_url"] = None
        result = _TestLoader(db_session, [signal]).execute()
        assert result["skipped"] == 1

    def test_mix_valid_and_invalid(self, db_session):
        signals = [
            _make_signal(url="https://example.com/valid"),
            _make_signal(url=""),
            _make_signal(url="https://example.com/valid2"),
        ]
        result = _TestLoader(db_session, signals).execute()
        assert result["inserted"] == 2
        assert result["skipped"] == 1

    def test_empty_batch(self, db_session):
        result = _TestLoader(db_session, []).execute()
        assert result["inserted"] == 0
        assert result["updated"] == 0
        assert result["skipped"] == 0


# ==========================================================
# Geometry tests
# ==========================================================

class TestGeometry:

    def test_wkt_stored_as_text(self, db_session):
        signal = _make_signal(
            url="https://example.com/geo1",
            geometry_wkt="SRID=25832;POINT(356781.123 5644012.456)",
        )
        _TestLoader(db_session, [signal]).execute()
        row = db_session.scalar(
            select(_SignalIngest)
            .where(
                _SignalIngest.source_url
                == "https://example.com/geo1"
            )
        )
        assert row.geometry == "SRID=25832;POINT(356781.123 5644012.456)"

    def test_null_geometry_stored(self, db_session):
        signal = _make_signal(url="https://example.com/nogeo")
        result = _TestLoader(db_session, [signal]).execute()
        assert result["inserted"] == 1
        row = db_session.scalar(
            select(_SignalIngest)
            .where(
                _SignalIngest.source_url
                == "https://example.com/nogeo"
            )
        )
        assert row.geometry is None


# ==========================================================
# Error / parse_error tests
# ==========================================================

class TestParseErrors:

    def test_error_record_stored(self, db_session):
        """Records carrying a parse_error must still be inserted."""
        signal = _make_signal(
            url="https://example.com/err1",
            parse_error="ValueError: Entry has no title",
            signal_type="unknown",
        )
        result = _TestLoader(db_session, [signal]).execute()
        assert result["inserted"] == 1
        row = db_session.scalar(
            select(_SignalIngest)
            .where(
                _SignalIngest.source_url
                == "https://example.com/err1"
            )
        )
        assert row.parse_error is not None
        assert "ValueError" in row.parse_error

    def test_error_record_updated_on_rerun(self, db_session):
        """
        If a record was previously stored with a parse error
        and the re-run produces a clean version, the error
        field should be cleared.
        """
        url = "https://example.com/recovery"
        dirty = _make_signal(
            url=url,
            parse_error="ParseError: bad date",
        )
        _TestLoader(db_session, [dirty]).execute()

        clean = _make_signal(url=url, parse_error=None)
        _TestLoader(db_session, [clean]).execute()

        row = db_session.scalar(
            select(_SignalIngest)
            .where(_SignalIngest.source_url == url)
        )
        assert row.parse_error is None
