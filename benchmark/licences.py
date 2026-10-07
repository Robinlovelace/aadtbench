"""Reviewed licence table for count sources.

A count source enters an open case only if it is listed here. Its licence is
taken from this table, never from the licence text that came with the data
and never from a default. Adding a source means checking its licence at the
publisher and recording where, when and who checked it.
"""
from __future__ import annotations

REVIEWED_SOURCES: dict[str, dict] = {
    "dft_manual": {
        "licence": "OGL-UK-3.0",
        "publisher": "Department for Transport, road traffic statistics (count point AADF)",
        "url": "https://roadtraffic.dft.gov.uk/downloads",
        "reviewed": "2026-10-07, OGL v3 as recorded with the data, publisher page check pending",
    },
    "dft_aadf": {
        "licence": "OGL-UK-3.0",
        "publisher": "Department for Transport, road traffic statistics (count point AADF)",
        "url": "https://roadtraffic.dft.gov.uk/downloads",
        "reviewed": "2026-10-07, OGL v3 as recorded with the data, publisher page check pending",
    },
    "oxflow": {
        "licence": "OGL-UK-3.0",
        "publisher": "Oxfordshire County Council traffic and active travel counters",
        "url": "https://www.oxfordshire.gov.uk (open data, OGL v3)",
        "reviewed": "2026-10-07, confirmed by Robin Lovelace (PR 17 review)",
    },
    "vic_dtp_aadt": {
        "licence": "CC-BY-4.0",
        "publisher": "Victoria Department of Transport and Planning, traffic volume",
        "url": "https://discover.data.vic.gov.au",
        "reviewed": "2026-10-07, CC BY 4.0 as recorded with the data, publisher page check pending",
    },
    "melbourne_ped": {
        "licence": "CC-BY-4.0",
        "publisher": "City of Melbourne pedestrian counting system",
        "url": "https://data.melbourne.vic.gov.au",
        "reviewed": "2026-10-07, CC BY 4.0 as recorded with the data, publisher page check pending",
    },
}

# Sources checked and found not open. Listed so the reason is on record.
REJECTED_SOURCES: dict[str, str] = {
    "wyca_tam": "WYCA traffic and active mode counts are not open data.",
    "leeds_footfall": "licence not confirmed as open with a source link.",
    "telraam": "CC BY-NC 4.0: only in cases labelled licence_class non_commercial (leuven-v1).",
    "vivacity": "local authority terms, check per authority.",
}


def reviewed_licence(source: str) -> tuple[str | None, str | None]:
    """Return (licence id, None) for a reviewed source, else (None, reason)."""
    if source in REVIEWED_SOURCES:
        return REVIEWED_SOURCES[source]["licence"], None
    return None, REJECTED_SOURCES.get(source, "source licence not reviewed")
