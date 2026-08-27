from scripts.benchmark_oxdna_memory import parse_oxdna_log


def test_parses_adaptive_memory_telemetry():
    report = parse_oxdna_log(
        """
INFO: CUDA max_neigh: 64, max_N_per_cell: 2067
INFO: Allocated CUDA memory: 481.56 MBs
INFO: CUDA adaptive neighbour telemetry: 119 observed max, 64 capacity
INFO: CUDA adaptive neighbour list grew to 142 entries per particle (15.96 MBs)
INFO: CUDA adaptive edge list: 947992 observed edges, 1137590 capacity, 8.68 MBs
INFO: Total Running Time: 10.3441 s, per step: 1.03441 ms
"""
    )
    assert report == {
        "allocated_cuda_mb": 481.56,
        "initial_capacity": 64,
        "observed_max_neighbors": 119,
        "grown_capacity": 142,
        "edge_capacity_mb": 8.68,
        "runtime_s": 10.3441,
        "ms_per_step": 1.03441,
    }
