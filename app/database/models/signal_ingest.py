"""
Signal Ingest Model

Staging table for inbound news signals extracted from
the Thomas Daily Morning News feed.

Each record represents a single commercial transaction
headline, logistics purchase, or brownfield deal signal
parsed from the source feed.

Schema  : iris_staging
Table   : signal_ingest
"""

from __future__ import annotations

from uuid import uuid4

from geoalchemy2 import Geometry

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from app.database.base import Base


# ==========================================================
# Signal Types
# ==========================================================

SIGNAL_TYPE_COMMERCIAL = "commercial_transaction"
SIGNAL_TYPE_LOGISTICS = "logistics_purchase"
SIGNAL_TYPE_BROWNFIELD = "brownfield_deal"
SIGNAL_TYPE_UNKNOWN = "unknown"

VALID_SIGNAL_TYPES = {
    SIGNAL_TYPE_COMMERCIAL,
    SIGNAL_TYPE_LOGISTICS,
    SIGNAL_TYPE_BROWNFIELD,
    SIGNAL_TYPE_UNKNOWN,
}


# ==========================================================
# Model
# ==========================================================


class SignalIngest(Base):
    """
    Staging record for a parsed news signal.

    The stable deduplication key is `source_url`.
    Re-running the ingestion pipeline will update
    existing records rather than insert duplicates.
    """

    __tablename__ = "signal_ingest"

    __table_args__ = (

        # --------------------------------------------------
        # Deduplication: one record per source URL
        # --------------------------------------------------

        UniqueConstraint(
            "source_url",
            name="uq_signal_ingest_source_url",
        ),

        # --------------------------------------------------
        # Indexes
        # --------------------------------------------------

        Index(
            "idx_signal_ingest_signal_type",
            "signal_type",
        ),

        Index(
            "idx_signal_ingest_published_at",
            "published_at",
        ),

        Index(
            "idx_signal_ingest_source",
            "source",
        ),

        Index(
            "idx_signal_ingest_location_name",
            "location_name",
        ),

        Index(
            "idx_signal_ingest_geometry",
            "geometry",
            postgresql_using="gist",
        ),

        Index(
            "idx_signal_ingest_processed",
            "processed",
        ),

        {
            "schema": "iris_staging",
        },
    )

    # ======================================================
    # Primary Key
    # ======================================================

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    # ======================================================
    # Source Information
    # ======================================================

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Source identifier slug, e.g. thomas_daily",
    )

    source_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Canonical article URL — stable dedup key",
    )

    # ======================================================
    # Article Content
    # ======================================================

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ======================================================
    # Publication
    # ======================================================

    published_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ======================================================
    # Signal Classification
    # ======================================================

    signal_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=SIGNAL_TYPE_UNKNOWN,
        comment=(
            "commercial_transaction | "
            "logistics_purchase | "
            "brownfield_deal | "
            "unknown"
        ),
    )

    # ======================================================
    # Geographic Context
    # ======================================================

    location_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Raw location string extracted from article",
    )

    location_resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True when geometry was successfully resolved",
    )

    location_ambiguous: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True when multiple candidate locations exist",
    )

    location_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Geocoding notes, error messages, or ambiguity details",
    )

    latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    geometry: Mapped[str | None] = mapped_column(
        Geometry(
            geometry_type="POINT",
            srid=25832,
            spatial_index=False,
        ),
        nullable=True,
        comment="Point geometry in EPSG:25832 (UTM zone 32N)",
    )

    # ======================================================
    # Processing Status
    # ======================================================

    processed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True after downstream processing is complete",
    )

    parse_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if parsing failed for this record",
    )

    # ======================================================
    # Audit
    # ======================================================

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
