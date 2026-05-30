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


class BoundingBox(BaseModel):
    """3D bounding box of a CAD object."""
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float
    center: list[float] = Field(default_factory=list, description="[cx, cy, cz]")
    size: list[float] = Field(default_factory=list, description="[sx, sy, sz]")


class TopologySummary(BaseModel):
    """Topology summary of a CAD object's Shape."""
    faces: int = 0
    edges: int = 0
    vertices: int = 0
    solids: int = 0
    is_valid: bool = True
    volume: Optional[float] = None
    area: Optional[float] = None


class PlacementSummary(BaseModel):
    """Placement (position + rotation) of a CAD object."""
    base: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation_euler: Optional[list[float]] = None


class DependencyInfo(BaseModel):
    """Dependency chain (InList/OutList) of a CAD object."""
    in_list: list[str] = Field(default_factory=list, description="Objects that depend on this object")
    out_list: list[str] = Field(default_factory=list, description="Objects this object depends on")


class CADObject(BaseModel):
    name: str = Field(..., description="Internal object name")
    label: str = Field(..., description="User-visible label")
    type: str = Field(..., description="FreeCAD object type")
    visible: bool = Field(default=True, description="Whether object is visible")
    bbox: Optional[BoundingBox] = Field(default=None, description="Bounding box (None for non-shape objects)")
    topology: Optional[TopologySummary] = Field(default=None, description="Topology summary (None for non-shape objects)")
    placement: Optional[PlacementSummary] = Field(default=None, description="Placement (None for non-shape objects)")
    dependencies: Optional[DependencyInfo] = Field(default=None, description="Dependency chain")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Object properties (Length, Width, etc.)"
    )


class DocumentState(BaseModel):
    document_name: str = Field(default="Unnamed", description="FreeCAD document name")
    objects: list[CADObject] = Field(default_factory=list)
    selected_objects: list[str] = Field(
        default_factory=list, description="Names of selected objects"
    )
