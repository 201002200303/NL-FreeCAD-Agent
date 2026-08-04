from app.inspection.impact_map import ImpactMap


def summarize_risk(impact_map: ImpactMap) -> str:
    if impact_map.blocked:
        return f"blocked: {impact_map.block_reason}"
    if impact_map.requires_confirmation:
        return "high_risk_confirmation_required"
    return "low_risk"

