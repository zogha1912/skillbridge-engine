import pytest

from etl.crosswalk_import import parse_crosswalk
from etl.onet_import import in_scope, parse_ratings, rescale_importance, technology_key


def rating_row(soc="15-1252.00", element="2.C.3.a", scale="IM", value="4.0", suppress="N", not_relevant=""):
    return {
        "O*NET-SOC Code": soc,
        "Element ID": element,
        "Element Name": "Computers and Electronics",
        "Scale ID": scale,
        "Data Value": value,
        "Recommend Suppress": suppress,
        "Not Relevant": not_relevant,
    }


@pytest.mark.parametrize(("raw", "expected"), [(1.0, 0.0), (3.0, 0.5), (5.0, 1.0), (0.5, 0.0), (6.0, 1.0)])
def test_rescale_importance_maps_1_to_5_onto_0_to_1(raw, expected):
    assert rescale_importance(raw) == expected


def test_ict_scope():
    assert in_scope("15-1252.00", "ict")  # Software Developers
    assert in_scope("11-3021.00", "ict")  # Computer and Information Systems Managers
    assert not in_scope("29-1141.00", "ict")  # Registered Nurses
    assert in_scope("29-1141.00", "all")


def test_parse_ratings_keeps_only_relevant_importance_rows():
    rows = [
        rating_row(value="4.25"),  # essential
        rating_row(element="2.C.1.a", value="3.0"),  # optional
        rating_row(element="2.C.1.b", value="2.0"),  # below MIN_IMPORTANCE
        rating_row(element="2.C.1.c", scale="LV", value="6.0"),  # level scale, ignored
        rating_row(element="2.C.1.d", suppress="Y"),  # suppressed by O*NET
        rating_row(element="2.C.1.e", not_relevant="Y"),  # marked not relevant
        rating_row(soc="29-1141.00"),  # out of ICT scope
    ]
    ratings = parse_ratings(rows, "ict")
    assert [(r.element_id, r.relation, r.importance) for r in ratings] == [
        ("2.C.3.a", "essential", 0.8125),
        ("2.C.1.a", "optional", 0.5),
    ]


def test_technology_key_normalises_whitespace():
    assert technology_key("  Python   3 ") == "tech:Python 3"


def test_parse_crosswalk_skips_metadata_and_non_occupation_rows():
    lines = [
        ["Mapping project name", "ESCO-O*NET Crosswalk", "", "", "", "", ""],
        ["Classification 1 Name", "O*NET", "", "", "", "", ""],
        ["O*NET Id", "O*NET Title", "O*NET Description", "ESCO or ISCO URI", "ESCO or ISCO Title", "ESCO or ISCO Description", "Type of Match"],
        ["15-1252.00", "Software Developers", "...", "http://data.europa.eu/esco/occupation/abc", "software developer", "...", "exactMatch"],
        ["15-1252.00", "Software Developers", "...", "http://data.europa.eu/esco/occupation/abc", "software developer", "...", "exactMatch"],
        ["15-1252.00", "Software Developers", "...", "http://data.europa.eu/esco/isco/C2512", "Software developers", "...", "broadMatch"],
        ["short row"],
    ]
    assert parse_crosswalk(lines) == [
        {"onet_soc_code": "15-1252.00", "esco_uri": "http://data.europa.eu/esco/occupation/abc", "match_type": "exactMatch"}
    ]
