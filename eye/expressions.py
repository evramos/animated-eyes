"""
eye/expressions.py

Loads named lid expressions from resources/expressions/*.json into one registry.
Import via: from eye.expressions import load_expressions
"""

import glob
import json
import os

from constants import EXPRESSION_PATH
from models.expression_types import Expression, LidPose

_POSE_KEYS  = {"upper", "lower"}                         # symmetric shape (right mirrors left)
_SIDE_KEYS  = {"left", "right"}                          # asymmetric shape (each eye independent)
_EXTRA_KEYS = {"pupil_scale", "gaze_bias", "blink_rate"}
_KNOWN_KEYS = _POSE_KEYS | _SIDE_KEYS | _EXTRA_KEYS
_ROT_WARN   = 20.0          # degrees; beyond this the lid curve likely clips (lid_control_plan Q2)
_NEUTRAL    = LidPose()     # defaults for any lid a spec leaves out


def load_expressions(pattern: str = EXPRESSION_PATH) -> dict[str, Expression]:
    """Merge every file matching pattern into one registry, then resolve `extends`.

    Names are case-insensitive (stored upper-case). Later files win on duplicates (sorted
    filename order). Empty folder → empty dict. Raises ValueError on bad values, unknown keys,
    unknown parents, or extends cycles, so mistakes fail at startup rather than mid-sequence.
    """
    raw: dict[str, tuple[dict, str]] = {}   # name → (spec, source filename)
    files = sorted(glob.glob(pattern))
    for path in files:
        src = os.path.basename(path)
        with open(path) as f:
            data = json.load(f)
        if "expressions" not in data:
            print(f"[expr] {src}: no 'expressions' key, skipped")
            continue
        for name, spec in data["expressions"].items():
            key = name.upper()
            if key in raw:
                print(f"[expr] {key} in {src} overrides {raw[key][1]}")
            if _POSE_KEYS & spec.keys() and _SIDE_KEYS & spec.keys():
                print(f"[expr] {key} ({src}): mixes upper/lower with left/right; using left/right")
            raw[key] = (spec, src)

    flat: dict[str, dict] = {}
    registry = {name: _build(name, _resolve(name, raw, flat), raw[name][1]) for name in raw}
    print(f"[expr] {len(registry)} expressions from {len(files)} files: {sorted(registry)}")
    return registry


def _resolve(name: str, raw: dict, flat: dict, chain: tuple = ()) -> dict:
    """Flatten `extends` into one spec dict. chain = names mid-resolution (cycle detection)."""
    if name in flat:
        return flat[name]
    if name in chain:
        raise ValueError(f"[expr] extends cycle: {' → '.join(chain + (name,))}")
    if name not in raw:
        raise ValueError(f"[expr] {chain[-1]} extends unknown expression {name}")

    spec, _ = raw[name]
    parent  = spec.get("extends")
    base    = dict(_resolve(parent.upper(), raw, flat, chain + (name,))) if parent else {}

    # Changing shape drops the parent's other shape: a symmetric child of an asymmetric parent (or vice versa)
    if _POSE_KEYS & spec.keys():
        for k in _SIDE_KEYS: base.pop(k, None)
    if _SIDE_KEYS & spec.keys():
        for k in _POSE_KEYS: base.pop(k, None)

    base.update({k: v for k, v in spec.items() if k != "extends"})
    flat[name] = base
    return base


def _build(name: str, spec: dict, src: str) -> Expression:
    where = f"{name} ({src})"
    if unknown := spec.keys() - _KNOWN_KEYS:
        raise ValueError(f"[expr] {where}: unknown keys {sorted(unknown)}")

    if _SIDE_KEYS & spec.keys():
        for side in sorted(_SIDE_KEYS - spec.keys()):
            print(f"[expr] {where}: no '{side}' pose; {side} eye uses neutral")
        for side in sorted(_SIDE_KEYS & spec.keys()):
            if unknown := spec[side].keys() - _POSE_KEYS:
                raise ValueError(f"[expr] {where} {side}: unknown keys {sorted(unknown)}")
        left  = _pose(spec.get("left",  {}), f"{where} left")
        right = _pose(spec.get("right", {}), f"{where} right")
    else:
        left, right = _pose(spec, where), None

    gaze = spec.get("gaze_bias")
    if gaze is not None and len(gaze) != 2:
        raise ValueError(f"[expr] {where}: gaze_bias must be [x, y]")

    blink = spec.get("blink_rate")
    if blink is not None and blink < 0:
        raise ValueError(f"[expr] {where}: blink_rate must be >= 0")

    return Expression(name, left, right,
                      pupil_scale=_unit(spec.get("pupil_scale"), "pupil_scale", where),
                      gaze_bias=tuple(map(float, gaze)) if gaze is not None else None,
                      blink_rate=float(blink) if blink is not None else None)


def _pose(d: dict, where: str) -> LidPose:
    upper_wt, upper_rot = _pair(d.get("upper"), _NEUTRAL.upper_wt, "upper", where)
    lower_wt, lower_rot = _pair(d.get("lower"), _NEUTRAL.lower_wt, "lower", where)
    return LidPose(upper_wt, lower_wt, upper_rot, lower_rot)


def _pair(value, default_wt: float, label: str, where: str) -> tuple[float, float]:
    """[weight, rotation] | [weight] | weight | None → (weight, rotation)."""
    if value is None:
        value = [default_wt]
    if not isinstance(value, list):
        value = [value]
    if not 1 <= len(value) <= 2:
        raise ValueError(f"[expr] {where}: {label} must be [weight, rotation]")
    wt  = _unit(value[0], label, where)
    rot = float(value[1]) if len(value) == 2 else 0.0
    if abs(rot) > _ROT_WARN:
        print(f"[expr] {where}: {label} rotation {rot}° exceeds ±{_ROT_WARN}° (may clip)")
    return wt, rot


def _unit(value, label: str, where: str) -> float | None:
    if value is None:
        return None
    v = float(value)
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"[expr] {where}: {label}={v} outside 0–1")
    return v
