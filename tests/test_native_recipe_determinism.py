"""Separate processes may not depend on UUID or Python set iteration state."""

import os
import subprocess
import sys


def test_routing_recipe_is_identical_across_python_hash_seeds():
    script = """
from backend.api.part_proof_commands import execute
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS, digest
d = create_empty_part("Bundle", "SQUARE")
commands = [
 ("bundle-create", {"history_seed": "06efb9b1-c6c5-4c0f-b1a7-82ec5c25b28a", "cells": [[r,c] for r in range(3) for c in range(2)], "length_bp": 96, "lattice_type": "SQUARE"}),
 ("auto-scaffold-seamed", {}),
 ("full-autostaple", {"custom_sequence": "ACGT" * 300}),
 ("extrude-segment", {"history_seed": "22411080-0442-40ee-aa20-291bc470a12a", "cells": [[8,8],[8,9]], "length_bp": 42}),
]
for kind, p in commands:
 d = execute(kind, d, {"history_seed": "501af50e-aa0f-4fac-8ebf-12903299a99a", **p, "_proof_version": 1})
print(digest(d.model_dump(mode="json", include=AUTHORING_FIELDS)))
"""
    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", script],
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
            timeout=30,
        ).strip()
        for seed in ("1", "2")
    ]
    assert outputs[0] == outputs[1]


def test_routing_namespace_is_nested_and_thread_local():
    from concurrent.futures import ThreadPoolExecutor
    from backend.core.routing_identity import crossover, identity_scope
    from backend.core.models import HalfCrossover, Direction

    halves = dict(
        half_a=HalfCrossover(helix_id="a", index=4, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="b", index=4, strand=Direction.REVERSE),
    )
    a, b = (
        "7babfe51-cbc2-44cc-a593-fcfd87e29512",
        "39231e9c-54c4-4579-bf6c-7a43a7ea9200",
    )

    def make(seed):
        with identity_scope(seed):
            return crossover(**halves).id

    assert crossover(**halves).id != crossover(**halves).id
    with identity_scope(a):
        expected = crossover(**halves).id
        assert make(b) != expected
        assert crossover(**halves).id == expected
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(make, [a, b])) == [expected, make(b)]
        try:
            with identity_scope(b):
                raise ValueError("interrupted")
        except ValueError:
            pass
        assert crossover(**halves).id == expected
    assert crossover(**halves).id != expected
