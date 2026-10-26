"""
Load Signal Ingest Command

Thin command wrapper around SignalIngestLoader.
Follows the Command pattern used throughout the pipeline.

IRIS-SIG-42
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config.paths import DataPaths
from app.loaders.signal_ingest_loader import SignalIngestLoader


class LoadSignalIngestCommand:
    """
    Loads normalised signal records into PostgreSQL.

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
        self.loader = SignalIngestLoader(
            session,
            paths=paths,
        )

    def execute(self) -> dict:
        """Execute the load and return a summary dict."""

        return self.loader.execute()
