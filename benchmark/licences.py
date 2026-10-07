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
    "leeds_footfall": {
        "licence": "OGL-UK-3.0",
        "publisher": "Leeds City Council, city centre footfall cameras (Data Mill North)",
        "url": "https://datamillnorth.org/dataset/leeds-city-centre-footfall-2kx4d",
        "reviewed": "2026-10-08, Open Government Licence v3 shown on the dataset page",
    },
    "stadt_zuerich_miv": {
        "licence": "CC0-1.0",
        "publisher": "Stadt Zuerich, motorised traffic counts (all motor vehicles)",
        "url": "https://data.stadt-zuerich.ch",
        "reviewed": "2026-10-08, CC0 per the dataset page, as recorded by the data porting step, recheck pending",
    },
    "stadt_zuerich_fuss_velo": {
        "licence": "CC0-1.0",
        "publisher": "Stadt Zuerich, automatic pedestrian and bicycle counts",
        "url": "https://data.stadt-zuerich.ch",
        "reviewed": "2026-10-08, CC0 per the dataset page, as recorded by the data porting step, recheck pending",
    },
    **{src: {
        "licence": "OGL-Toronto",
        "publisher": f"City of Toronto open data ({what})",
        "url": "https://open.toronto.ca",
        "reviewed": "2026-10-08, Open Government Licence Toronto as recorded with the data, recheck pending",
    } for src, what in (("toronto_tmc", "turning movement counts"), ("toronto_svc", "speed and volume counts"),
                        ("toronto_bike", "permanent bicycle counters"))},
}

# Non-commercial sources, allowed only in cases with licence_class non_commercial.
NON_COMMERCIAL_SOURCES: dict[str, dict] = {
    "telraam": {
        "licence": "CC-BY-NC-4.0",
        "publisher": "Telraam citizen traffic sensors",
        "url": "https://faq.telraam.net/article/9/telraam-data-license-what-can-i-do-with-the-telraam-data",
        "reviewed": "2026-10-07, CC BY-NC 4.0 per Telraam FAQ, accepted for this non-commercial benchmark by Robin Lovelace",
    },
}

# Sources checked and found not open. Listed so the reason is on record.
REJECTED_SOURCES: dict[str, str] = {
    "wyca_tam": "WYCA traffic and active mode counts are not open data.",
    "telraam": "CC BY-NC 4.0: only in cases labelled licence_class non_commercial (leuven-v1).",
    "vivacity": "no open publication found (Data Mill North searched 2026-10-08).",
}


def reviewed_licence(source: str) -> tuple[str | None, str | None]:
    """Return (licence id, None) for a reviewed source, else (None, reason)."""
    if source in REVIEWED_SOURCES:
        return REVIEWED_SOURCES[source]["licence"], None
    return None, REJECTED_SOURCES.get(source, "source licence not reviewed")
