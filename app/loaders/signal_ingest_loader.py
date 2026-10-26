"""
Signal Ingest Loader

Loads normalised signal records from disk into the
iris_staging.signal_ingest PostgreSQL table.

Idempotency guarantee
---------------------
Source URL (source_url) is the stable deduplication key.

- On the first run a record is inserted.
- On subsequent runs the existing record is updated in place:
  title, summary, published_at, signal_type, location fields
  and geometry are refreshed.
- Duplicate records are never created regardless of how many
  times the pipeline is executed.

Error handling
--------------
- If a record is missing source_url it is skipped and
  counted as skipped rather than raising.
- A database error triggers a full session rollback so
  partial writes do not leave the table in an inconsistent
  state.

IRIS-SIG-42
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.paths import DataPaths
from app.database.models.signal_ingest import (
    SIGNAL_TYPE_UNKNOWN,
    SignalIngest,
)

logger = logging.getLogger(__name__)


class SignalIngestLoader:
    """
    Loads ``signals.json`` into ``iris_staging.signal_ingest``.

    Parameters
    ----------
    session
        An open SQLAlchemy session.
    paths
        DataPaths controlling the workspace.
    """

    def __init__(
        self,
        session: Session,
        paths: DataPaths | None = None,
    ):
        self.session = session

        self.paths = paths or DataPaths()

        self.input_file = (
            self.paths.signal_processed / "signals.json"
        )

    # ======================================================
    # PUBLIC API
    # ======================================================

    def execute(self) -> dict:
        """
        Load all signal records and return a summary dict.

        Returns
        -------
        dict with keys:
            inserted – number of new records
            updated  – number of records refreshed
            skipped  – records missing required fields
        """

        print("--------------------------------")
        print("Loading Signal Ingest records...")

        records = self._load_json(self.input_file)

        print(f"Records in file : {len(records)}")

        inserted = 0
        updated = 0
        skipped = 0

        try:

            for data in records:

                result = self._upsert(data)

                if result == "inserted":
                    inserted += 1
                elif result == "updated":
                    updated += 1
                else:
                    skipped += 1

            self.session.commit()

        except Exception:

            self.session.rollback()

            raise

        print("--------------------------------")
        print(f"Inserted : {inserted}")
        print(f"Updated  : {updated}")
        print(f"Skipped  : {skipped}")
        print("Signal Ingest Loaded Successfully")

        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
        }

    # ======================================================
    # PRIVATE: upsert
    # ======================================================

    def _upsert(
        self,
        data: dict,
    ) -> str:
        """
        Insert or update a single signal record.

        Returns ``"inserted"``, ``"updated"``, or ``"skipped"``.
        """

        source_url = (data.get("source_url") or "").strip()

        if not source_url:

            logger.warning(
                "Skipping record with no source_url: %s",
                data.get("title"),
            )

            return "skipped"

        existing = self.session.scalar(
            select(SignalIngest)
            .where(SignalIngest.source_url == source_url)
        )

        # --------------------------------------------------
        # Geometry
        # --------------------------------------------------

        geometry = self._build_geometry(
            data.get("geometry_wkt")
        )

        # --------------------------------------------------
        # Shared fields
        # --------------------------------------------------

        fields = dict(
            source=data.get("source", "Thomas Daily"),
            title=data.get("title", ""),
            summary=data.get("summary"),
            published_at=self._parse_dt(
                data.get("published_at")
            ),
            signal_type=data.get(
                "signal_type",
                SIGNAL_TYPE_UNKNOWN,
            ),
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
            geometry=geometry,
            processed=bool(data.get("processed", False)),
            parse_error=data.get("parse_error"),
        )

        # --------------------------------------------------
        # Update
        # --------------------------------------------------

        if existing:

            for attr, value in fields.items():
                setattr(existing, attr, value)

            return "updated"

        # --------------------------------------------------
        # Insert
        # --------------------------------------------------

        record = SignalIngest(
            id=data.get("id") or None,
            source_url=source_url,
            **fields,
        )

        self.session.add(record)

        return "inserted"

    # ======================================================
    # PRIVATE: helpers
    # ======================================================

    @staticmethod
    def _load_json(file: Path) -> list:

        if not file.exists():
            raise FileNotFoundError(
                f"Signal ingest input not found:\n{file}"
            )

        with file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, list):
            raise ValueError(
                f"Expected a JSON list in {file}"
            )

        return data

    @staticmethod
    def _parse_dt(value: str | None):
        """Parse an ISO 8601 datetime string, return None on failure."""

        if not value:
            return None

        from datetime import datetime, timezone

        for fmt in (
            "%Y-%m-%dT%H:%M:%S+00:00",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt

            except ValueError:
                continue

        logger.warning("Could not parse datetime: '%s'", value)
        return None

    @staticmethod
    def _build_geometry(
        wkt: str | None,
    ):
        """
        Convert a WKT SRID-prefixed string into a
        GeoAlchemy2 WKTElement.

        Expected format:  SRID=25832;POINT(x y)
        """

        if not wkt:
            return None

        try:
            # Strip SRID prefix if present; WKTElement
            # accepts the full 'SRID=25832;POINT(...)' form.
            return WKTElement(wkt, srid=25832)

        except Exception as exc:

            logger.warning(
                "Could not build geometry from WKT '%s': %s",
                wkt,
                exc,
            )

            return None
