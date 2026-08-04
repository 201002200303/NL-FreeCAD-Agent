from app.abstract_steps.schemas import AbstractStep, AbstractStepQueue
from app.cad_spec.schemas import CADSpec


def build_step_queue(recipe: dict) -> AbstractStepQueue:
    steps = [AbstractStep(**item) for item in recipe.get("abstract_steps", [])]
    return AbstractStepQueue(
        recipe_id=recipe["recipe_id"],
        steps=steps,
        current_step_id=steps[0].step_id if steps else None,
    )


def advance_step_queue(queue: AbstractStepQueue, completed_step_id: str) -> AbstractStepQueue:
    next_id = None
    seen_completed = False
    for step in queue.steps:
        if step.step_id == completed_step_id:
            step.status = "completed"
            seen_completed = True
            continue
        if seen_completed and step.status == "pending":
            next_id = step.step_id
            break
    queue.current_step_id = next_id
    return queue


def resolve_current_abstract_step(abstract_step_queue: dict | None) -> dict | None:
    """Return the active abstract step from a queue dict, if any."""
    if not abstract_step_queue:
        return None
    queue = AbstractStepQueue(**abstract_step_queue)
    step = queue.current_step()
    if step is None:
        return None
    if step.status == "completed":
        return None
    return step.model_dump(mode="json")


def is_queue_exhausted(abstract_step_queue: dict | None) -> bool:
    if not abstract_step_queue:
        return False
    steps = abstract_step_queue.get("steps", [])
    return bool(steps) and all(step.get("status") == "completed" for step in steps)


def is_harness_session(cad_spec: dict | None, abstract_step_queue: dict | None) -> bool:
    """Return True when the session runs on the unified abstract-step control track.

    After V0.8 unification, an abstract step queue alone drives execution; cad_spec
    is optional context (from LLM or rules) but not required for routing.
    """
    if not abstract_step_queue:
        return False
    return bool(abstract_step_queue.get("steps"))


def build_queue_from_phases(phases: list[dict], recipe_id: str = "llm_session") -> AbstractStepQueue:
    """Convert LLM high-level phases into a unified abstract step queue."""
    steps: list[AbstractStep] = []
    for phase in phases:
        phase_id = phase.get("phase_id") or f"P{len(steps) + 1}"
        criteria = phase.get("success_criteria") or []
        postconditions = [
            item for item in criteria if isinstance(item, str) and item.startswith("verify_")
        ]
        if not postconditions:
            postconditions = ["verify_object_exists", "verify_shape_valid"]
        steps.append(
            AbstractStep(
                step_id=phase_id,
                step_type="llm_phase",
                intent=phase.get("intent") or phase.get("title") or "",
                expected_outputs=[],
                postconditions=postconditions,
                allowed_tool_categories=[],
                risk_level="medium",
            )
        )
    return AbstractStepQueue(
        recipe_id=recipe_id,
        steps=steps,
        current_step_id=steps[0].step_id if steps else None,
    )


def build_queue_from_high_level_plan(high_level_plan: dict) -> AbstractStepQueue:
    """Build abstract step queue from a high-level plan, preferring explicit steps."""
    explicit = high_level_plan.get("abstract_steps")
    if explicit:
        steps = [AbstractStep(**item) for item in explicit]
        return AbstractStepQueue(
            recipe_id=high_level_plan.get("recipe_id", "llm_session"),
            steps=steps,
            current_step_id=steps[0].step_id if steps else None,
        )
    return build_queue_from_phases(
        high_level_plan.get("phases", []),
        recipe_id=high_level_plan.get("recipe_id", "llm_session"),
    )


def should_use_recipe_queue(
    cad_spec: dict | None,
    recipe: dict | None,
    recipe_queue: dict | None,
    high_level_plan: dict | None,
) -> bool:
    """Use registry recipe queue only for simple, well-matched specs."""
    from app.recipes.registry import COMPLEX_MODEL_TYPES

    if not recipe or not recipe_queue or not recipe_queue.get("steps"):
        return False
    model_type = (cad_spec or {}).get("model_type", "generic")
    if model_type in COMPLEX_MODEL_TYPES:
        return False
    phases = (high_level_plan or {}).get("phases") or []
    if len(phases) > len(recipe_queue.get("steps", [])):
        return False
    features = (cad_spec or {}).get("features") or []
    if len(features) > 4:
        return False
    return True


def tool_calls_for_abstract_step(
    *,
    cad_spec: CADSpec,
    abstract_step: dict,
    impact_map: dict | None = None,
    name_map: dict[str, str] | None = None,
    call_prefix: str = "AS",
) -> list[dict]:
    """Generate a small, bounded tool-call batch for one abstract step.

    This is the deterministic V0.8 harness path. It handles common recipes and
    leaves complex cases to the existing LLM next_step path.
    """

    step_type = abstract_step.get("step_type")
    name_map = name_map or {}
    features = cad_spec.features

    if step_type in {"create_primary_solid", "create_base"}:
        feature = _first_feature(features, {"box", "body", "cylinder", "cone"})
        if not feature:
            return []
        return [_create_primitive_call(feature, f"{call_prefix}_1")]

    if step_type == "apply_edge_feature":
        feature = _first_feature(features, {"fillet", "chamfer"})
        primary = _primary_created_name(features)
        target = _resolve_target_name(_target_from_impact(impact_map), name_map, fallback=primary)
        if not feature:
            return []
        if feature.type == "fillet":
            radius = feature.dimensions.get("radius", 2.0)
            return [
                {
                    "call_id": f"{call_prefix}_1",
                    "tool": "add_fillet",
                    "args": {"target": target, "radius": radius, "result_name": f"{target}_Fillet"},
                    "description": abstract_step.get("intent", "Apply fillet"),
                    "expected_effect": {
                        "new_object": f"{target}_Fillet",
                        "source": target,
                        "source_should_be_hidden": True,
                    },
                }
            ]
        if feature.type == "chamfer":
            size = feature.dimensions.get("distance", 2.0)
            return [
                {
                    "call_id": f"{call_prefix}_1",
                    "tool": "add_chamfer",
                    "args": {"target": target, "size": size, "result_name": f"{target}_Chamfer"},
                    "description": abstract_step.get("intent", "Apply chamfer"),
                    "expected_effect": {
                        "new_object": f"{target}_Chamfer",
                        "source": target,
                        "source_should_be_hidden": True,
                    },
                }
            ]

    if step_type == "cut_hole":
        feature = _first_feature(features, {"hole"})
        primary = _primary_created_name(features)
        target = _resolve_target_name(_target_from_impact(impact_map), name_map, fallback=primary)
        if not feature or not target:
            return []
        diameter = feature.dimensions.get("diameter") or feature.dimensions.get("radius", 5.0) * 2
        return [
            {
                "call_id": f"{call_prefix}_1",
                "tool": "cut_hole",
                "args": {"target": target, "hole_diameter": diameter, "through_all": True, "result_name": f"{target}_Hole"},
                "description": abstract_step.get("intent", "Cut hole"),
                "expected_effect": {
                    "new_object": f"{target}_Hole",
                    "source": target,
                    "source_should_be_hidden": True,
                },
            }
        ]

    return []


def _first_feature(features, types: set[str]):
    return next((feature for feature in features if feature.type in types), None)


def _create_primitive_call(feature, call_id: str) -> dict:
    name = feature.name_hint or feature.type.title()
    dims = feature.dimensions
    if feature.type in {"box", "body"}:
        return {
            "call_id": call_id,
            "tool": "create_box",
            "args": {
                "name": name,
                "length": dims.get("length", 100.0),
                "width": dims.get("width", 60.0),
                "height": dims.get("height", 20.0),
                "unit": "mm",
            },
            "description": "Create box from CAD spec.",
            "expected_effect": {"new_object": name, "type": "Part::Box"},
        }
    if feature.type == "cylinder":
        return {
            "call_id": call_id,
            "tool": "create_cylinder",
            "args": {
                "name": name,
                "radius": dims.get("radius", 25.0),
                "height": dims.get("height", 50.0),
                "unit": "mm",
            },
            "description": "Create cylinder from CAD spec.",
            "expected_effect": {"new_object": name, "type": "Part::Cylinder"},
        }
    if feature.type == "cone":
        return {
            "call_id": call_id,
            "tool": "create_cone",
            "args": {
                "name": name,
                "radius1": dims.get("radius1", 35.0),
                "radius2": dims.get("radius2", 18.0),
                "height": dims.get("height", 28.0),
                "unit": "mm",
            },
            "description": "Create cone from CAD spec.",
            "expected_effect": {"new_object": name, "type": "Part::Cone"},
        }
    return {}


def _target_from_impact(impact_map: dict | None) -> str | None:
    if not impact_map:
        return None
    targets = impact_map.get("target_objects") or []
    if not targets:
        return None
    return _sanitize_target_name(targets[0])


def _sanitize_target_name(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    if "," in text:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        return parts[-1] if parts else None
    return text


def _resolve_target_name(raw: str | None, name_map: dict[str, str], fallback: str = "Base") -> str:
    candidate = _sanitize_target_name(raw) or fallback
    if candidate in name_map:
        return name_map[candidate]
    if candidate in name_map.values():
        return candidate
    resolved_fallback = name_map.get(fallback, fallback)
    if resolved_fallback in name_map.values() or resolved_fallback == fallback:
        return resolved_fallback
    return candidate


def _primary_created_name(features) -> str:
    feature = _first_feature(features, {"box", "cylinder", "cone", "body"})
    if feature and feature.name_hint:
        return feature.name_hint
    if feature and feature.type == "box":
        return "Base"
    if feature and feature.type == "cylinder":
        return "Cylinder"
    return "Base"
