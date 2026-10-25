from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from swiss_pantry.health import additives_risk
from swiss_pantry.health.off_client import HealthFacts

NOVA_PENALTY = {1: 0, 2: 5, 3: 15, 4: 30}
NOVA_PENALTY_UNKNOWN = 5

# Weights mirror the user's stated priorities (additives and saturated fat
# matter, salt/energy don't) rather than Yuka's undisclosed formula, which we
# have no access to and can't replicate exactly. Additives are weighted by
# risk tier (from Open Food Facts' EFSA/ANSES data) rather than a flat count
# per item - an additive with no flagged concern (citric acid, lecithin)
# barely costs anything; one flagged high-risk (nitrites, MSG) costs a lot.
ADDITIVE_PENALTY_BY_RISK = {"high": 10, "moderate": 5, "low": 1}
ADDITIVE_PENALTY_CAP = 30
SAT_FAT_PENALTY_PER_GRAM = 6
SAT_FAT_PENALTY_CAP = 30

GRADE_THRESHOLDS = [(85, "A"), (70, "B"), (50, "C"), (30, "D")]

NOVA_LABELS = {
    1: "unprocessed / minimally processed",
    2: "processed culinary ingredient",
    3: "processed food",
    4: "ultra-processed food",
}


@dataclass
class ScoreBreakdown:
    nova_group: Optional[int]
    nova_penalty: float
    additives: list[additives_risk.AdditiveInfo]
    additives_penalty: float
    saturated_fat_per_100g: Optional[float]
    saturated_fat_penalty: float
    total_score: float
    grade: str


def _grade_for(value: float) -> str:
    for threshold, letter in GRADE_THRESHOLDS:
        if value >= threshold:
            return letter
    return "E"


def compute_breakdown(
    nova_group: Optional[int],
    additives_tags: Optional[list[str]],
    saturated_fat_per_100g: Optional[float],
) -> Optional[ScoreBreakdown]:
    # Processing level is the single heaviest term in the score (up to -30),
    # so without it the result isn't a measurement, it's a guess wearing a
    # grade. Treating "unknown" as a small -5 penalty used to let genuinely
    # unclassified products surface as an A, implying a confidence we don't
    # have. No NOVA group means no score.
    if nova_group is None:
        return None

    nova_penalty = NOVA_PENALTY.get(nova_group, 10)

    additives = additives_risk.classify_all(additives_tags) if additives_tags is not None else []
    additives_penalty = min(
        sum(ADDITIVE_PENALTY_BY_RISK[a.risk] for a in additives), ADDITIVE_PENALTY_CAP
    )

    sat_fat_penalty = (
        min(saturated_fat_per_100g * SAT_FAT_PENALTY_PER_GRAM, SAT_FAT_PENALTY_CAP)
        if saturated_fat_per_100g is not None
        else 0
    )

    total_penalty = nova_penalty + additives_penalty + sat_fat_penalty
    value = round(max(0.0, min(100.0, 100.0 - total_penalty)), 1)

    return ScoreBreakdown(
        nova_group=nova_group,
        nova_penalty=nova_penalty,
        additives=additives,
        additives_penalty=additives_penalty,
        saturated_fat_per_100g=saturated_fat_per_100g,
        saturated_fat_penalty=sat_fat_penalty,
        total_score=value,
        grade=_grade_for(value),
    )


def score_from_parts(
    nova_group: Optional[int],
    additives_tags: Optional[list[str]],
    saturated_fat_per_100g: Optional[float],
) -> tuple[Optional[float], Optional[str]]:
    """Score directly from stored columns, so a scoring-rule change can be
    replayed over the existing DB without re-scraping (see rescore.py)."""
    breakdown = compute_breakdown(nova_group, additives_tags, saturated_fat_per_100g)
    if breakdown is None:
        return None, None
    return breakdown.total_score, breakdown.grade


def score(facts: Optional[HealthFacts]) -> tuple[Optional[float], Optional[str]]:
    if facts is None:
        return None, None
    breakdown = compute_breakdown(facts.nova_group, facts.additives_tags, facts.saturated_fat_per_100g)
    if breakdown is None:
        return None, None
    return breakdown.total_score, breakdown.grade


def explain(
    nova_group: Optional[int],
    additives_tags: Optional[list[str]],
    saturated_fat_per_100g: Optional[float],
) -> str:
    """Human-readable breakdown of how a stored score was arrived at, rebuilt
    from the same inputs that were saved alongside it - used by the app so a
    confusing grade can be explained without re-querying Open Food Facts."""
    breakdown = compute_breakdown(nova_group, additives_tags, saturated_fat_per_100g)
    if breakdown is None:
        if nova_group is None and (additives_tags is not None or saturated_fat_per_100g is not None):
            return (
                "Not rated: Open Food Facts has no processing (NOVA) classification for this "
                "product. Some data exists (see the nutrition columns), but not enough to grade it."
            )
        return "Not rated: no Open Food Facts data found for this product."

    parts = []
    label = NOVA_LABELS.get(breakdown.nova_group, "unknown")
    parts.append(f"NOVA {breakdown.nova_group} ({label}): -{breakdown.nova_penalty:.0f}")

    if not breakdown.additives:
        parts.append("no additives: -0")
    else:
        by_risk: dict = {"high": [], "moderate": [], "low": []}
        for a in breakdown.additives:
            by_risk[a.risk].append(a.name.split(" - ")[-1] if " - " in a.name else a.name)
        risk_bits = []
        for tier in ("high", "moderate", "low"):
            if by_risk[tier]:
                risk_bits.append(f"{tier}-risk: {', '.join(by_risk[tier])}")
        parts.append(f"{len(breakdown.additives)} additives ({'; '.join(risk_bits)}): -{breakdown.additives_penalty:.0f}")

    if breakdown.saturated_fat_per_100g is not None:
        parts.append(f"{breakdown.saturated_fat_per_100g:.1f}g sat. fat/100g: -{breakdown.saturated_fat_penalty:.1f}")
    else:
        parts.append("saturated fat unknown: -0")

    return " · ".join(parts) + f" → {breakdown.total_score:.1f}/100 ({breakdown.grade})"
