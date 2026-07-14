"""ssDNA topology classifier for the SNUPI FEM — phase SS-0.

`build_fem_mesh` places FEM nodes only at duplex-core base pairs (scaffold ∧ staple),
which matches SNUPI exactly.  Every *single-stranded* nucleotide is therefore absent
from the mesh.  This module enumerates those nucleotides and sorts them into the three
mechanically distinct cases, so the later phases can treat each correctly:

* **bridge** — an ssDNA run with a meshed duplex node on BOTH sides along the strand
  path.  It is load-bearing: it transmits force between two duplexes.  SNUPI collapses
  such a run to a single soft isotropic beam whose rest length is the WLC RMS
  end-to-end distance (NOT the contour).  Today we instead span it with a full-stiffness
  dsDNA beam (same-helix) or a crude Lp=1.5 nm axial spring (cross-helix).  Phase SS-1.

  A bridge is ``interior`` when both anchors sit on the same helix (an unstapled gap) and
  ``hop`` when they sit on different helices (a single-stranded crossover / linker).

* **tail** — an ssDNA run with a meshed duplex node on exactly ONE side: an overhang, a
  toehold, or a dangling scaffold end.  It carries no load between duplexes, so published
  SNUPI cannot represent it at all — its ssDNA element is by construction an *end-to-end
  connection between two base-pair nodes*, and a tail has no distal node to connect to.
  NADOC extends the model here: tails contribute mass, hydrodynamic drag and visible
  thermal motion in the Langevin engine.  Phases SS-2/3/4.

  **Anchor rule (from the user, binding — do not re-derive):** *the tail anchor is
  defined by which end has a crossover into the embedded staple.*  That is the meshed
  neighbour found by walking the strand path; it is NOT fixed to 3' or 5'.  A tail at the
  strand's 5' terminus anchors on its 3' side and vice versa.  Having exactly one meshed
  neighbour is what *makes* a run a tail — that is the discriminator against a bridge.

* **free** — an ssDNA run with NO meshed neighbour: an entire strand that never touches
  the duplex core.  Excluded from the FEM (as today); reported so it is never silently
  dropped.

Read-only: derives Layer-2/3 information from Layer-1 topology and writes nothing back.

See ``memory/project_snupi_ssdna.md`` for the phased plan and the SNUPI ssDNA constants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from backend.core.models import Design
from backend.core.sequences import domain_bp_range

# A nucleotide's identity on a helix: (helix_id, bp, direction). Matches the key the
# renderer/display path uses for a bead, so an ss node can be mapped back to its bead.
NtKey = Tuple[str, int, str]


@dataclass(frozen=True)
class SSAnchor:
    """A meshed duplex base pair that an ssDNA run hangs from / bridges to."""
    helix_id: str
    bp: int


@dataclass
class SSRun:
    """One maximal run of consecutive single-stranded nucleotides along a strand path."""
    kind: str                       # "bridge" | "tail" | "free"
    strand_id: str
    strand_type: str
    nts: List[NtKey]                # 5'→3' order
    anchor_5: Optional[SSAnchor]    # meshed duplex bp immediately 5' of the run
    anchor_3: Optional[SSAnchor]    # meshed duplex bp immediately 3' of the run
    overhang_ids: Tuple[str, ...] = ()

    @property
    def n_nt(self) -> int:
        return len(self.nts)

    @property
    def anchor(self) -> Optional[SSAnchor]:
        """The single meshed neighbour of a TAIL — the end that crosses into the embedded
        staple (the user's anchor rule).  None for a free run; raises for a bridge, which
        has two anchors and must be handled with ``anchor_5``/``anchor_3`` explicitly."""
        if self.kind == "bridge":
            raise ValueError("a bridge has two anchors — use anchor_5 / anchor_3")
        return self.anchor_5 or self.anchor_3

    @property
    def bridge_kind(self) -> Optional[str]:
        """For a bridge: "interior" (both anchors on one helix — an unstapled gap) or
        "hop" (anchors on different helices — a single-stranded crossover/linker)."""
        if self.kind != "bridge":
            return None
        assert self.anchor_5 is not None and self.anchor_3 is not None
        return "interior" if self.anchor_5.helix_id == self.anchor_3.helix_id else "hop"

    @property
    def is_overhang(self) -> bool:
        return bool(self.overhang_ids)


def meshed_bp(design: Design) -> Dict[str, Set[int]]:
    """The exact set of bp that ``build_fem_mesh`` turns into FEM nodes, per helix.

    Mirrors the mesh builder's two conditions: the helix must have a non-degenerate axis,
    and it must carry ≥2 duplex-core bp (fewer → nothing to solve, the helix is skipped).
    Kept in lockstep with ``build_fem_mesh``; the byte-identity test pins that.
    """
    from backend.physics.fem_solver import _MIN_FEM_NODES, _duplex_bp_per_helix

    duplex = _duplex_bp_per_helix(design)
    out: Dict[str, Set[int]] = {}
    for helix in design.helices:
        ax = helix.axis_start, helix.axis_end
        dx = ax[1].x - ax[0].x
        dy = ax[1].y - ax[0].y
        dz = ax[1].z - ax[0].z
        if (dx * dx + dy * dy + dz * dz) ** 0.5 < 1e-9:
            continue
        bps = duplex.get(helix.id, set())
        if len(bps) < _MIN_FEM_NODES:
            continue
        out[helix.id] = set(bps)
    return out


def classify_ssdna_runs(design: Design) -> List[SSRun]:
    """Enumerate every maximal single-stranded run in the design, classified.

    Walks each strand's nucleotide path 5'→3' (domains in order, bp in traversal order),
    marks each nucleotide meshed/unmeshed against :func:`meshed_bp`, and groups the
    unmeshed ones into runs.  The meshed nucleotide bounding each run on either side is
    its anchor; the number of anchors decides the kind (see the module docstring).

    Works at *nucleotide* granularity rather than domain granularity, so a domain that is
    only partially paired splits correctly instead of being classified as a whole.
    """
    nodes = meshed_bp(design)
    runs: List[SSRun] = []

    for strand in design.strands:
        if getattr(strand, "is_reference", False):
            continue

        # The strand's full 5'→3' nucleotide path, each tagged with its overhang (if any).
        path: List[Tuple[NtKey, Optional[str]]] = []
        for dm in strand.domains:
            oh = getattr(dm, "overhang_id", None)
            for bp in domain_bp_range(dm):
                path.append(((dm.helix_id, bp, dm.direction.value), oh))
        if not path:
            continue

        is_meshed = [key[1] in nodes.get(key[0], ()) for key, _ in path]

        i = 0
        n = len(path)
        while i < n:
            if is_meshed[i]:
                i += 1
                continue
            j = i
            while j < n and not is_meshed[j]:
                j += 1
            # path[i:j] is a maximal unmeshed run; its neighbours (if any) are meshed.
            a5 = None
            if i > 0:
                h, bp, _ = path[i - 1][0]
                a5 = SSAnchor(helix_id=h, bp=bp)
            a3 = None
            if j < n:
                h, bp, _ = path[j][0]
                a3 = SSAnchor(helix_id=h, bp=bp)
            n_anchors = (a5 is not None) + (a3 is not None)
            kind = "bridge" if n_anchors == 2 else ("tail" if n_anchors == 1 else "free")
            ohs = tuple(sorted({oh for _, oh in path[i:j] if oh}))
            runs.append(SSRun(
                kind=kind,
                strand_id=strand.id,
                strand_type=strand.strand_type.value,
                nts=[k for k, _ in path[i:j]],
                anchor_5=a5,
                anchor_3=a3,
                overhang_ids=ohs,
            ))
            i = j

    return runs


@dataclass
class SSInventory:
    """Summary counts for one design — what the SS-0 audit reports."""
    n_helices: int = 0
    n_meshed_helices: int = 0
    n_nodes: int = 0
    n_ss_nt: int = 0
    runs: List[SSRun] = field(default_factory=list)

    def of_kind(self, kind: str) -> List[SSRun]:
        return [r for r in self.runs if r.kind == kind]

    def bridges(self, bridge_kind: Optional[str] = None) -> List[SSRun]:
        rs = self.of_kind("bridge")
        return rs if bridge_kind is None else [r for r in rs if r.bridge_kind == bridge_kind]

    def tails(self, *, overhang: Optional[bool] = None) -> List[SSRun]:
        rs = self.of_kind("tail")
        if overhang is None:
            return rs
        return [r for r in rs if r.is_overhang is overhang]


def ssdna_inventory(design: Design) -> SSInventory:
    """Classify every ssDNA run and summarize (the audit's data source)."""
    nodes = meshed_bp(design)
    runs = classify_ssdna_runs(design)
    return SSInventory(
        n_helices=len(design.helices),
        n_meshed_helices=len(nodes),
        n_nodes=sum(len(v) for v in nodes.values()),
        n_ss_nt=sum(r.n_nt for r in runs),
        runs=runs,
    )
