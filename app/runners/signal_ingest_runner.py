"""
Signal Ingest Runner

Executes the full Thomas Daily Morning News ingestion
pipeline in three steps:

    1. Fetch   – download the RSS feed (or load fixture)
    2. Parse   – normalise, classify, and geocode records
    3. Load    – upsert records into iris_staging.signal_ingest

Can be called standalone (uses default data/ workspace) or
from PipelineRunner.run_all() with an isolated RunContext
DataPaths instance.

IRIS-SIG-42
"""

from __future__ import annotations

from app.config.paths import DataPaths
from app.commands.load_signal_ingest_command import (
    LoadSignalIngestCommand,
)
from app.database.session import SessionLocal
from app.parsers.signal_ingest_parser import SignalIngestParser
from app.scrapers.signal_ingest_fetcher import SignalIngestFetcher


def run(
    paths: DataPaths | None = None,
    geocode_enabled: bool = True,
) -> dict:
    """
    Run the complete signal ingest pipeline.

    Parameters
    ----------
    paths
        DataPaths controlling the workspace.  When called
        from ``PipelineRunner.run_all()`` the RunContext-
        specific paths are supplied here.
    geocode_enabled
        Pass False to skip live Nominatim geocoding
        (useful for tests and offline demos).

    Returns
    -------
    dict
        Summary from the loader with keys:
        ``inserted``, ``updated``, ``skipped``.
    """

    paths = paths or DataPaths()

    # --------------------------------------------------
    # Step 1: Fetch
    # --------------------------------------------------

    print("=" * 60)
    print("IRIS-SIG-42 | Signal Ingest Pipeline")
    print("=" * 60)

    print("\n[Step 1] Fetching Thomas Daily feed...")

    fetcher = SignalIngestFetcher(paths=paths)
    fetcher.fetch()

    # --------------------------------------------------
    # Step 2: Parse + classify + geocode
    # --------------------------------------------------

    print("\n[Step 2] Parsing and classifying signals...")

    parser = SignalIngestParser(
        paths=paths,
        geocode_enabled=geocode_enabled,
    )
    parser.parse()

    # --------------------------------------------------
    # Step 3: Load into PostgreSQL
    # --------------------------------------------------

    print("\n[Step 3] Loading into iris_staging.signal_ingest...")

    session = SessionLocal()

    try:

        command = LoadSignalIngestCommand(
            session,
            paths=paths,
        )

        result = command.execute()

    finally:

        session.close()

    print("\n" + "=" * 60)
    print("Signal Ingest Pipeline Completed")
    print("=" * 60)

    return result
