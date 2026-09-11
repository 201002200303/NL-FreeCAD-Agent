# API Contract V0.8 - CAD Harness Core

> **归档文档**：本文记录的是已被取代的历史方案，不是当前实现依据。
> 当前主线见 [development_mainline.md](../development_mainline.md) / [code_mode.md](../code_mode.md)；归档清单见 [README.md](./README.md)。


V0.8 keeps the V0.7 closed loop and adds a controlled CAD Harness path:

`Spec -> Inspect -> Recipe -> Abstract Step -> Verify -> Repair`

The legacy `/agent/plan`, `/agent/start_plan`, `/agent/next_step`, and `/agent/evaluate_step` endpoints remain compatible.

## POST /agent/spec

Natural language to structured CAD Spec. This endpoint never returns tool calls.

Request:

```json
{
  "user_input": "create a 100x60x20 box with fillet radius 3",
  "debug_mode": false
}
```

Response:

```json
{
  "status": "ok",
  "user_input": "create a 100x60x20 box with fillet radius 3",
  "cad_spec": {
    "model_type": "box",
    "unit": "mm",
    "coordinate_system": "XYZ",
    "features": [
      {
        "type": "box",
        "name_hint": "Base",
        "dimensions": {"length": 100, "width": 60, "height": 20},
        "position": null,
        "target_hint": null,
        "parameters": {}
      },
      {
        "type": "fillet",
        "name_hint": null,
        "dimensions": {"radius": 3},
        "position": null,
        "target_hint": "selected_or_primary_solid",
        "parameters": {}
      }
    ],
    "dimensions": {"length": 100, "width": 60, "height": 20, "fillet_radius": 3},
    "unknowns": [],
    "assumptions": ["Unit defaults to mm when not specified."]
  },
  "question": null,
  "message": null
}
```

## POST /agent/impact_map

CAD Spec plus current document state to Model Impact Map.

Request:

```json
{
  "cad_spec": {
    "model_type": "generic",
    "unit": "mm",
    "coordinate_system": "XYZ",
    "features": [
      {
        "type": "hole",
        "dimensions": {"radius": 5},
        "target_hint": "selected_or_primary_solid"
      }
    ],
    "dimensions": {},
    "unknowns": [],
    "assumptions": []
  },
  "document_state": {
    "document_name": "Unnamed",
    "selected_objects": ["Base"],
    "objects": [
      {
        "name": "Base",
        "label": "Base",
        "type": "Part::Box",
        "visible": true,
        "topology": {"faces": 6, "edges": 12, "vertices": 8, "solids": 1, "is_valid": true},
        "properties": {}
      }
    ]
  }
}
```

Response:

```json
{
  "status": "ok",
  "impact_map": {
    "target_objects": ["Base"],
    "affected_geometry": ["hole:Base"],
    "helper_objects": ["temporary cutting cylinder"],
    "expected_changes": ["Apply hole to 'Base'."],
    "risk_points": ["hole modifies existing geometry and should be confirmed."],
    "requires_confirmation": true,
    "blocked": false,
    "block_reason": null
  },
  "message": null
}
```

If no target can be resolved for a high-risk existing-object operation, `status` is `blocked`.

## POST /agent/select_recipe

Selects a registered recipe only. The service does not invent recipes.

Request:

```json
{
  "cad_spec": {
    "model_type": "box",
    "unit": "mm",
    "coordinate_system": "XYZ",
    "features": [
      {"type": "box", "name_hint": "Base", "dimensions": {"length": 100, "width": 60, "height": 20}},
      {"type": "fillet", "dimensions": {"radius": 3}, "target_hint": "selected_or_primary_solid"}
    ],
    "dimensions": {},
    "unknowns": [],
    "assumptions": []
  },
  "impact_map": {}
}
```

Response:

```json
{
  "status": "ok",
  "recipe": {
    "recipe_id": "box_with_fillet_recipe",
    "applicable_model_types": ["box", "generic"],
    "required_inputs": ["length", "width", "height", "radius"],
    "postconditions": ["filleted object exists", "source object is hidden"],
    "risk_points": ["fillet can fail on invalid edges or excessive radius"],
    "validators": ["verify_object_exists", "verify_shape_valid", "verify_source_hidden"]
  },
  "abstract_step_queue": {
    "recipe_id": "box_with_fillet_recipe",
    "current_step_id": "AS1",
    "steps": [
      {
        "step_id": "AS1",
        "step_type": "create_primary_solid",
        "intent": "Create the base box before adding edge features.",
        "allowed_tool_categories": ["primitives"],
        "max_retry": 2,
        "risk_level": "low",
        "status": "pending"
      }
    ]
  },
  "message": "Selected box_with_fillet_recipe."
}
```

## POST /agent/next_step V0.8 Extension

Existing V0.7 fields are still accepted. Optional V0.8 fields constrain generation to the current recipe and abstract step:

```json
{
  "session_id": "session_123",
  "user_input": "create a 100x60x20 box",
  "high_level_plan": {"goal": "box", "phases": [{"phase_id": "P1", "title": "Build", "intent": "Build box"}]},
  "current_phase_id": "P1",
  "document_state": {"document_name": "Unnamed", "objects": [], "selected_objects": []},
  "cad_spec": {"model_type": "box", "unit": "mm", "coordinate_system": "XYZ", "features": [{"type": "box", "name_hint": "Base", "dimensions": {"length": 100, "width": 60, "height": 20}}]},
  "current_recipe": {"recipe_id": "primitive_box_recipe"},
  "current_abstract_step": {"step_id": "AS1", "step_type": "create_primary_solid", "intent": "Create box"}
}
```

Response includes traceability:

```json
{
  "decision": "execute",
  "phase_id": "P1",
  "recipe_id": "primitive_box_recipe",
  "abstract_step_id": "AS1",
  "tool_calls": [
    {
      "call_id": "AS1_1",
      "tool": "create_box",
      "args": {"name": "Base", "length": 100, "width": 60, "height": 20, "unit": "mm"},
      "description": "Create box from CAD spec.",
      "expected_effect": {"new_object": "Base", "type": "Part::Box"}
    }
  ]
}
```

## POST /agent/evaluate_step V0.8 Extension

Optional V0.8 fields add validator and postcondition results:

```json
{
  "session_id": "session_123",
  "last_tool_call": {"call_id": "AS1_1", "tool": "create_box", "expected_effect": {"new_object": "Base"}},
  "execution_result": {"call_id": "AS1_1", "status": "success", "tool": "create_box", "produced_objects": ["Base"]},
  "before_state": {"document_name": "Unnamed", "objects": [], "selected_objects": []},
  "document_state": {
    "document_name": "Unnamed",
    "objects": [
      {"name": "Base", "label": "Base", "type": "Part::Box", "visible": true, "topology": {"solids": 1, "is_valid": true}}
    ],
    "selected_objects": []
  },
  "current_recipe": {"recipe_id": "primitive_box_recipe", "validators": ["verify_object_exists", "verify_shape_valid"]},
  "current_abstract_step": {"step_id": "AS1", "postconditions": ["verify_object_exists", "verify_shape_valid"]}
}
```

Response:

```json
{
  "decision": "continue",
  "phase_status": "in_progress",
  "validator_results": [
    {"validator": "verify_object_exists", "passed": true, "error_code": null},
    {"validator": "verify_shape_valid", "passed": true, "error_code": null}
  ],
  "postcondition_results": [
    {"validator": "verify_object_exists", "passed": true, "error_code": null},
    {"validator": "verify_shape_valid", "passed": true, "error_code": null}
  ]
}
```
