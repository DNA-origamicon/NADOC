"""Read-only temperature-view model, in Celsius. See docs/staple_temperature.md.

These are independent-staple estimates, not a prediction of cooperative folding
kinetics. Keep numerical parity with frontend/src/scene/staple_temperature.js.
"""
import math

R = 8.31447 / 4.184
MAGNESIUM_M = 0.010
STAPLE_M = 200e-9
NN = {
    'AA': (-7.6, -21.3), 'TT': (-7.6, -21.3), 'AT': (-7.2, -20.4), 'TA': (-7.2, -21.3),
    'CA': (-8.5, -22.7), 'TG': (-8.5, -22.7), 'GT': (-8.4, -22.4), 'AC': (-8.4, -22.4),
    'CT': (-7.8, -21.0), 'AG': (-7.8, -21.0), 'GA': (-8.2, -22.2), 'TC': (-8.2, -22.2),
    'CG': (-10.6, -27.2), 'GC': (-9.8, -24.4), 'GG': (-8.0, -19.9), 'CC': (-8.0, -19.9),
}


def duplex_thermodynamics(sequence):
    sequence = (sequence or '').upper()
    if len(sequence) < 2 or set(sequence) - set('ACGT'):
        return None
    h, s = 0.2, -5.7
    for base in (sequence[0], sequence[-1]):
        if base in 'AT':
            h += 2.2
            s += 6.9
    for i in range(1, len(sequence)):
        dh, ds = NN[sequence[i-1:i+1]]
        h += dh
        s += ds
    return h, s


def domain_melting_temperature(sequence):
    thermo = duplex_thermodynamics(sequence)
    if thermo is None:
        return None
    seq = sequence.upper()
    gc = sum(b in 'GC' for b in seq) / len(seq)
    lmg = math.log(MAGNESIUM_M)
    correction = (3.92e-5 - 9.11e-6*lmg + gc*(6.26e-5 + 1.42e-5*lmg)
                  + (-4.82e-4 + 5.25e-4*lmg + 8.31e-5*lmg*lmg)/(2*(len(seq)-1)))
    h, s = thermo
    kelvin = h*1000 / (s + R*math.log(STAPLE_M))
    return 1/(1/kelvin + correction) - 273.15


def staple_folding_temperature(sequences, distances):
    if not sequences or len(distances) != len(sequences)-1:
        return None
    h, s = 0, R*math.log(STAPLE_M)
    for seq in sequences:
        thermo = duplex_thermodynamics(seq)
        if thermo is None:
            return None
        dh, ds = thermo
        h += dh*1000
        s += ds + 0.368*(len(seq)-1)*math.log(3.3*math.sqrt(MAGNESIUM_M))
    for distance in distances:
        if not math.isfinite(distance) or distance <= 0:
            return None
        contour, persistence = distance*0.6, 0.9
        r2 = 2*persistence*contour*(1-persistence/contour*(1-math.exp(-contour/persistence)))
        effective_m = (3/(2*math.pi*r2*1e-18))**1.5 / 6.02e23 / 1000
        s += R*math.log(effective_m)
    return h/s - 273.15


def estimate_staple_temperatures(design):
    """Project scaffold contours and duplex domains exactly as the view does.

    Each scaffold is independently circular for this thermodynamic model only.
    Unsupported or ambiguous staples return None rather than an invented score.
    """
    from backend.core.models import Direction, StrandType
    from backend.core.sequences import _build_loop_skip_map, domain_bp_range

    ls_map = _build_loop_skip_map(design)
    junctions = {}
    for xo in design.crossovers:
        a, b = xo.half_a, xo.half_b
        ka, kb = (a.helix_id, a.index, a.strand), (b.helix_id, b.index, b.strand)
        junctions[ka, kb] = junctions[kb, ka] = xo
    for fl in design.forced_ligations:
        junctions[(fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction),
                  (fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction)] = fl

    def keys(domain):
        special = domain.overhang_id is not None or domain.binds_overhang_id is not None
        return [(domain.helix_id, bp, domain.direction, copy)
                for bp in domain_bp_range(domain)
                for copy in range(1 + (0 if special else ls_map.get((domain.helix_id, bp), 0)))]

    def after(domains, i):
        d, nxt = domains[i], domains[(i+1) % len(domains)]
        if d.overhang_id is not None or nxt.overhang_id is not None:
            return None
        return junctions.get(((d.helix_id, d.end_bp, d.direction),
                              (nxt.helix_id, nxt.start_bp, nxt.direction)))

    def internal(domain):
        result = {}
        step = 1 if domain.end_bp >= domain.start_bp else -1
        lo, hi = sorted((domain.start_bp, domain.end_bp))
        for (a, b), junction in junctions.items():
            if (a[0] == b[0] == domain.helix_id and a[2] == b[2] == domain.direction
                    and b[1] == a[1]+step and lo <= a[1] <= hi and lo <= b[1] <= hi):
                result[a[1]] = junction
        return result

    pairing, lengths = {}, {}
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD or strand.is_reference:
            continue
        offset, position = 0, 0
        seq = (strand.sequence or '').upper()
        for i, domain in enumerate(strand.domains):
            domain_keys = keys(domain)
            inserts = internal(domain)
            tail = domain.overhang_id is not None and i in (0, len(strand.domains)-1)
            if not tail:
                for k, key in enumerate(domain_keys):
                    base = seq[offset+k:offset+k+1]
                    pairing[key] = None if key in pairing else (strand.id, position, base)
                    position += 1
                    if k+1 == len(domain_keys) or domain_keys[k+1][1] != key[1]:
                        junction = inserts.get(key[1])
                        position += len(junction.extra_bases or '') if junction else 0
            offset += len(domain_keys)
            junction = after(strand.domains, i)
            position += len(junction.extra_bases or '') if junction else 0
        lengths[strand.id] = position

    result = {}
    complement = {'A': 'T', 'T': 'A', 'G': 'C', 'C': 'G'}
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD or strand.is_reference:
            continue
        offset, bound, eligible = 0, [], bool(strand.domains)
        for i, domain in enumerate(strand.domains):
            domain_keys = keys(domain)
            seq = (strand.sequence or '')[offset:offset+len(domain_keys)].upper()
            offset += len(domain_keys)
            junction = after(strand.domains, i)
            if junction and (junction.extra_bases or i == len(strand.domains)-1):
                eligible = False
            tail = domain.overhang_id is not None and domain.binds_overhang_id is None
            if tail and i in (0, len(strand.domains)-1):
                continue
            if (domain.overhang_id is not None or domain.binds_overhang_id is not None
                    or any(j.extra_bases for j in internal(domain).values())):
                eligible = False
            partners = [pairing.get((h, bp, Direction.REVERSE if direction == Direction.FORWARD
                                    else Direction.FORWARD, copy)) for h, bp, direction, copy in domain_keys]
            if (not partners or not all(partners) or len(seq) != len(domain_keys)
                    or domain_melting_temperature(seq) is None):
                eligible = False
                continue
            scaffold_id = partners[0][0]
            length = lengths[scaffold_id]
            if any(p[0] != scaffold_id or (complement.get(p[2]) and complement[p[2]] != seq[k])
                   for k, p in enumerate(partners)):
                eligible = False
                continue
            positions = [partners[0][1]]
            for previous, current in zip(partners, partners[1:]):
                delta = current[1]-previous[1]
                if delta > length/2:
                    delta -= length
                if delta < -length/2:
                    delta += length
                positions.append(positions[-1]+delta)
            if len(set(positions)) != len(positions) or max(positions)-min(positions) != len(positions)-1:
                eligible = False
            bound.append((seq, scaffold_id, sum(positions)/len(positions) % length))
        if not bound or len({b[1] for b in bound}) != 1:
            eligible = False
        distances = []
        if eligible:
            length = lengths[bound[0][1]]
            for previous, current in zip(bound, bound[1:]):
                distance = abs(current[2]-previous[2])
                distances.append(min(distance, length-distance))
        result[strand.id] = staple_folding_temperature([b[0] for b in bound], distances) if eligible else None
    return result
