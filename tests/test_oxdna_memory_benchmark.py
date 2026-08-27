from scripts.benchmark_oxdna_memory import parse_oxdna_log, tile_oxdna_system


def test_adaptive_patch_uses_separate_wide_cuda_particle_ids():
    patch = (
        __import__("pathlib").Path(__file__).parents[1]
        / "tools"
        / "oxdna_memory"
        / "adaptive-neighbor-lists.patch"
    ).read_text(encoding="utf-8")

    assert "_d_particle_ids" in patch
    assert "buff_particle_ids[IND] = particle_ids[j]" in patch
    assert "_h_poss[i].w = GpuUtils::int_as_float(p->btype)" in patch
    assert "int newindex = _h_particle_ids[i]" in patch
    added_lines = "\n".join(
        line[1:] for line in patch.splitlines() if line.startswith("+")
    )
    assert "0x003FFFFF" not in added_lines
    assert "get_particle_index(" not in added_lines


def test_parses_adaptive_memory_telemetry():
    report = parse_oxdna_log(
        """
INFO: CUDA max_neigh: 64, max_N_per_cell: 2067
INFO: CUDA Cells mem: 0.45 MBs, lists mem: 0.11 MBs
INFO: Allocated CUDA memory: 481.56 MBs
INFO: CUDA adaptive neighbour telemetry: 119 observed max, 64 capacity
INFO: CUDA adaptive neighbour list grew to 142 entries per particle (15.96 MBs)
INFO: CUDA adaptive edge list: 947992 observed edges, 1137590 capacity, 8.68 MBs
INFO: Total Running Time: 10.3441 s, per step: 1.03441 ms
***> Observables                      0.250 (  2.4%)
"""
    )
    assert report == {
        "allocated_cuda_mb": 481.56,
        "cell_storage_mb": 0.45,
        "initial_capacity": 64,
        "observed_max_neighbors": 119,
        "grown_capacity": 142,
        "grown_neighbor_mb": 15.96,
        "edge_capacity_mb": 8.68,
        "runtime_s": 10.3441,
        "ms_per_step": 1.03441,
        "observables_s": 0.25,
    }


def test_tiles_topology_and_configuration_without_cross_copy_bonds(tmp_path):
    topology = tmp_path / "source.top"
    topology.write_text("2 1\n1 A 1 -1\n1 T -1 0\n", encoding="utf-8")
    configuration = tmp_path / "source.dat"
    configuration.write_text(
        "t = 0\nb = 20 20 20\nE = 0 0 0\n"
        "0 0 0 1 0 0 0 1 0 0 0 0 0 0 0\n"
        "1 0 0 1 0 0 0 1 0 0 0 0 0 0 0\n",
        encoding="utf-8",
    )

    tiled_top, tiled_conf = tile_oxdna_system(
        topology, configuration, 3, tmp_path / "out"
    )
    assert tiled_top.read_text(encoding="utf-8").splitlines() == [
        "6 3",
        "1 A 1 -1",
        "1 T -1 0",
        "2 A 3 -1",
        "2 T -1 2",
        "3 A 5 -1",
        "3 T -1 4",
    ]
    assert len(tiled_conf.read_text(encoding="utf-8").splitlines()) == 9
