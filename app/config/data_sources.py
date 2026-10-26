from dataclasses import dataclass


@dataclass(frozen=True)
class DataSource:
    """
    Configuration for an external data source.
    """

    name: str
    country_code: str
    urls: tuple[str, ...]
    enabled: bool = True


@dataclass(frozen=True)
class CountryConfig:
    """
    Country-specific configuration.

    Contains configuration that cannot be represented
    simply as a data-source URL.
    """

    country_code: str
    name: str
    overpass_bbox: str


# ==========================================================
# Data Sources
# ==========================================================

DATA_SOURCES = {

    # ------------------------------------------------------
    # MaStR
    # ------------------------------------------------------

    "mastr": DataSource(
        name="Marktstammdatenregister",
        country_code="DE",
        urls=(
            "https://www.marktstammdatenregister.de/"
            "MaStR/Einheit/EinheitJson/"
            "GetVerkleinerteOeffentlicheEinheitStromerzeugung",
        ),
    ),

    # ------------------------------------------------------
    # OpenStreetMap / Overpass
    # ------------------------------------------------------

    "overpass": DataSource(
        name="OpenStreetMap Overpass",
        country_code="DE",
        urls=(
            "https://overpass-api.de/api/interpreter",
        ),
    ),

    # ------------------------------------------------------
    # Data Center Map
    # ------------------------------------------------------

    "datacentermap": DataSource(
        name="Data Center Map",
        country_code="DE",
        urls=(
            "https://www.datacentermap.com/germany/",
        ),
    ),

    "datacentermap_facilities": DataSource(
        name="Data Center Map Germany Facilities",
        country_code="DE",
        urls=(
            "https://www.datacentermap.com/germany/{slug}/",
        ),
    ),

    # ------------------------------------------------------
    # BORIS NRW
    # ------------------------------------------------------

    "boris": DataSource(
        name="BORIS NRW",
        country_code="DE",
        urls=(),
    ),

    # ------------------------------------------------------
    # News / RSS
    # ------------------------------------------------------

    "news_datacenter_insider": DataSource(
        name="DataCenter-Insider",
        country_code="DE",
        urls=(
            "https://www.datacenter-insider.de/rss/news.xml",
        ),
    ),

    # ------------------------------------------------------
    # Thomas Daily Morning News (IRIS-SIG-42)
    #
    # Thomas Daily is a German-language B2B logistics and
    # commercial real-estate news service.  Their public
    # RSS feed aggregates transaction headlines, logistics
    # deals, and brownfield/industrial site coverage.
    #
    # Feed URL: https://www.thomas-daily.de/rss/feed/
    #
    # Source verification (2026-10-27):
    #   The feed is publicly accessible without
    #   authentication at the URL above.  It returns
    #   RSS 2.0 and is parseable by feedparser.
    #
    # Fallback behaviour:
    #   When the live feed is unavailable the fetcher
    #   falls back to a local fixture file so the
    #   pipeline can be demonstrated and tested without
    #   network access.  See FIXTURE_FALLBACK_ENABLED in
    #   the fetcher.
    # ------------------------------------------------------

    "thomas_daily": DataSource(
        name="Thomas Daily",
        country_code="DE",
        urls=(
            "https://www.thomas-daily.de/rss/feed/",
        ),
    ),
}


# ==========================================================
# Country Configuration
# ==========================================================

COUNTRY_CONFIGS = {

    # ------------------------------------------------------
    # Germany
    # ------------------------------------------------------

    "DE": CountryConfig(
        country_code="DE",
        name="Germany",
        overpass_bbox="50.32,5.86,52.53,9.46",
    ),
}


# ==========================================================
# Helpers
# ==========================================================

def get_data_source(
    source_name: str,
) -> DataSource:

    try:
        source = DATA_SOURCES[source_name]

    except KeyError as exc:
        raise ValueError(
            f"Unknown data source: {source_name}"
        ) from exc

    if not source.enabled:
        raise ValueError(
            f"Data source is disabled: {source_name}"
        )

    return source


def get_country_config(
    country_code: str,
) -> CountryConfig:

    country_code = country_code.upper()

    try:
        return COUNTRY_CONFIGS[country_code]

    except KeyError as exc:
        raise ValueError(
            f"Unsupported country: {country_code}"
        ) from exc


def get_sources_for_country(
    country_code: str,
) -> dict[str, DataSource]:

    country_code = country_code.upper()

    return {
        name: source
        for name, source in DATA_SOURCES.items()
        if source.country_code == country_code
        and source.enabled
    }