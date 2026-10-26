"""create iris_staging.signal_ingest

IRIS-SIG-42: Thomas Daily Morning News inbound webhook parser.

Creates the iris_staging schema and the signal_ingest staging
table with all required columns, constraints, and indexes.

Revision ID: c4f1a2d83e90
Revises: 722e96fc5617
Create Date: 2026-10-27 09:00:00.000000

"""

from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4f1a2d83e90"
down_revision: Union[str, Sequence[str], None] = "722e96fc5617"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create iris_staging schema and signal_ingest table."""

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    op.execute("CREATE SCHEMA IF NOT EXISTS iris_staging")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    op.create_table(
        "signal_ingest",
        # ----------------------------------------------------------
        # Primary key
        # ----------------------------------------------------------
        sa.Column(
            "id",
            sa.String(length=36),
            nullable=False,
            comment="UUID primary key",
        ),
        # ----------------------------------------------------------
        # Source information
        # ----------------------------------------------------------
        sa.Column(
            "source",
            sa.String(length=100),
            nullable=False,
            comment="Source identifier slug, e.g. thomas_daily",
        ),
        sa.Column(
            "source_url",
            sa.Text(),
            nullable=False,
            comment="Canonical article URL — stable dedup key",
        ),
        # ----------------------------------------------------------
        # Article content
        # ----------------------------------------------------------
        sa.Column(
            "title",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=True,
        ),
        # ----------------------------------------------------------
        # Publication date
        # ----------------------------------------------------------
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        # ----------------------------------------------------------
        # Signal classification
        # ----------------------------------------------------------
        sa.Column(
            "signal_type",
            sa.String(length=50),
            nullable=False,
            server_default="unknown",
            comment=(
                "commercial_transaction | "
                "logistics_purchase | "
                "brownfield_deal | "
                "unknown"
            ),
        ),
        # ----------------------------------------------------------
        # Geographic context
        # ----------------------------------------------------------
        sa.Column(
            "location_name",
            sa.String(length=255),
            nullable=True,
            comment="Raw location string extracted from article",
        ),
        sa.Column(
            "location_resolved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
            comment="True when geometry was successfully resolved",
        ),
        sa.Column(
            "location_ambiguous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
            comment="True when multiple candidate locations exist",
        ),
        sa.Column(
            "location_notes",
            sa.Text(),
            nullable=True,
            comment="Geocoding notes, error messages, or ambiguity details",
        ),
        sa.Column(
            "latitude",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "longitude",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=25832,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
            comment="Point geometry in EPSG:25832 (UTM zone 32N)",
        ),
        # ----------------------------------------------------------
        # Processing status
        # ----------------------------------------------------------
        sa.Column(
            "processed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
            comment="True after downstream processing is complete",
        ),
        sa.Column(
            "parse_error",
            sa.Text(),
            nullable=True,
            comment="Error message if parsing failed for this record",
        ),
        # ----------------------------------------------------------
        # Audit
        # ----------------------------------------------------------
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # ----------------------------------------------------------
        # Constraints
        # ----------------------------------------------------------
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_url",
            name="uq_signal_ingest_source_url",
        ),
        schema="iris_staging",
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    op.create_index(
        "idx_signal_ingest_signal_type",
        "signal_ingest",
        ["signal_type"],
        unique=False,
        schema="iris_staging",
    )

    op.create_index(
        "idx_signal_ingest_published_at",
        "signal_ingest",
        ["published_at"],
        unique=False,
        schema="iris_staging",
    )

    op.create_index(
        "idx_signal_ingest_source",
        "signal_ingest",
        ["source"],
        unique=False,
        schema="iris_staging",
    )

    op.create_index(
        "idx_signal_ingest_location_name",
        "signal_ingest",
        ["location_name"],
        unique=False,
        schema="iris_staging",
    )

    op.create_index(
        "idx_signal_ingest_geometry",
        "signal_ingest",
        ["geometry"],
        unique=False,
        schema="iris_staging",
        postgresql_using="gist",
    )

    op.create_index(
        "idx_signal_ingest_processed",
        "signal_ingest",
        ["processed"],
        unique=False,
        schema="iris_staging",
    )


def downgrade() -> None:
    """Drop signal_ingest table and iris_staging schema."""

    op.drop_index(
        "idx_signal_ingest_processed",
        table_name="signal_ingest",
        schema="iris_staging",
    )

    op.drop_index(
        "idx_signal_ingest_geometry",
        table_name="signal_ingest",
        schema="iris_staging",
        postgresql_using="gist",
    )

    op.drop_index(
        "idx_signal_ingest_location_name",
        table_name="signal_ingest",
        schema="iris_staging",
    )

    op.drop_index(
        "idx_signal_ingest_source",
        table_name="signal_ingest",
        schema="iris_staging",
    )

    op.drop_index(
        "idx_signal_ingest_published_at",
        table_name="signal_ingest",
        schema="iris_staging",
    )

    op.drop_index(
        "idx_signal_ingest_signal_type",
        table_name="signal_ingest",
        schema="iris_staging",
    )

    op.drop_table("signal_ingest", schema="iris_staging")

    op.execute("DROP SCHEMA IF EXISTS iris_staging CASCADE")
