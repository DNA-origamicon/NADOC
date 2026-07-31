"""The solvent binary wire format.

Decoded by an INDEPENDENT pure-Python reader (the style of
tests/test_atomistic_bundle_bin.py) rather than by calling the packer's own
helpers — a round-trip through shared code proves nothing about the layout the
JavaScript parser has to agree with.
"""

import json
import struct

import numpy as np
import pytest

from backend.core.md_solvent import (
    SPECIES,
    empty_solvent_bin,
    pack_solvent_bin,
)

MAGIC = 0x4E534C56   # "NSLV"


def unpack(buf: bytes) -> dict:
    """Independent reader — mirrors what frontend/src/scene/md_solvent_bin.js does."""
    magic, version, n_frames, reserved = struct.unpack_from("<IIII", buf, 0)
    assert magic == MAGIC, f"bad magic {magic:#x}"
    (header_len,) = struct.unpack_from("<I", buf, 16)
    header = json.loads(buf[20:20 + header_len].decode("utf-8"))
    off = 20 + header_len + ((-header_len) % 4)      # zero-padded to 4 bytes
    assert off % 4 == 0, "float blocks must be 4-byte aligned"

    per_mol = 9 if header["atomistic"] else 3
    n_serials = header.get("n_serials", 0)
    frames = {}
    for i, fid in enumerate(header["frame_ids"]):
        nw = header["per_frame_nw"][i]
        n = nw * per_mol
        water = np.frombuffer(buf, dtype="<f4", count=n, offset=off); off += 4 * n
        n = header["n_ions"] * 3
        ions = np.frombuffer(buf, dtype="<f4", count=n, offset=off); off += 4 * n
        box = None
        if header.get("has_box"):
            box = np.frombuffer(buf, dtype="<f4", count=24, offset=off); off += 4 * 24
        dna = None
        if n_serials:
            n = n_serials * 3
            dna = np.frombuffer(buf, dtype="<f4", count=n, offset=off); off += 4 * n
        frames[fid] = {"water": water, "ions": ions, "box": box, "dna": dna}
    assert off == len(buf), f"trailing bytes: read {off} of {len(buf)}"
    return {"version": version, "n_frames": n_frames, "reserved": reserved,
            "header": header, "frames": frames}


def make_frame(nw, n_ions, *, atomistic=False, seed=0, has_box=True, **kw):
    """A frame whose blocks and header counts AGREE — which is the contract the
    packer asserts, and the thing v1 got wrong."""
    rng = np.random.default_rng(seed)
    per_mol = 9 if atomistic else 3
    f = {
        "water": rng.normal(size=nw * per_mol).astype(np.float32),
        "ions": rng.normal(size=n_ions * 3).astype(np.float32),
        "box": rng.normal(size=24).astype(np.float32) if has_box else np.zeros(0, np.float32),
        "ion_species": np.arange(n_ions, dtype=np.uint8) % len(SPECIES),
        "n_water": nw, "n_ions": n_ions, "n_ions_total": max(n_ions, 7),
        "n_waters_total": nw * 10, "has_box": has_box,
        "atomistic": atomistic, "capped": False, "shell_nm": 0.5,
    }
    f.update(kw)
    return f


class TestRoundTrip:
    def test_single_frame_sphere_mode(self):
        f = make_frame(5, 3)
        got = unpack(pack_solvent_bin({0: f}))
        assert got["n_frames"] == 1
        assert got["header"]["frame_ids"] == [0]
        assert got["header"]["atomistic"] is False
        np.testing.assert_array_equal(got["frames"][0]["water"], f["water"])
        np.testing.assert_array_equal(got["frames"][0]["ions"], f["ions"])
        np.testing.assert_array_equal(got["frames"][0]["box"], f["box"])

    def test_atomistic_mode_ships_nine_floats_per_molecule(self):
        f = make_frame(4, 2, atomistic=True)
        got = unpack(pack_solvent_bin({0: f}))
        assert got["header"]["atomistic"] is True
        assert got["frames"][0]["water"].size == 4 * 9

    def test_multiple_frames_keep_their_composite_ids_and_order(self):
        frames = {7: make_frame(3, 2, seed=1), 2: make_frame(5, 2, seed=2),
                  11: make_frame(1, 2, seed=3)}
        got = unpack(pack_solvent_bin(frames))
        assert got["header"]["frame_ids"] == [2, 7, 11]      # sorted numerically
        assert got["header"]["per_frame_nw"] == [5, 3, 1]
        for fid in (2, 7, 11):
            np.testing.assert_array_equal(got["frames"][fid]["water"], frames[fid]["water"])

    # A hydration shell is a DIFFERENT molecule set each frame, so the per-frame
    # water block length varies. The header's per_frame_nw is what lets the reader
    # walk the blocks at all.
    def test_variable_water_count_per_frame(self):
        frames = {0: make_frame(2, 1, seed=4), 1: make_frame(9, 1, seed=5)}
        got = unpack(pack_solvent_bin(frames))
        assert got["frames"][0]["water"].size == 2 * 3
        assert got["frames"][1]["water"].size == 9 * 3

    def test_ion_species_ride_the_header_once(self):
        f = make_frame(2, 4)
        got = unpack(pack_solvent_bin({0: f}))
        assert got["header"]["ion_species"] == list(f["ion_species"])
        assert got["header"]["species_table"] == list(SPECIES)

    def test_capped_and_shell_are_reported(self):
        f = make_frame(2, 1, capped=True, shell_nm=0.8)
        got = unpack(pack_solvent_bin({0: f}))
        assert got["header"]["capped"] is True
        assert got["header"]["shell_nm"] == pytest.approx(0.8)


class TestLayout:
    def test_magic_and_version(self):
        magic, version = struct.unpack_from("<II", pack_solvent_bin({0: make_frame(1, 1)}), 0)
        assert magic == MAGIC
        assert version == 2

    # A JSON header of arbitrary byte length would leave the float blocks at an
    # unaligned offset, and `new Float32Array(buf, offset)` throws in JS unless
    # offset % 4 == 0.
    @pytest.mark.parametrize("pad_key_len", range(1, 9))
    def test_float_blocks_are_four_byte_aligned_for_any_header_length(self, pad_key_len):
        f = make_frame(2, 1)
        buf = pack_solvent_bin({0: f}, meta={"x" * pad_key_len: 1})
        (header_len,) = struct.unpack_from("<I", buf, 16)
        assert (20 + header_len + ((-header_len) % 4)) % 4 == 0
        unpack(buf)                    # and it decodes

    def test_no_trailing_bytes(self):
        unpack(pack_solvent_bin({0: make_frame(3, 2), 1: make_frame(4, 2)}))

    def test_water_precedes_ions_precedes_box(self):
        # Distinct sentinel values so a mis-ordered read is unmissable.
        f = make_frame(2, 2)
        f["water"] = np.full(6, 1.0, dtype=np.float32)
        f["ions"] = np.full(6, 2.0, dtype=np.float32)
        f["box"] = np.full(24, 3.0, dtype=np.float32)
        got = unpack(pack_solvent_bin({0: f}))["frames"][0]
        assert set(got["water"].tolist()) == {1.0}
        assert set(got["ions"].tolist()) == {2.0}
        assert set(got["box"].tolist()) == {3.0}


class TestIncludeDna:
    """The `include_dna` piggyback: DNA coordinates ride the SAME request so the
    ~30 s MDAnalysis context build is paid once per chunk, not twice."""

    def test_dna_block_round_trips(self):
        f = make_frame(3, 2)
        f["dna"] = np.arange(12, dtype=np.float32)      # 4 serials × 3
        got = unpack(pack_solvent_bin({0: f}, meta={"n_serials": 4}))
        assert got["header"]["n_serials"] == 4
        np.testing.assert_array_equal(got["frames"][0]["dna"], np.arange(12))

    def test_dna_block_is_absent_by_default(self):
        got = unpack(pack_solvent_bin({0: make_frame(3, 2)}))
        assert got["header"]["n_serials"] == 0
        assert got["frames"][0]["dna"] is None

    def test_short_dna_input_is_zero_filled_not_truncated(self):
        # Serial-indexed arrays are sparse: an absent serial must read as 0,0,0
        # rather than shifting every later atom.
        f = make_frame(1, 1)
        f["dna"] = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        got = unpack(pack_solvent_bin({0: f}, meta={"n_serials": 3}))
        np.testing.assert_array_equal(got["frames"][0]["dna"],
                                      [1, 2, 3, 0, 0, 0, 0, 0, 0])

    def test_dna_follows_the_box_block(self):
        f = make_frame(1, 1)
        f["water"] = np.full(3, 1.0, dtype=np.float32)
        f["ions"] = np.full(3, 2.0, dtype=np.float32)
        f["box"] = np.full(24, 3.0, dtype=np.float32)
        f["dna"] = np.full(6, 4.0, dtype=np.float32)
        got = unpack(pack_solvent_bin({0: f}, meta={"n_serials": 2}))["frames"][0]
        assert set(got["box"].tolist()) == {3.0}
        assert set(got["dna"].tolist()) == {4.0}


class TestEmpty:
    def test_empty_payload_is_a_bare_header(self):
        buf = empty_solvent_bin()
        got = unpack(buf)
        assert got["n_frames"] == 0
        assert got["header"]["frame_ids"] == []
        assert got["frames"] == {}

    def test_empty_payload_still_carries_the_species_table(self):
        assert unpack(empty_solvent_bin())["header"]["species_table"] == list(SPECIES)

    def test_a_frame_with_no_water_is_valid(self):
        f = make_frame(0, 3)
        got = unpack(pack_solvent_bin({0: f}))
        assert got["frames"][0]["water"].size == 0
        assert got["frames"][0]["ions"].size == 9


class TestIndependentToggles:
    """Water / Ions / Box are independent checkboxes, so ANY subset can be absent.

    v1 wrote an empty block for a disabled species while still advertising the full
    count in the header, so every read after the gap landed at the wrong offset and
    the client got null — Water-alone and Ions-alone silently drew nothing, and only
    the all-three-on combination happened to line up. These cover the whole lattice.
    """

    @pytest.mark.parametrize("water", [True, False])
    @pytest.mark.parametrize("ions", [True, False])
    @pytest.mark.parametrize("box", [True, False])
    def test_every_combination_round_trips(self, water, ions, box):
        f = make_frame(4 if water else 0, 3 if ions else 0, has_box=box)
        got = unpack(pack_solvent_bin({0: f}))
        fr = got["frames"][0]
        assert fr["water"].size == (12 if water else 0)
        assert fr["ions"].size == (9 if ions else 0)
        assert (fr["box"] is not None) == box
        if box:
            np.testing.assert_array_equal(fr["box"], f["box"])

    def test_header_counts_describe_what_was_written(self):
        got = unpack(pack_solvent_bin({0: make_frame(0, 0, has_box=False)}))
        assert got["header"]["n_ions"] == 0
        assert got["header"]["has_box"] is False
        # …while the TOTALS still report what the system actually holds, so the
        # panel can say "N of M molecules" with the species toggled off.
        assert got["header"]["n_ions_total"] == 7

    def test_water_only_is_readable(self):
        """The exact combination that was reported broken."""
        got = unpack(pack_solvent_bin({0: make_frame(5, 0, has_box=False)}))
        assert got["frames"][0]["water"].size == 15
        assert got["frames"][0]["ions"].size == 0
        assert got["frames"][0]["box"] is None

    def test_ions_only_is_readable(self):
        got = unpack(pack_solvent_bin({0: make_frame(0, 6, has_box=False)}))
        assert got["frames"][0]["ions"].size == 18
        assert got["frames"][0]["water"].size == 0

    def test_box_only_is_readable(self):
        got = unpack(pack_solvent_bin({0: make_frame(0, 0, has_box=True)}))
        assert got["frames"][0]["box"].size == 24
        assert got["frames"][0]["water"].size == 0
        assert got["frames"][0]["ions"].size == 0

    def test_mixed_combinations_across_multiple_frames(self):
        frames = {0: make_frame(3, 2, has_box=True, seed=1),
                  1: make_frame(7, 2, has_box=True, seed=2)}
        got = unpack(pack_solvent_bin(frames))
        assert got["header"]["per_frame_nw"] == [3, 7]

    # The packer refuses to emit a blob whose header contradicts its blocks, so a
    # future caller cannot reintroduce the desync silently.
    def test_packer_rejects_a_header_block_mismatch(self):
        bad = make_frame(2, 3)
        bad["ions"] = np.zeros(0, dtype=np.float32)    # claims 3, writes none
        with pytest.raises(AssertionError):
            pack_solvent_bin({0: bad})

    def test_packer_rejects_a_box_mismatch(self):
        bad = make_frame(2, 1, has_box=True)
        bad["box"] = np.zeros(0, dtype=np.float32)
        with pytest.raises(AssertionError):
            pack_solvent_bin({0: bad})


class TestVersion:
    def test_version_is_two(self):
        """Bumped when blocks became optional — a stale client must fail closed."""
        assert struct.unpack_from("<I", pack_solvent_bin({0: make_frame(1, 1)}), 4)[0] == 2
