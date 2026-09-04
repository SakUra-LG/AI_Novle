from typing import List


# Closed-enum schemas to bound LLM outputs and reduce hallucinations
RELATION_TYPES: List[str] = [
    "ally",
    "hostile",
    "love_interest",
    "family",
    "subordinate",
    "mentor",
    "stranger",
    "rival",
]

RELATION_STATUS: List[str] = [
    "neutral",
    "tension",
    "distrust",
    "fragile_trust",
    "trust",
    "conflict",
    "rupture",
    "intimacy",
]

FORESHADOW_TYPES: List[str] = [
    "identity_secret",
    "object_clue",
    "betrayal_hint",
    "emotion_seed",
    "backstory_gap",
    "threat_seed",
]


def clamp_relation_type(value: str) -> str:
    return value if value in RELATION_TYPES else "ally"


def clamp_relation_status(value: str) -> str:
    return value if value in RELATION_STATUS else "neutral"


def clamp_foreshadow_type(value: str) -> str:
    return value if value in FORESHADOW_TYPES else "object_clue"

