# scene_types.py
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pi3d

if TYPE_CHECKING:
    from eye.lid import EyeLidMesh


@dataclass
class LidPoints:
    closed: list
    open: list
    edge: list

@dataclass
class EyeMeshes:
    iris: pi3d.Shape
    sclera: pi3d.Shape
    lids: EyeLidMesh # type checker sees this, runtime never evaluates it

@dataclass
class SvgPoints:
    view_box: tuple
    pupil_min: list
    pupil_max: list
    iris: list
    sclera_front: list
    sclera_back: list
    upper_lid: LidPoints
    lower_lid: LidPoints

@dataclass
class SceneContext:
    left: EyeMeshes
    right: EyeMeshes
    iris_z: float
    iris_regen_threshold: float
    upper_lid_regen_threshold: float
    lower_lid_regen_threshold: float