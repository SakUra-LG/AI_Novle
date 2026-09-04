from typing import Dict, Any


def hard_constraints_pass(old_rel: Dict[str, Any], proposal: Dict[str, Any]) -> bool:
    """
    Very small set of hard constraints to gate wild jumps.
    """
    # Example: do not jump from "hostile/rupture" to "intimacy" in a single chapter
    old_status = (old_rel or {}).get("status")
    new_status = proposal.get("new_status")
    if old_status in {"conflict", "rupture"} and new_status in {"intimacy", "trust"}:
        return False
    return True


def confidence_ok(conf: float, min_promote: float) -> bool:
    return conf >= min_promote

