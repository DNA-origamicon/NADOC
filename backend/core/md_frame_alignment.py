"""Shared rigid alignment for live MD display and trajectory extraction.

Coordinates are measured physical data; this only changes their display frame.
The sequential inlier guard preserves the existing live/playback algorithm.
Periodic image selection remains with each reader (their strand maps differ).
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class FrameAlignment:
    positions: np.ndarray
    rotation: np.ndarray | None
    mobile_centroid: np.ndarray | None
    fit_mask: np.ndarray | None


def align_md_frame(p_nm, ctx, frame_idx: int) -> FrameAlignment:
    """Align a frame and advance this reader's sequential rotation state only."""
    eq_pos = ctx.get("eq_positions")
    eq_valid = ctx.get("eq_valid")
    rigid_mask = ctx.get("rigid_mask")
    eq_centered = ctx.get("eq_centered")
    eq_centroid = ctx.get("eq_centroid")
    _mob_c = _rm = None
    # Kabsch rotation aligned to the design equilibrium (rigid dsDNA atoms only),
    # with the sequential rotation-flip guard from _seek_sync.
    R_align = None
    R_prev = ctx.get("R_prev")
    prev_frame = ctx.get("prev_frame_idx", -999)
    _is_sequential = abs(frame_idx - prev_frame) <= 3
    if (
        eq_centered is not None
        and eq_centroid is not None
        and len(eq_centered) == len(p_nm)
    ):
        _rm = (
            rigid_mask
            if (rigid_mask is not None and rigid_mask.any())
            else (eq_valid if (eq_valid is not None and eq_valid.any()) else None)
        )
        _mob_c = p_nm[_rm].mean(axis=0) if _rm is not None else p_nm.mean(axis=0)
        _mc = p_nm - _mob_c
        _H = _mc.T @ eq_centered
        _U2, _, _Vt2 = np.linalg.svd(_H)
        _d2 = np.linalg.det(_Vt2.T @ _U2.T)
        R_align = _Vt2.T @ np.diag([1.0, 1.0, _d2]) @ _U2.T

        if R_prev is not None and _is_sequential:
            _dR = R_align @ R_prev.T
            _cos = max(-1.0, min(1.0, (float(np.trace(_dR)) - 1.0) / 2.0))
            _angle_deg = np.degrees(np.arccos(_cos))
            if _angle_deg > 60.0:
                _p_nm_raw = _mc @ R_align.T + eq_centroid
                _pre_d = np.linalg.norm(_p_nm_raw - eq_pos, axis=1)
                _med_d = (
                    np.median(_pre_d[_rm]) if _rm is not None else np.median(_pre_d)
                )
                _inlier = (
                    _rm & (_pre_d < _med_d * 3.0)
                    if _rm is not None
                    else (_pre_d < _med_d * 3.0)
                )
                if _inlier.sum() >= 10:
                    _mob_c2 = p_nm[_inlier].mean(axis=0)
                    _mc2 = p_nm - _mob_c2
                    _eq_c2 = eq_pos - eq_centroid
                    _eq_c2[~_inlier] = 0.0
                    _H2 = _mc2.T @ _eq_c2
                    _U3, _, _Vt3 = np.linalg.svd(_H2)
                    _d3 = np.linalg.det(_Vt3.T @ _U3.T)
                    R_inlier = _Vt3.T @ np.diag([1.0, 1.0, _d3]) @ _U3.T
                    _dR2 = R_inlier @ R_prev.T
                    _cos2 = max(-1.0, min(1.0, (float(np.trace(_dR2)) - 1.0) / 2.0))
                    if np.arccos(_cos2) < np.arccos(_cos):
                        R_align = R_inlier
                        _mob_c = _mob_c2
                        _mc = _mc2
        p_nm = _mc @ R_align.T + eq_centroid
        ctx["R_prev"] = R_align
        ctx["prev_frame_idx"] = frame_idx

    return FrameAlignment(p_nm, R_align, _mob_c, _rm)
