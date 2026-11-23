"""Reviewed licence table for count sources."""
from __future__ import annotations

REVIEWED_SOURCES: dict[str, dict] = {
    "dft_manual": {
        "licence": "OGL-UK-3.0",
        "publisher": "Department for Transport, road traffic statistics (count point AADF)",
        "url": "https://roadtraffic.dft.gov.uk/downloads",
        "reviewed": "2026-11-23, OGL v3.0 verified on publisher portal",
    },
    "vic_dtp_aadt": {
        "licence": "CC-BY-4.0",
        "publisher": "Victoria Department of Transport and Planning, traffic volume",
        "url": "https://discover.data.vic.gov.au/dataset/historical-annual-average-daily-traffic-volume",
        "reviewed": "2026-11-23, CC BY 4.0 verified on DataVic / Transport Victoria",
    },
    "melbourne_ped": {
        "licence": "CC-BY-4.0",
        "publisher": "City of Melbourne pedestrian counting system",
        "url": "https://data.melbourne.vic.gov.au/explore/dataset/pedestrian-counting-system-sensor-locations/",
        "reviewed": "2026-11-23, CC BY 4.0 verified on City of Melbourne Open Data",
    },
    "leeds_footfall": {
        "licence": "OGL-UK-3.0",
        "publisher": "Leeds City Council, city centre footfall cameras (Data Mill North)",
        "url": "https://datamillnorth.org/dataset/leeds-city-centre-footfall-2kx4d",
        "reviewed": "2026-11-23, OGL v3.0 verified on Data Mill North",
    },
    "tfl": {
        "licence": "OGL-UK-2.0",
        "publisher": "Transport for London, Active Travel Counts Programme (TfL Open Data terms, OGL v2.0 with TfL amendments)",
        "url": "https://cycling.data.tfl.gov.uk",
        "attribution": "Powered by TfL Open Data. Contains OS data © Crown copyright and database rights 2026.",
        "reviewed": "2026-11-23, TfL Open Data terms (OGL v2.0 + TfL/OS attribution clauses) verified",
    },
    "stadt_zuerich_miv": {
        "licence": "CC0-1.0",
        "publisher": "Stadt Zuerich, motorised traffic counts (all motor vehicles)",
        "url": "https://data.stadt-zuerich.ch/dataset/sid_dav_verkehrszaehlung_miv_od2031",
        "reviewed": "2026-11-23, CC0 1.0 verified on Stadt Zuerich Open Data",
    },
    "stadt_zuerich_fuss_velo": {
        "licence": "CC0-1.0",
        "publisher": "Stadt Zuerich, automatic pedestrian and bicycle counts",
        "url": "https://data.stadt-zuerich.ch/dataset/ted_taz_verkehrszaehlungen_werte_fussgaenger_velo",
        "reviewed": "2026-11-23, CC0 1.0 verified on Stadt Zuerich Open Data",
    },
    **{src: {
        "licence": "OGL-Toronto",
        "publisher": f"City of Toronto open data ({what})",
        "url": f"https://open.toronto.ca/dataset/{slug}/",
        "reviewed": "2026-11-23, Open Government Licence – Toronto verified on open.toronto.ca",
    } for src, slug, what in (
        ("toronto_tmc", "traffic-volumes-at-intersections-for-all-modes", "turning movement counts"),
        ("toronto_svc", "traffic-volumes-midblock-vehicle-speed-volume-and-classification-counts", "speed and volume counts"),
        ("toronto_bike", "permanent-bicycle-counters", "permanent bicycle counters"),
    )},
    **{src: {
        "licence": "ODbL-1.0",
        "publisher": f"Direction de la Voirie et des Déplacements – Ville de Paris ({what})",
        "url": f"https://opendata.paris.fr/explore/dataset/{ds}/",
        "reviewed": "2026-11-23, ODbL 1.0 verified on opendata.paris.fr",
    } for src, ds, what in (
        ("paris_multimodal", "comptage-multimodal-comptages", "multimodal thermal sensors"),
        ("paris_velo", "comptage-velo-donnees-compteurs", "Eco-Counter bicycle counters"),
        ("paris_road", "comptages-routiers-permanents", "permanent road traffic loops"),
    )},
}

NON_COMMERCIAL_SOURCES: dict[str, dict] = {
    "telraam": {
        "licence": "CC-BY-NC-4.0",
        "publisher": "Telraam citizen traffic sensors",
        "url": "https://faq.telraam.net/article/9/telraam-data-license-what-can-i-do-with-the-telraam-data",
        "reviewed": "2026-11-23, CC BY-NC 4.0 verified per Telraam FAQ",
    },
}

REJECTED_SOURCES: dict[str, str] = {
    "wyca_tam": "WYCA traffic and active mode counts are not open data.",
    "telraam": "CC BY-NC 4.0: non-commercial only; excluded from open benchmark cases.",
    "vivacity": "no open publication found (Data Mill North searched 2026-10-08).",
}


def reviewed_licence(source: str) -> tuple[str | None, str | None]:
    if source in REVIEWED_SOURCES:
        return REVIEWED_SOURCES[source]["licence"], None
    return None, REJECTED_SOURCES.get(source, "source licence not reviewed")
