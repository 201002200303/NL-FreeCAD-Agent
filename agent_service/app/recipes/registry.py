from copy import deepcopy
from typing import Any

from app.abstract_steps.planner import build_step_queue, should_use_recipe_queue
from app.cad_spec.schemas import CADSpec


COMPLEX_MODEL_TYPES = {
    "robot",
    "car",
    "vehicle",
    "automobile",
    "furniture",
    "assembly",
    "multi_part",
    "character",
    "figure",
}
SIMPLE_MODEL_TYPES = {"box", "cylinder", "lamp", "shaft", "plate", "generic"}
MIN_RECIPE_SCORE = 5


RECIPES: dict[str, dict[str, Any]] = {
    "primitive_box_recipe": {
        "recipe_id": "primitive_box_recipe",
        "applicable_model_types": ["box", "generic"],
        "feature_types": ["box"],
        "required_inputs": ["length", "width", "height"],
        "risk_points": [],
        "validators": ["verify_object_exists", "verify_shape_valid", "verify_bbox_close"],
        "postconditions": ["primary box exists", "box dimensions are close to spec"],
        "abstract_steps": [
            {
                "step_id": "AS1",
                "step_type": "create_primary_solid",
                "intent": "Create the box solid described by the CAD spec.",
                "expected_outputs": ["Base"],
                "postconditions": ["verify_object_exists", "verify_shape_valid", "verify_bbox_close"],
                "allowed_tool_categories": ["primitives"],
                "risk_level": "low",
            }
        ],
    },
    "primitive_cylinder_recipe": {
        "recipe_id": "primitive_cylinder_recipe",
        "applicable_model_types": ["cylinder", "shaft", "generic"],
        "feature_types": ["cylinder"],
        "required_inputs": ["radius", "height"],
        "risk_points": [],
        "validators": ["verify_object_exists", "verify_shape_valid", "verify_bbox_close"],
        "postconditions": ["primary cylinder exists"],
        "abstract_steps": [
            {
                "step_id": "AS1",
                "step_type": "create_primary_solid",
                "intent": "Create the cylinder solid described by the CAD spec.",
                "expected_outputs": ["Cylinder"],
                "postconditions": ["verify_object_exists", "verify_shape_valid"],
                "allowed_tool_categories": ["primitives"],
                "risk_level": "low",
            }
        ],
    },
    "box_with_fillet_recipe": {
        "recipe_id": "box_with_fillet_recipe",
        "applicable_model_types": ["box", "generic"],
        "feature_types": ["box", "fillet"],
        "required_inputs": ["length", "width", "height", "radius"],
        "risk_points": ["fillet can fail on invalid edges or excessive radius"],
        "validators": ["verify_object_exists", "verify_shape_valid", "verify_source_hidden"],
        "postconditions": ["filleted object exists", "source object is hidden"],
        "abstract_steps": [
            {
                "step_id": "AS1",
                "step_type": "create_primary_solid",
                "intent": "Create the base box before adding edge features.",
                "expected_outputs": ["Base"],
                "postconditions": ["verify_object_exists", "verify_shape_valid"],
                "allowed_tool_categories": ["primitives"],
                "risk_level": "low",
            },
            {
                "step_id": "AS2",
                "step_type": "apply_edge_feature",
                "intent": "Apply fillets to the primary box.",
                "input_refs": ["AS1"],
                "expected_outputs": ["Base_Fillet"],
                "postconditions": ["verify_object_exists", "verify_shape_valid", "verify_source_hidden"],
                "allowed_tool_categories": ["features"],
                "risk_level": "high",
            },
        ],
    },
    "cylinder_base_recipe": {
        "recipe_id": "cylinder_base_recipe",
        "applicable_model_types": ["lamp", "cylinder", "generic"],
        "feature_types": ["cylinder"],
        "required_inputs": ["radius", "height"],
        "risk_points": [],
        "validators": ["verify_object_exists", "verify_shape_valid"],
        "postconditions": ["cylinder base exists"],
        "abstract_steps": [
            {
                "step_id": "AS1",
                "step_type": "create_base",
                "intent": "Create a cylindrical base.",
                "expected_outputs": ["Base"],
                "postconditions": ["verify_object_exists", "verify_shape_valid"],
                "allowed_tool_categories": ["primitives"],
                "risk_level": "low",
            }
        ],
    },
    "hole_cut_recipe": {
        "recipe_id": "hole_cut_recipe",
        "applicable_model_types": ["generic", "box", "cylinder"],
        "feature_types": ["hole"],
        "required_inputs": ["target", "radius"],
        "risk_points": ["hole cut modifies an existing solid"],
        "validators": ["verify_object_exists", "verify_shape_valid", "verify_volume_decreased", "verify_source_hidden"],
        "postconditions": ["cut result exists", "volume decreased"],
        "abstract_steps": [
            {
                "step_id": "AS1",
                "step_type": "cut_hole",
                "intent": "Cut a hole into the selected or primary target object.",
                "input_refs": ["target"],
                "expected_outputs": ["target_Hole"],
                "postconditions": ["verify_object_exists", "verify_shape_valid", "verify_volume_decreased"],
                "allowed_tool_categories": ["features", "boolean"],
                "risk_level": "high",
            }
        ],
    },
    "boolean_cut_recipe": {
        "recipe_id": "boolean_cut_recipe",
        "applicable_model_types": ["generic"],
        "feature_types": ["boolean_cut"],
        "required_inputs": ["base", "tool"],
        "risk_points": ["boolean cut can remove unintended geometry"],
        "validators": ["verify_object_exists", "verify_shape_valid", "verify_volume_decreased"],
        "postconditions": ["boolean result exists"],
        "abstract_steps": [
            {
                "step_id": "AS1",
                "step_type": "boolean_cut",
                "intent": "Subtract a tool solid from a base solid.",
                "input_refs": ["base", "tool"],
                "expected_outputs": ["Cut"],
                "postconditions": ["verify_object_exists", "verify_shape_valid", "verify_volume_decreased"],
                "allowed_tool_categories": ["boolean"],
                "risk_level": "high",
            }
        ],
    },
}


def list_recipes() -> list[dict[str, Any]]:
    return [deepcopy(recipe) for recipe in RECIPES.values()]


def get_recipe(recipe_id: str) -> dict[str, Any] | None:
    recipe = RECIPES.get(recipe_id)
    return deepcopy(recipe) if recipe else None


def select_recipe(cad_spec: CADSpec, impact_map: dict | None = None) -> dict[str, Any]:
    if cad_spec.model_type in COMPLEX_MODEL_TYPES:
        return {
            "status": "llm_fallback",
            "message": f"No registered recipe for model_type '{cad_spec.model_type}'.",
            "recipe": None,
            "abstract_step_queue": None,
        }

    if len(cad_spec.features) > 4:
        return {
            "status": "llm_fallback",
            "message": "CAD spec has too many features for a registry recipe.",
            "recipe": None,
            "abstract_step_queue": None,
        }

    feature_types = [feature.type for feature in cad_spec.features]
    candidates = []
    for recipe in RECIPES.values():
        recipe_features = recipe.get("feature_types", [])
        score = 0
        if cad_spec.model_type in recipe.get("applicable_model_types", []):
            score += 2
        elif "generic" in recipe.get("applicable_model_types", []) and cad_spec.model_type in SIMPLE_MODEL_TYPES:
            score += 1
        score += sum(1 for feature_type in recipe_features if feature_type in feature_types)
        if recipe_features and all(feature_type in feature_types for feature_type in recipe_features):
            score += 2
        if score >= MIN_RECIPE_SCORE:
            candidates.append((score, recipe["recipe_id"], recipe))

    if not candidates:
        return {
            "status": "llm_fallback",
            "message": "No registered recipe matches this CAD spec.",
            "recipe": None,
            "abstract_step_queue": None,
        }

    candidates.sort(reverse=True, key=lambda item: item[0])
    selected = deepcopy(candidates[0][2])
    queue = build_step_queue(selected)
    return {
        "status": "ok",
        "recipe": selected,
        "abstract_step_queue": queue.model_dump(mode="json"),
        "message": f"Selected {selected['recipe_id']}.",
    }

