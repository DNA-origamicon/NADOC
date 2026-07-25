"""Unit tests for the pure helpers behind POST /oxdna/jobs/{id}/export-trajectory
(the composite-trajectory range exporter). The heavy composite/atomistic paths are
integration-only; here we pin the small, fast, format-critical helpers."""

from backend.api.routes_oxdna import (
    _strided_indices,
    _dat_particle_line,
    _assemble_multiframe_pdb,
    _render_model_block,
    _export_stem,
)
from backend.core.pdb_export import build_multiframe_pdb_template


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


class TestMultiframePdbTemplate:
    """The template renders each frame by splicing ONLY PDB columns 31-54 into text captured
    from a single export_pdb() render, instead of re-rendering (~6 s/frame on a 330k-atom
    design, most of it regenerating a CONECT block the caller then discards).

    Every test here compares against `_render_model_block` — the authoritative slow renderer —
    because "fast and subtly different" is the failure mode that matters: a mis-mapped splice
    would corrupt coordinates silently in a file the user takes to ChimeraX.
    """

    def _export_pdb_stub(self, design, model=None, viewer_terminals=False):
        # Column-accurate: coords occupy [30:54] exactly as _pdb_atom_record writes them,
        # in Angstroms (the model carries nm), with a suffix after column 54.
        lines = ["REMARK  stub", "CRYST1  100.000  100.000  100.000  90.00  90.00  90.00"]
        for i, a in enumerate(model.atoms):
            lines.append(
                f"ATOM  {i + 1:5d}  C   AAA A   1    "
                f"{a.x * 10.0:8.3f}{a.y * 10.0:8.3f}{a.z * 10.0:8.3f}"
                f"  1.00  0.00           C  ")
        lines.append("TER")
        lines.append("CONECT    1    2")
        lines.append("END")
        return "\n".join(lines) + "\n"

    def _model(self, n):
        m = _FakeModel(n)
        for i, a in enumerate(m.atoms):
            a.serial = i
        return m

    def test_coords_land_in_columns_31_to_54(self):
        model = self._model(1)
        tpl = build_multiframe_pdb_template(None, model, self._export_pdb_stub)
        block = tpl.model_block([1.5, -2.25, 3.0], 1)
        atom_line = [ln for ln in block.splitlines() if ln.startswith("ATOM")][0]
        assert atom_line[30:54] == f"{15.0:8.3f}{-22.5:8.3f}{30.0:8.3f}"
        assert atom_line[:30].startswith("ATOM")
        assert atom_line[54:] == "  1.00  0.00           C  "

    def test_block_is_byte_identical_to_the_authoritative_renderer(self):
        model = self._model(4)
        tpl = build_multiframe_pdb_template(None, model, self._export_pdb_stub)
        flat = [0.1, 0.2, 0.3, -1.0, 2.5, 3.75, 10.0, -20.0, 30.125, 0.0, 0.0, 0.0]
        for model_no in (1, 7, 240):
            expected, _ = _render_model_block(None, model, flat, self._export_pdb_stub, model_no)
            assert tpl.model_block(flat, model_no) == expected

    def test_full_document_matches_the_legacy_non_streaming_builder(self):
        # The streaming route emits: frame-1 block (slow renderer) + template blocks + CONECT
        # + END. That must reproduce _assemble_multiframe_pdb byte-for-byte.
        model = self._model(3)
        flats = {
            "0": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0],
            "1": [0.5, 0.5, 0.5, 1.5, 1.5, 1.5, 2.5, 2.5, 2.5],
            "2": [9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        }
        indices = [0, 1, 2]
        legacy = _assemble_multiframe_pdb(None, model, flats, indices, self._export_pdb_stub)

        tpl = build_multiframe_pdb_template(None, model, self._export_pdb_stub)
        first_block, conect = _render_model_block(
            None, model, flats["0"], self._export_pdb_stub, 1)
        streamed = first_block
        for n, idx in enumerate(indices[1:], start=2):
            streamed += tpl.model_block(flats[str(idx)], n)
        streamed += "\n".join([*conect, "END"]) + "\n"

        assert streamed == legacy

    def test_returns_none_when_atom_count_disagrees(self):
        # The splitter assumes the k-th ATOM line is model.atoms[k]. If a renderer ever
        # filters or reorders, it must return None (-> caller falls back), never mis-map.
        def _short(design, model=None, viewer_terminals=False):
            return "ATOM      1  C   AAA A   1       0.000   0.000   0.000\nEND\n"

        assert build_multiframe_pdb_template(None, self._model(5), _short) is None

    def test_returns_none_for_a_multi_model_source(self):
        def _multi(design, model=None, viewer_terminals=False):
            return "MODEL        1\nATOM      1  C   AAA A   1       0.000   0.000   0.000\nENDMDL\nEND\n"

        assert build_multiframe_pdb_template(None, self._model(1), _multi) is None

    def test_header_and_conect_are_captured_out_of_the_body(self):
        tpl = build_multiframe_pdb_template(None, self._model(2), self._export_pdb_stub)
        assert any(ln.startswith("REMARK") for ln in tpl.header)
        assert any(ln.startswith("CRYST1") for ln in tpl.header)
        assert tpl.conect == ["CONECT    1    2"]
        # END is dropped (re-emitted after the last model) and no header leaks into a block.
        block = tpl.model_block([0.0] * 6, 1)
        assert "REMARK" not in block and "CRYST1" not in block
        assert "CONECT" not in block and "\nEND\n" not in block


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


class TestCompositeTrajectoryAtomisticProgress:
    """The per-frame all-atom rebuild is the LONG pole of an export (~17 s/frame on a
    16k-nt design). Without this callback the whole pass ran inside the caller's opaque
    "align" phase, so the progress bar sat frozen at 0/N for 15+ minutes and read as a
    hung export. The heavy rebuild itself is integration-only — here we stub it out and
    pin only that the callback is wired and counts correctly."""

    def _patch(self, monkeypatch, n_ordered):
        from backend.core import oxdna_health as oh

        monkeypatch.setattr(oh, "_aligned_downsampled_frames",
                            lambda *a, **k: (None, [{} for _ in range(n_ordered)], None, None))
        monkeypatch.setattr(oh, "_aligned_cache_key", lambda *a, **k: "key")
        monkeypatch.setattr(oh, "frame_atomistic_flat", lambda design, frame: [1.0, 2.0, 3.0])
        # Bypass the shared display cache so this test can't be perturbed by, or pollute, it.
        monkeypatch.setattr(oh, "_display_out_get", lambda key: None)
        monkeypatch.setattr(oh, "_display_out_put", lambda key, payload: None)
        return oh

    def test_progress_fires_once_per_requested_frame(self, monkeypatch):
        oh = self._patch(monkeypatch, n_ordered=5)
        calls = []
        out = oh.composite_trajectory_atomistic(
            None, [], None, [0, 2, 4],
            progress=lambda done, total: calls.append((done, total)))
        assert calls == [(1, 3), (2, 3), (3, 3)]
        assert sorted(out) == ["0", "2", "4"]

    def test_out_of_range_indices_still_advance_the_bar_to_100pct(self, monkeypatch):
        # A range overrunning the trajectory must not stall the bar short of total —
        # skipped indices produce no output but still tick.
        oh = self._patch(monkeypatch, n_ordered=2)
        calls = []
        out = oh.composite_trajectory_atomistic(
            None, [], None, [0, 1, 7],
            progress=lambda done, total: calls.append((done, total)))
        assert calls[-1] == (3, 3)
        assert sorted(out) == ["0", "1"]      # index 7 dropped, but it counted

    def test_absent_callback_is_optional(self, monkeypatch):
        oh = self._patch(monkeypatch, n_ordered=3)
        assert sorted(oh.composite_trajectory_atomistic(None, [], None, [0, 1])) == ["0", "1"]
