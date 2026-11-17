"""Skill Delta, Match, Anti-Resume overlap and Final Score (docs/02-architecture.md §4).

Pure functions with no database or network access. Skill similarity is passed in as a
callable, so the caller decides where vectors come from (pgvector in the app, a dict
in tests). Similarity of a skill with itself is always 1.0.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

Similarity = Callable[[int, int], float]


@dataclass(frozen=True)
class EngineConfig:
    version: str = "1.0.0"
    alpha: float = 1.5  # Anti-Resume penalty multiplier
    tau_match: float = 0.90  # similarity at which a user skill covers a target skill
    tau_overlap: float = 0.80  # similarity at which a deal-breaker hits a target skill
    severity_weights: dict[str, float] = field(
        default_factory=lambda: {"hard": 1.0, "strong": 0.5, "mild": 0.2}
    )
    essential_weight: float = 1.0  # used when a link has no importance rating
    optional_weight: float = 0.5


@dataclass(frozen=True)
class TargetSkill:
    skill_id: int
    relation: str  # "essential" | "optional"
    importance: float | None = None  # 0..1 when the source rates it (O*NET)


@dataclass(frozen=True)
class AntiResumeItem:
    skill_id: int
    severity: str  # "hard" | "strong" | "mild"


@dataclass(frozen=True)
class DeltaItem:
    skill_id: int
    relation: str
    weight: float


@dataclass(frozen=True)
class Overlap:
    anti_skill_id: int
    target_skill_id: int
    similarity: float
    value: float  # severity * weight * similarity


@dataclass(frozen=True)
class ScoreResult:
    match: float
    penalty: float  # alpha * sum(overlap values)
    final_score: float
    pruned: bool
    delta: list[DeltaItem]  # missing skills, essential first, then by weight
    overlaps: list[Overlap]
    engine_version: str


def skill_weight(skill: TargetSkill, config: EngineConfig) -> float:
    if skill.importance is not None:
        return min(max(skill.importance, 0.0), 1.0)
    return config.essential_weight if skill.relation == "essential" else config.optional_weight


def _sim(similarity: Similarity, a: int, b: int) -> float:
    return 1.0 if a == b else similarity(a, b)


def is_covered(target_id: int, user_skills: Iterable[int], similarity: Similarity, config: EngineConfig) -> bool:
    return any(_sim(similarity, u, target_id) >= config.tau_match for u in user_skills)


def score_role(
    target: list[TargetSkill],
    user_skills: set[int],
    anti_resume: list[AntiResumeItem],
    similarity: Similarity,
    config: EngineConfig | None = None,
) -> ScoreResult:
    config = config or EngineConfig()
    weights = {t.skill_id: skill_weight(t, config) for t in target}
    total = sum(weights.values())

    covered_weight = 0.0
    delta = []
    for t in target:
        if is_covered(t.skill_id, user_skills, similarity, config):
            covered_weight += weights[t.skill_id]
        else:
            delta.append(DeltaItem(t.skill_id, t.relation, weights[t.skill_id]))
    delta.sort(key=lambda d: (d.relation != "essential", -d.weight, d.skill_id))
    match = covered_weight / total if total > 0 else 0.0

    overlaps = []
    for item in anti_resume:
        severity = config.severity_weights[item.severity]
        best = max(
            ((t.skill_id, _sim(similarity, item.skill_id, t.skill_id)) for t in target),
            key=lambda pair: (pair[1], -pair[0]),
            default=None,
        )
        if best is not None and best[1] >= config.tau_overlap:
            target_id, sim = best
            overlaps.append(Overlap(item.skill_id, target_id, sim, severity * weights[target_id] * sim))

    penalty = config.alpha * sum(o.value for o in overlaps)
    final_score = match - penalty
    return ScoreResult(
        match=match,
        penalty=penalty,
        final_score=final_score,
        pruned=final_score <= 0,
        delta=delta,
        overlaps=overlaps,
        engine_version=config.version,
    )
