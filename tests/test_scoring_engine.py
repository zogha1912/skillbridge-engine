import random

import pytest

from app.services.engine import AntiResumeItem, EngineConfig, TargetSkill, score_role

# Skill IDs for the worked example in docs/02-architecture.md §4.6
PYTHON, SQL, REST, DOCKER, ONCALL, COBOL, JCL, INCIDENT = range(1, 9)


def sim_table(pairs: dict[tuple[int, int], float]):
    def similarity(a: int, b: int) -> float:
        return pairs.get((a, b), pairs.get((b, a), 0.0))

    return similarity


EXAMPLE_SIM = sim_table({(INCIDENT, ONCALL): 0.95})
USER = {PYTHON, SQL, DOCKER}
ANTI = [AntiResumeItem(COBOL, "hard"), AntiResumeItem(INCIDENT, "strong")]

ROLE_A = [
    TargetSkill(PYTHON, "essential"),
    TargetSkill(SQL, "essential"),
    TargetSkill(REST, "essential"),
    TargetSkill(DOCKER, "optional"),
    TargetSkill(ONCALL, "optional"),
]
ROLE_B = [TargetSkill(COBOL, "essential"), TargetSkill(SQL, "essential"), TargetSkill(JCL, "essential")]


def test_worked_example_role_a_is_kept():
    r = score_role(ROLE_A, USER, ANTI, EXAMPLE_SIM)
    assert r.match == pytest.approx(0.625)
    assert [(d.skill_id, d.weight) for d in r.delta] == [(REST, 1.0), (ONCALL, 0.5)]
    assert [(o.anti_skill_id, o.target_skill_id) for o in r.overlaps] == [(INCIDENT, ONCALL)]
    assert r.overlaps[0].value == pytest.approx(0.2375)
    assert r.final_score == pytest.approx(0.26875)
    assert not r.pruned
    assert r.engine_version == "1.0.0"


def test_worked_example_role_b_is_pruned():
    r = score_role(ROLE_B, USER, ANTI, EXAMPLE_SIM)
    assert r.match == pytest.approx(1 / 3)
    assert r.final_score == pytest.approx(1 / 3 - 1.5)
    assert r.pruned


def test_importance_overrides_relation_weight():
    target = [TargetSkill(PYTHON, "essential", importance=0.8), TargetSkill(SQL, "optional", importance=0.2)]
    assert score_role(target, {SQL}, [], sim_table({})).match == pytest.approx(0.2 / 1.0)


def test_similar_skill_covers_target_at_threshold():
    target = [TargetSkill(PYTHON, "essential")]
    assert score_role(target, {SQL}, [], sim_table({(SQL, PYTHON): 0.90})).match == 1.0
    assert score_role(target, {SQL}, [], sim_table({(SQL, PYTHON): 0.89})).match == 0.0


def test_overlap_below_threshold_is_ignored():
    r = score_role(ROLE_A, USER, [AntiResumeItem(INCIDENT, "hard")], sim_table({(INCIDENT, ONCALL): 0.79}))
    assert r.overlaps == [] and r.penalty == 0


def test_hard_dealbreaker_on_essential_skill_always_prunes():
    # Even a perfect skill match cannot survive a hard deal-breaker on an essential skill.
    target = [TargetSkill(PYTHON, "essential"), TargetSkill(COBOL, "essential")]
    r = score_role(target, {PYTHON, COBOL}, [AntiResumeItem(COBOL, "hard")], sim_table({}))
    assert r.match == 1.0 and r.pruned


def test_empty_role_scores_zero_and_is_pruned():
    r = score_role([], USER, ANTI, EXAMPLE_SIM)
    assert (r.match, r.final_score, r.pruned, r.delta) == (0.0, 0.0, True, [])


def test_custom_config():
    r = score_role(ROLE_A, USER, ANTI, EXAMPLE_SIM, EngineConfig(alpha=0.0, version="test"))
    assert r.final_score == pytest.approx(0.625) and r.engine_version == "test"


# Property checks (docs/02-architecture.md §4.7), on seeded random roles.
def random_case(rng: random.Random):
    skills = list(range(1, 30))
    target = [
        TargetSkill(s, rng.choice(["essential", "optional"]), rng.choice([None, round(rng.random(), 2)]))
        for s in rng.sample(skills, rng.randint(1, 10))
    ]
    user = set(rng.sample(skills, rng.randint(0, 12)))
    anti = [AntiResumeItem(s, rng.choice(["hard", "strong", "mild"])) for s in rng.sample(skills, rng.randint(0, 4))]
    pairs = {(a, b): round(rng.random(), 2) for a in skills for b in skills if a < b and rng.random() < 0.2}
    return target, user, anti, sim_table(pairs), skills


@pytest.mark.parametrize("seed", range(200))
def test_properties(seed):
    rng = random.Random(seed)
    target, user, anti, sim, skills = random_case(rng)
    base = score_role(target, user, anti, sim)

    assert 0.0 <= base.match <= 1.0
    assert base.penalty >= 0
    assert base.pruned == (base.final_score <= 0)

    # Adding a user skill never lowers Match.
    extra = rng.choice(skills)
    assert score_role(target, user | {extra}, anti, sim).match >= base.match - 1e-12

    # Adding an Anti-Resume item never raises the Final Score.
    more_anti = anti + [AntiResumeItem(rng.choice(skills), rng.choice(["hard", "strong", "mild"]))]
    assert score_role(target, user, more_anti, sim).final_score <= base.final_score + 1e-12
