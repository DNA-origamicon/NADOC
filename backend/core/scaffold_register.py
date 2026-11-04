"""Fixed-route scaffold register scoring (Aksel et al., PNAS 2024).

Equations and assumptions: docs/scaffold_register.md. No routing mutations.
The vectorized kernel uses O(N) scratch memory, not N copies of a Design.
"""
from dataclasses import dataclass
import math
import numpy as np
from backend.core.models import Direction, StrandType
from backend.core.sequences import (
    _build_loop_skip_map, domain_bp_range, assign_staple_sequences, _SCAFFOLD_BY_NAME,
    strand_partner_bases, build_scaffold_base_map, build_overhang_bp_bases,
)

R = 8.31447 / 4.184 / 1000  # kcal mol^-1 K^-1, reference implementation
# SantaLucia & Hicks 2004; deliberately NOT the older NADOC Tm table.
NN = {
    'AA': (-7.6, -21.3), 'TT': (-7.6, -21.3), 'AT': (-7.2, -20.4),
    'TA': (-7.2, -21.3), 'CA': (-8.5, -22.7), 'TG': (-8.5, -22.7),
    'GT': (-8.4, -22.4), 'AC': (-8.4, -22.4), 'CT': (-7.8, -21.0),
    'AG': (-7.8, -21.0), 'GA': (-8.2, -22.2), 'TC': (-8.2, -22.2),
    'CG': (-10.6, -27.2), 'GC': (-9.8, -24.4),
    'GG': (-8.0, -19.9), 'CC': (-8.0, -19.9),
}


@dataclass(frozen=True)
class Conditions:
    temperature_c: float = 50.0
    scaffold_nM: float = 10.0
    staple_nM: float = 100.0
    magnesium_mM: float = 12.5
    tris_mM: float = 40.0

    def __post_init__(self):
        if not all(math.isfinite(x) for x in vars(self).values()):
            raise ValueError('Conditions must be finite.')
        if not 0 <= self.temperature_c <= 100:
            raise ValueError('Temperature must be between 0 and 100 °C.')
        if self.scaffold_nM <= 0 or self.staple_nM <= self.scaffold_nM / 2:
            raise ValueError('Staple concentration must exceed half the positive scaffold concentration.')
        if self.magnesium_mM < 0 or self.tris_mM < 0 or self.salt <= 0:
            raise ValueError('Salt concentrations must be nonnegative, with at least one positive.')

    @property
    def temperature(self):
        return self.temperature_c + 273.15

    @property
    def salt(self):
        return 0.5 * self.tris_mM / 1000 + 3.3 * math.sqrt(self.magnesium_mM / 1000)


def loop_energy(distance, temperature):
    """Reference wormlike-chain mean-square distance and closure concentration."""
    if distance <= 0:
        raise ValueError('Distinct duplex domains have coincident scaffold centers.')
    contour = 0.6 * distance
    r2 = 1.8 * contour * (1 - 0.9 / contour * (1 - math.exp(-contour / 0.9)))
    concentration = (3 / (2 * math.pi * r2 * 1e-18)) ** 1.5 / 6.02e23 / 1000
    return -R * temperature * math.log(concentration)


def score_registers(sequence, staples, conditions=Conditions(), *, circular=True):
    """Return Q for all offsets; staples contain ordered duplex index lists.

    Each duplex follows a contiguous scaffold interval (either polarity).
    Circular windows may cross index zero. Exact domain midpoints are unwrapped
    before taking circular distances, so the symbolic origin cannot affect them.
    Higher Q = sum(log(p_staple))/paired_nt is better. Q is not a yield.
    """
    sequence = sequence.upper()
    n = len(sequence)
    if n < 2 or set(sequence) - set('ACGT'):
        raise ValueError('A complete A/C/G/T scaffold sequence is required.')
    if not staples:
        raise ValueError('No paired staples to score.')
    t = conditions.temperature
    rt = R * t
    salt = 0.368 * math.log(conditions.salt)
    # The reverse-complement duplex has identical NN energy.
    pairs = [sequence[i] + sequence[(i + 1) % n] for i in range(n)]
    energy = np.array([NN[p][0] - t * NN[p][1] / 1000 for p in pairs])
    prefix = np.concatenate(([0.0], np.cumsum(np.tile(energy, 2))))
    terminal = np.array([b in 'AT' for b in sequence], dtype=float)
    offsets = np.arange(n)
    score = np.zeros(n)
    paired_nt = 0
    binding = -rt * math.log((conditions.staple_nM - 0.5 * conditions.scaffold_nM) * 1e-9)
    for domains in staples:
        if not domains:
            raise ValueError('Each staple must contain paired duplex domains.')
        total = np.full(n, binding)
        centers = []
        for indices in domains:
            indices = np.asarray(indices, dtype=int)
            length = len(indices)
            if not length or length > n or np.any(indices < 0) or np.any(indices >= n):
                raise ValueError('Invalid duplex scaffold indices.')
            if length > 1:
                diff = np.diff(indices) % n
                if np.all(diff == n - 1):
                    indices = indices[::-1]
                elif not np.all(diff == 1):
                    raise ValueError('Duplex must be contiguous on the scaffold.')
            start = int(indices[0])
            centers.append((start + (length - 1) / 2) % n)
            pos = (offsets + start) % n
            total += prefix[pos + length - 1] - prefix[pos]
            total += 0.2 - t * (-5.7 + salt * (length - 1)) / 1000
            ends = terminal[pos].copy()
            if length > 1:
                ends += terminal[(pos + length - 1) % n]
            total += ends * (2.2 - t * 6.9 / 1000)
            paired_nt += length
        for a, b in zip(centers, centers[1:]):
            distance = abs(b - a)
            if circular:
                distance = min(distance, n - distance)
            total += loop_energy(distance, t)
        # Stable even when direct exp(-dG/RT) would overflow or round p to one.
        score -= np.logaddexp(0, total / rt)
    return score / paired_nt


def prepare_design(design):
    """Extract a single closed route with a symbolic sequence origin and antiparallel duplex domains.

    The first release requires the entire physical scaffold in the model. No
    invented wrap bond between distant ends, omitted source tails or N padding.
    """
    scaffolds = [s for s in design.strands if s.is_scaffold and not s.is_reference]
    if len(scaffolds) != 1:
        raise ValueError('This experiment requires exactly one active scaffold.')
    scaffold = scaffolds[0]
    ls = _build_loop_skip_map(design)
    sites = []
    locations = []
    for di, domain in enumerate(scaffold.domains):
        if domain.overhang_id or domain.binds_overhang_id:
            raise ValueError('Scaffold overhang domains are not supported by this experiment.')
        for bp in domain_bp_range(domain):
            for copy in range(max(0, ls.get((domain.helix_id, bp), 0) + 1)):
                sites.append((domain.helix_id, bp, domain.direction, copy))
                locations.append((di, bp))
    n = len(sites)
    sequence = (scaffold.sequence or '').upper()
    if n < 2 or len(sequence) != n or set(sequence) - set('ACGT'):
        raise ValueError('Assign a complete A/C/G/T scaffold sequence before running the sweep.')
    if scaffold.custom_scaffold_length and scaffold.custom_scaffold_length != n:
        raise ValueError('Model the full physical scaffold, including its unused tail, before moving its sequence origin.')
    if scaffold.custom_scaffold_length is None and n >= 32:
        for name, source in _SCAFFOLD_BY_NAME.items():
            if n < len(source) and sequence in source + source:
                raise ValueError(f'The stored sequence is a {n}-nt fragment of {name} ({len(source)} nt). Model the full circular scaffold, or explicitly assign a complete custom scaffold of this length, before optimizing its start.')
    if len(set(sites)) != n:
        raise ValueError('Scaffold visits the same nucleotide more than once.')

    def ordinary(a, b):
        return (a[0] == b[0] and a[2] == b[2] and a[3] == b[3] == 0
                and b[1] - a[1] == (1 if a[2] == Direction.FORWARD else -1)
                and ls.get((a[0], a[1]), 0) == ls.get((b[0], b[1]), 0) == 0)

    if not ordinary(sites[-1], sites[0]):
        raise ValueError('The current scaffold ends must form a co-linear, adjacent nick on the same helix. Open-ended routes cannot be re-cut without rerouting.')
    lookup = {site: i for i, site in enumerate(sites)}
    paired = set()
    staples = []
    ignored_nt = 0
    for strand in design.strands:
        if strand.is_reference or strand.strand_type != StrandType.STAPLE:
            continue
        runs, run, previous = [], [], None
        path = []
        for domain in strand.domains:
            for bp in domain_bp_range(domain):
                copies = max(0, ls.get((domain.helix_id, bp), 0) + 1)
                for copy in reversed(range(copies)):
                    opposite = Direction.REVERSE if domain.direction == Direction.FORWARD else Direction.FORWARD
                    idx = None if domain.overhang_id or domain.binds_overhang_id else lookup.get((domain.helix_id, bp, opposite, copy))
                    if idx is not None and copies > 1:
                        raise ValueError('Paired insertion bases are not supported by this experimental register mapper. Unpaired scaffold insertions and skips are supported.')
                    path.append((idx, domain.helix_id, domain.direction))
        bound = [j for j, p in enumerate(path) if p[0] is not None]
        if not bound:
            continue
        if any(path[j][0] is None for j in range(bound[0], bound[-1]+1)):
            raise ValueError('Internal unpaired staple bridges are not supported by the Aksel duplex model.')
        ignored_nt += len(path) - len(bound)
        for idx, helix, direction in path:
            if idx is None:
                continue
            if idx in paired:
                raise ValueError('Multiple staple bases compete for the same scaffold nucleotide.')
            paired.add(idx)
            if previous is not None and (helix != previous[1] or direction != previous[2] or (previous[0]-idx) % n != 1):
                runs.append(run)
                run = []
            run.append(idx)
            previous = (idx, helix, direction)
        if run:
            runs.append(run)
        staples.append(runs)
    if not staples:
        raise ValueError('Route staples before evaluating scaffold nick positions.')
    cuts = [i for i in range(n) if ordinary(sites[i-1], sites[i])]
    return scaffold, sequence, staples, cuts, sites, locations, ignored_nt


def evaluate_design(design, conditions=Conditions()):
    from time import perf_counter
    started = perf_counter()
    scaffold, sequence, staples, cuts, sites, _, ignored = prepare_design(design)
    all_scores = score_registers(sequence, staples, conditions, circular=True)
    scores = all_scores[(-np.asarray(cuts)) % len(sequence)]
    baseline = float(scores[cuts.index(0)])
    order = np.argsort(-scores, kind='stable')
    # Prefix subtraction leaves ~1e-14 noise even on a uniform sequence.
    # Preserve the current origin when its score is numerically tied for best.
    if float(scores[order[0]]) - baseline <= 1e-12:
        zero = cuts.index(0)
        order = np.concatenate(([zero], order[order != zero]))
    def candidate(j):
        cut = cuts[int(j)]
        h, bp, direction, _ = sites[cut]
        return {'cut_index': cut, 'register_offset': (-cut) % len(sequence),
                'helix_id': h, 'bp': bp, 'direction': direction.value,
                'q': float(scores[j]), 'delta_q': float(scores[j] - baseline)}
    return {'model': 'Aksel 2024; circular fixed-route register sweep',
            'scaffold_id': scaffold.id, 'scaffold_nt': len(sequence),
            'staple_count': len(staples), 'paired_nt': sum(len(d) for s in staples for d in s),
            'ignored_terminal_staple_nt': ignored, 'conditions': vars(conditions),
            'candidate_count': len(cuts), 'current': candidate(cuts.index(0)),
            'best': candidate(order[0]), 'top': [candidate(j) for j in order[:20]],
            'scores': [{'cut_index': c, 'q': float(q)} for c, q in zip(cuts, scores)],
            'elapsed_seconds': perf_counter() - started}


def apply_nick(design, cut_index):
    scaffold, _, _, cuts, _, locations, _ = prepare_design(design)
    if cut_index not in cuts:
        raise ValueError('The selected nick is not on an eligible ordinary scaffold backbone bond.')
    if cut_index == 0:
        return design
    di, bp = locations[cut_index]
    domains = list(scaffold.domains)
    current = domains[di]
    head = current.model_copy(update={'start_bp': bp})
    tail = [] if bp == current.start_bp else [current.model_copy(update={
        'end_bp': bp - (1 if current.direction == Direction.FORWARD else -1)})]
    rotated = [head] + domains[di+1:] + domains[:di] + tail
    # Remove the old nick's artificial domain boundary without changing bases.
    merged = []
    for domain in rotated:
        prev = merged[-1] if merged else None
        if (prev and prev.helix_id == domain.helix_id and prev.direction == domain.direction
                and domain.start_bp - prev.end_bp == (1 if domain.direction == Direction.FORWARD else -1)):
            merged[-1] = prev.model_copy(update={'end_bp': domain.end_bp})
        else:
            merged.append(domain)
    updated = scaffold.model_copy(update={'domains': merged, 'routing_seed': None})
    result = design.model_copy(update={'strands': [updated if s.id == scaffold.id else s for s in design.strands]})
    # Circular scaffold sequence is unchanged; base 0 now starts at the new nick.
    sequenced = assign_staple_sequences(result)
    # Only the selected scaffold and its active staples belong to this action.
    originals = {s.id: s for s in design.strands}
    scaf_map = build_scaffold_base_map(result)
    ls = _build_loop_skip_map(result)
    overhangs = build_overhang_bp_bases(result)
    strands = []
    for strand in sequenced.strands:
        original = originals[strand.id]
        if strand.is_reference or strand.strand_type not in (StrandType.SCAFFOLD, StrandType.STAPLE):
            strands.append(original)
            continue
        if strand.strand_type == StrandType.STAPLE and original.sequence:
            partners = strand_partner_bases(result, strand, scaf_map=scaf_map, ls_map=ls, overhang_bp_bases=overhangs)
            bases = list(strand.sequence)
            for i, partner in enumerate(partners):
                if partner is None and i < len(original.sequence):
                    bases[i] = original.sequence[i]
            strand = strand.model_copy(update={'sequence': ''.join(bases)})
        strands.append(strand)
    return sequenced.model_copy(update={'strands': strands})
