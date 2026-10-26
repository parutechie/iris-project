"""
Signal Ingest Repository

Query layer for the iris_staging.signal_ingest table.

All methods return plain SQLAlchemy model instances.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models.signal_ingest import (
    SignalIngest,
)


class SignalIngestRepository:

    def __init__(
        self,
        session: Session,
    ):
        self.session = session

    # =====================================================
    # Fetch by PK / URL
    # =====================================================

    def get(
        self,
        signal_id: str,
    ) -> SignalIngest | None:
        """Return a single record by primary key."""

        return self.session.get(
            SignalIngest,
            signal_id,
        )

    # -----------------------------------------------------

    def get_by_url(
        self,
        source_url: str,
    ) -> SignalIngest | None:
        """
        Return the record whose source_url matches.

        source_url is the stable deduplication key.
        """

        return self.session.scalar(
            select(SignalIngest)
            .where(
                SignalIngest.source_url == source_url
            )
        )

    # =====================================================
    # List queries
    # =====================================================

    def get_all(self) -> list[SignalIngest]:
        """Return all records ordered by publication date."""

        return list(
            self.session.scalars(
                select(SignalIngest)
                .order_by(
                    SignalIngest.published_at.desc()
                )
            )
        )

    # -----------------------------------------------------

    def get_by_signal_type(
        self,
        signal_type: str,
    ) -> list[SignalIngest]:
        """Return records filtered by signal_type."""

        return list(
            self.session.scalars(
                select(SignalIngest)
                .where(
                    SignalIngest.signal_type == signal_type
                )
                .order_by(
                    SignalIngest.published_at.desc()
                )
            )
        )

    # -----------------------------------------------------

    def get_recent(
        self,
        limit: int = 50,
    ) -> list[SignalIngest]:
        """Return the most recently published records."""

        return list(
            self.session.scalars(
                select(SignalIngest)
                .order_by(
                    SignalIngest.published_at.desc()
                )
                .limit(limit)
            )
        )

    # -----------------------------------------------------

    def get_unprocessed(self) -> list[SignalIngest]:
        """Return records that have not yet been processed."""

        return list(
            self.session.scalars(
                select(SignalIngest)
                .where(
                    SignalIngest.processed.is_(False)
                )
                .order_by(
                    SignalIngest.published_at.asc()
                )
            )
        )

    # -----------------------------------------------------

    def get_with_geometry(self) -> list[SignalIngest]:
        """Return records that have a resolved geometry."""

        return list(
            self.session.scalars(
                select(SignalIngest)
                .where(
                    SignalIngest.location_resolved.is_(True)
                )
                .order_by(
                    SignalIngest.published_at.desc()
                )
            )
        )

    # -----------------------------------------------------

    def get_with_errors(self) -> list[SignalIngest]:
        """Return records that have a parse_error set."""

        return list(
            self.session.scalars(
                select(SignalIngest)
                .where(
                    SignalIngest.parse_error.is_not(None)
                )
            )
        )

    # =====================================================
    # Counts
    # =====================================================

    def count(self) -> int:
        """Total number of staged records."""

        return len(self.get_all())

    # -----------------------------------------------------

    def count_by_signal_type(
        self,
        signal_type: str,
    ) -> int:
        """Count records for a specific signal type."""

        return len(
            self.get_by_signal_type(signal_type)
        )
