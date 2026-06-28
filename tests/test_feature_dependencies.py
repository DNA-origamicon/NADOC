"""Unit tests for backend.core.feature_dependencies (pure dependency analysis)."""
from backend.core.feature_dependencies import (
    EntryInfo,
    analyze_dependents,
    snapshot_delta,
    structural_reference_targets,
)
from backend.core.models import (
    Crossover,
    Design,
    Direction,
    Domain,
    HalfCrossover,
    Helix,
    Strand,
    StrandType,
    Vec3,
)


def _snap(added=(), modified=(), targets=None, reconstructable=False):
    return EntryInfo(
        added=set(added), modified=set(modified),
        targets=None if targets is None else set(targets),
        reconstructable=reconstructable,
    )


# ── analyze_dependents ────────────────────────────────────────────────────────

def test_no_later_entries_has_no_dependents():
    infos = [_snap(added={'h1'}, reconstructable=True)]
    assert analyze_dependents(infos, 0) == []


def test_independent_replayable_later_op_survives():
    # Two parallel extrusions; deleting the first keeps the second (different
    # helices, replayable, no reference).
    infos = [
        _snap(added={'hA'}, targets=set(), reconstructable=True),   # K
        _snap(added={'hB'}, targets=set(), reconstructable=True),   # independent
    ]
    assert analyze_dependents(infos, 0) == []


def test_reference_dependency_is_caught():
    # Later op extends a helix K created (modified ∩ produced) → dependent.
    infos = [
        _snap(added={'hA'}, reconstructable=True),                       # K creates hA
        _snap(modified={'hA'}, targets={'hA'}, reconstructable=True),    # continuation onto hA
    ]
    assert analyze_dependents(infos, 0) == [1]


def test_non_reconstructable_independent_later_op_survives():
    # Non-reconstructable no longer means dependent by itself. A baked snapshot
    # that references nothing K produced can be scrubbed.
    infos = [
        _snap(added={'hA'}, reconstructable=True),                 # K
        _snap(added={'s1'}, targets=set(), reconstructable=False), # auto-scaffold
    ]
    assert analyze_dependents(infos, 0) == []


def test_unknown_targets_treated_as_dependent():
    infos = [
        _snap(added={'hA'}, reconstructable=True),
        _snap(targets=None, reconstructable=True),   # unresolved cluster → unknown
    ]
    assert analyze_dependents(infos, 0) == [1]


def test_transitive_closure():
    # K → L (references K) → M (references L, but not K directly).
    infos = [
        _snap(added={'hA'}, reconstructable=True),                       # K
        _snap(added={'hB'}, targets={'hA'}, reconstructable=True),       # L deps on K, makes hB
        _snap(modified={'hB'}, targets={'hB'}, reconstructable=True),    # M deps on L's hB
    ]
    assert analyze_dependents(infos, 0) == [1, 2]


def test_survivor_between_two_dependents():
    # K creates hA. L depends on hA. P is independent (own helix). M depends on L.
    infos = [
        _snap(added={'hA'}, reconstructable=True),                    # 0 K
        _snap(added={'hB'}, targets={'hA'}, reconstructable=True),    # 1 dep (on hA)
        _snap(added={'hC'}, targets=set(), reconstructable=True),     # 2 independent survivor
        _snap(modified={'hB'}, targets={'hB'}, reconstructable=True), # 3 dep (on hB)
    ]
    assert analyze_dependents(infos, 0) == [1, 3]


def test_delta_entry_independent_survives():
    # A bend scoped to an unrelated helix survives deleting K.
    infos = [
        _snap(added={'hA'}, reconstructable=True),                 # K
        _snap(targets={'hZ'}, reconstructable=True),               # bend on hZ (delta)
    ]
    assert analyze_dependents(infos, 0) == []


def test_delta_entry_on_produced_helix_is_dependent():
    infos = [
        _snap(added={'hA'}, reconstructable=True),                 # K
        _snap(targets={'hA'}, reconstructable=True),               # bend scoped to hA
    ]
    assert analyze_dependents(infos, 0) == [1]


def test_structural_targets_include_added_strand_domain_helix_refs():
    h = Helix(id="h_removed", axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=10), length_bp=10)
    pre = Design(helices=[h], strands=[])
    post = pre.copy_with(strands=[
        Strand(
            id="s_new",
            strand_type=StrandType.STAPLE,
            domains=[Domain(helix_id="h_removed", start_bp=0, end_bp=5, direction=Direction.FORWARD)],
        )
    ])
    added, modified = snapshot_delta(pre, post)

    assert structural_reference_targets(pre, post, added, modified) >= {"h_removed"}


def test_structural_targets_include_added_crossover_endpoint_refs():
    h1 = Helix(id="h_removed", axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=10), length_bp=10)
    h2 = Helix(id="h_survivor", axis_start=Vec3(x=1, y=0, z=0), axis_end=Vec3(x=1, y=0, z=10), length_bp=10)
    pre = Design(helices=[h1, h2])
    post = pre.copy_with(crossovers=[
        Crossover(
            id="xo",
            half_a=HalfCrossover(helix_id="h_removed", index=5, strand=Direction.FORWARD),
            half_b=HalfCrossover(helix_id="h_survivor", index=5, strand=Direction.REVERSE),
        )
    ])
    added, modified = snapshot_delta(pre, post)

    assert structural_reference_targets(pre, post, added, modified) >= {"h_removed", "h_survivor"}
