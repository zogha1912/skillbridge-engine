from etl.esco_import import in_scope, map_skill_type, select_rows, split_labels

OCC_DEV = "http://data.europa.eu/esco/occupation/dev"
OCC_NURSE = "http://data.europa.eu/esco/occupation/nurse"
SK_PY = "http://data.europa.eu/esco/skill/python"
SK_CARE = "http://data.europa.eu/esco/skill/care"
SK_HASKELL = "http://data.europa.eu/esco/skill/haskell"


def occ(uri, label, isco, alt=""):
    return {"conceptUri": uri, "preferredLabel": label, "iscoGroup": isco, "code": isco + ".1",
            "altLabels": alt, "description": f"{label} description", "status": "released"}


def skill(uri, label, skill_type="knowledge"):
    return {"conceptUri": uri, "preferredLabel": label, "altLabels": "", "description": "",
            "skillType": skill_type, "status": "released"}


def rel(occupation, skill_uri, relation):
    return {"occupationUri": occupation, "skillUri": skill_uri, "relationType": relation}


def test_in_scope_uses_isco_groups():
    assert in_scope("2512", "ict")  # software developers
    assert in_scope("3512", "ict")  # ICT user support technicians
    assert in_scope("1330", "ict")  # ICT service managers
    assert not in_scope("3521", "ict")  # broadcasting technicians
    assert not in_scope("2221", "ict")
    assert in_scope("2221", "all")


def test_split_labels_dedupes_and_drops_blanks():
    assert split_labels("application developer\n\n  software engineer \napplication developer") == [
        "application developer",
        "software engineer",
    ]
    assert split_labels("") is None


def test_map_skill_type():
    assert map_skill_type("skill/competence") == "skill"
    assert map_skill_type("knowledge") == "knowledge"
    assert map_skill_type("") is None


def test_select_rows_ict_scope():
    occs, skills, links = select_rows(
        occupations=[occ(OCC_DEV, "software developer", "2512", alt="application developer"), occ(OCC_NURSE, "nurse", "2221")],
        skills=[skill(SK_PY, "Python"), skill(SK_CARE, "patient care", "skill/competence"), skill(SK_HASKELL, "Haskell")],
        relations=[
            rel(OCC_DEV, SK_PY, "optional"),
            rel(OCC_DEV, SK_PY, "essential"),  # duplicate pair: essential wins
            rel(OCC_NURSE, SK_CARE, "essential"),  # out of scope
        ],
        digital_skill_uris={SK_HASKELL},
        scope="ict",
    )
    assert [o["title"] for o in occs] == ["software developer"]
    assert occs[0]["alt_labels"] == ["application developer"]
    assert sorted(s["preferred_label"] for s in skills) == ["Haskell", "Python"]  # linked + digital, not nursing
    assert links == [{"occupation_uri": OCC_DEV, "skill_uri": SK_PY, "relation": "essential", "importance": None}]
