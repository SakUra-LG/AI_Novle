from typing import Dict, Any, List, Tuple
from .schema import clamp_relation_type, clamp_relation_status


class RelationExtractionProvider:
    """
    Interface for semantic relation extraction from chapter text.
    Implementations should return a list of proposals for present pairs.
    """

    def extract_relations(self, chapter_no: int, paragraphs: List[str], present_pairs: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
        raise NotImplementedError


class SimpleHeuristicExtractor(RelationExtractionProvider):
    """
    A tiny, fully local heuristic extractor so the pipeline can run offline.
    - If two names co-occur in a paragraph containing protective/hostile verbs, assign a type/status with moderate confidence.
    This is intentionally conservative and serves as a placeholder for an actual LLM-backed implementation.
    """

    def extract_relations(self, chapter_no: int, paragraphs: List[str], present_pairs: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []
        protect_cues = {"护住", "挡在", "照顾", "安慰", "扶住", "关心"}
        hostile_cues = {"怒斥", "掌掴", "推搡", "威胁", "讥讽", "敌视", "厌恶"}
        ambiguous_cues = {"沉默", "注视", "凝视", "靠近", "同乘", "对望"}

        for a, b in present_pairs:
            best_span = ""
            rtype = "ally"
            rstatus = "neutral"
            conf = 0.4
            for para in paragraphs:
                if a in para and b in para:
                    best_span = para.strip()[:120]
                    if any(c in para for c in protect_cues):
                        rtype, rstatus, conf = "ally", "fragile_trust", 0.65
                        break
                    if any(c in para for c in hostile_cues):
                        rtype, rstatus, conf = "hostile", "conflict", 0.7
                        break
                    if any(c in para for c in ambiguous_cues):
                        rtype, rstatus, conf = "love_interest", "tension", 0.6
                        # do not break; maybe find stronger cue
            proposals.append(
                {
                    "pair": [a, b],
                    "current_relation_type": clamp_relation_type(rtype),
                    "current_relation_status": clamp_relation_status(rstatus),
                    "changed": True,
                    "previous_status": None,
                    "new_status": clamp_relation_status(rstatus),
                    "evidence_spans": [best_span] if best_span else [],
                    "confidence": conf,
                    "chapter": chapter_no,
                }
            )
        return proposals

