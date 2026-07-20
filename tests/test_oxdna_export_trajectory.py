"""Unit tests for the pure helpers behind POST /oxdna/jobs/{id}/export-trajectory
(the composite-trajectory range exporter). The heavy composite/atomistic paths are
integration-only; here we pin the small, fast, format-critical helpers."""

from backend.api.routes_oxdna import (
    _strided_indices,
    _dat_particle_line,
    _assemble_multiframe_pdb,
    _export_stem,
)


class TestStridedIndices:
    def test_full_range_when_under_cap(self):
        assert _strided_indices(10, 15, 120) == [10, 11, 12, 13, 14]

    def test_half_open(self):
        # [lo, hi) — hi is exclusive
        assert _strided_indices(0, 3, 120) == [0, 1, 2]

    def test_strides_down_to_cap_without_exceeding_hi(self):
        out = _strided_indices(0, 1000, 10)
        assert len(out) == 10
        assert out[0] == 0
        assert max(out) < 1000          # never emits an out-of-range index
        assert out == sorted(out)       # monotonic

    def test_empty_when_lo_ge_hi(self):
        assert _strided_indices(5, 5, 120) == []


class TestDatParticleLine:
    def test_exact_oxdna_format(self):
        line = _dat_particle_line((1.0, 2.0, 3.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        assert line == (
            "1.000000 2.000000 3.000000  "
            "1.000000 0.000000 0.000000  "
            "0.000000 0.000000 1.000000  "
            "0.000000 0.000000 0.000000  0.000000 0.000000 0.000000"
        )
        # 15 floats: pos(3) + a1(3) + a3(3) + v(3) + L(3)
        assert len(line.split()) == 15


class _FakeAtom:
    def __init__(self):
        self.x = self.y = self.z = 0.0


class _FakeModel:
    def __init__(self, n_atoms):
        self.atoms = [_FakeAtom() for _ in range(n_atoms)]


class TestAssembleMultiframePdb:
    def _export_pdb_stub(self, design, model=None, viewer_terminals=False):
        # emit one ATOM line per atom (coords from the stamped model) + a TER + CONECT + END
        lines = []
        for i, a in enumerate(model.atoms):
            lines.append(f"ATOM  {i:5d}  C   AAA A   1    {a.x:8.3f}{a.y:8.3f}{a.z:8.3f}")
        lines.append("TER")
        lines.append("CONECT    0    1")
        lines.append("END")
        return "\n".join(lines) + "\n"

    def test_wraps_each_frame_in_model_endmdl_with_single_conect(self):
        model = _FakeModel(2)
        flats = {
            "0": [0, 0, 0, 1, 1, 1],
            "2": [2, 2, 2, 3, 3, 3],
        }
        out = _assemble_multiframe_pdb(None, model, flats, [0, 2], self._export_pdb_stub)
        assert out.count("MODEL") == 2
        assert out.count("ENDMDL") == 2
        assert out.count("CONECT") == 1          # bonds constant → emitted once
        assert out.strip().endswith("END")
        # per-frame coordinates were stamped (frame 2's first atom sits at x=2.000)
        models = out.split("MODEL")
        assert "2.000" in models[2]

    def test_skips_frames_whose_flat_mismatches_topology(self):
        model = _FakeModel(2)
        flats = {"0": [0, 0, 0, 1, 1, 1], "1": [9, 9, 9]}  # idx 1 wrong length
        out = _assemble_multiframe_pdb(None, model, flats, [0, 1], self._export_pdb_stub)
        assert out.count("MODEL") == 1

    def test_empty_when_no_frames_survive(self):
        assert _assemble_multiframe_pdb(None, _FakeModel(2), {}, [0, 1], self._export_pdb_stub) == ""

    def test_progress_fires_once_per_index_including_skipped_frames(self):
        # The bar advances per index processed (not per valid frame), so a skipped
        # frame still ticks — otherwise a partly-invalid range would stall the bar.
        model = _FakeModel(2)
        flats = {"0": [0, 0, 0, 1, 1, 1], "1": [9, 9, 9]}   # idx 1 wrong length → skipped
        calls = []
        _assemble_multiframe_pdb(None, model, flats, [0, 1], self._export_pdb_stub,
                                 progress=lambda done, total: calls.append((done, total)))
        assert calls == [(1, 2), (2, 2)]                    # reaches total even with a skip


class TestExportStem:
    def test_sanitizes_design_name(self):
        class _Meta:
            name = "My Design/v2 *final*"

        class _Design:
            metadata = _Meta()

        assert _export_stem(object(), _Design()) == "My_Design_v2__final_"

    def test_falls_back_to_job_id(self):
        class _Design:
            metadata = None

        class _Job:
            job_id = "abc123"

        assert _export_stem(_Job(), _Design()) == "abc123"
