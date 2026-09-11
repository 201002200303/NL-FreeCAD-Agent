# Runtime Flow V0.8 - CAD Harness Core

> **归档文档**：本文记录的是已被取代的历史方案，不是当前实现依据。
> 当前主线见 [development_mainline.md](../development_mainline.md) / [code_mode.md](../code_mode.md)；归档清单见 [README.md](./README.md)。


V0.8 does not replace the V0.7 Observe-Plan-Act-Evaluate loop. It inserts a controlled harness before and around `next_step`.

```text
User
  -> /agent/spec
  -> /agent/impact_map
  -> /agent/select_recipe
  -> /agent/next_step
  -> FreeCAD execute
  -> /agent/evaluate_step
  -> repair / next abstract step / finish
```

## Rules

- CAD Spec describes what to build. It does not contain tool calls.
- Impact Map identifies existing targets, affected geometry, helper objects, expected changes, and risk points.
- Recipe selection only chooses from the registry.
- Abstract Steps sit between phase and tool call.
- Each `next_step` request may generate only 1 to 3 tool calls for the current Abstract Step.
- Geometry validators run before semantic judgement can mark a step successful.
- Failed validators return explicit `error_code` values and cannot be overridden by LLM judgement.
- Repair is local to the current Abstract Step.

## Traceability

Every V0.8 tool call should be traceable to:

- `cad_spec`
- `impact_map`
- `recipe_id`
- `abstract_step_id`
- validator or postcondition results
