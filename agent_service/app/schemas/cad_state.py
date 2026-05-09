from pydantic import BaseModel, Field
from typing import Any, Optional
from enum import Enum


class ObjectType(str, Enum):
    BOX = "Part::Box"
    CYLINDER = "Part::Cylinder"
    CUT = "Part::Cut"
    FILLET = "Part::Fillet"
    CHAMFER = "Part::Chamfer"
    SKETCH = "Sketcher::SketchObject"
    PAD = "PartDesign::Pad"
    GENERIC = "App::FeaturePython"


class CADObject(BaseModel):
    name: str = Field(..., description="Internal object name")
    label: str = Field(..., description="User-visible label")
    type: str = Field(..., description="FreeCAD object type")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Object properties (Length, Width, etc.)"
    )


class DocumentState(BaseModel):
    document_name: str = Field(default="Unnamed", description="FreeCAD document name")
    objects: list[CADObject] = Field(default_factory=list)
    selected_objects: list[str] = Field(
        default_factory=list, description="Names of selected objects"
    )
