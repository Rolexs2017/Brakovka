"""Shared unwind/wind roll geometry (diameter ↔ length)."""

from __future__ import annotations

from math import pi, sqrt


def unwind_diameter_m(
    start_diameter_m: float,
    core_diameter_m: float,
    thickness_m: float,
    unwound_m: float,
) -> float:
    """Remaining diameter of a shrinking unwind roll from consumed length."""
    d0 = start_diameter_m
    core = core_diameter_m
    d_sq = d0 * d0 - (4.0 * thickness_m * max(0.0, unwound_m)) / pi
    return sqrt(max(core * core, d_sq))


def remaining_length_m(
    diameter_m: float,
    core_diameter_m: float,
    thickness_m: float,
) -> float:
    """Material length left on an unwind roll at the given diameter."""
    if thickness_m <= 1e-9:
        return 0.0
    return max(
        0.0,
        (pi / (4.0 * thickness_m))
        * (diameter_m * diameter_m - core_diameter_m * core_diameter_m),
    )


def wound_diameter_m(
    core_diameter_m: float,
    thickness_m: float,
    wound_m: float,
) -> float:
    """Growing consumer-roll diameter from wound length."""
    d0 = core_diameter_m
    return sqrt(max(d0 * d0 + (4.0 * thickness_m * max(0.0, wound_m)) / pi, d0 * d0))


def start_diameter_from_length_m(
    core_diameter_m: float,
    thickness_m: float,
    length_m: float,
) -> float:
    """Initial unwind-roll diameter from loaded material length."""
    return wound_diameter_m(core_diameter_m, thickness_m, length_m)
