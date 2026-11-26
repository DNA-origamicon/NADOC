"""Resolve base-source disagreements without erasing their original evidence."""
import math

BASE_PREFERENCE = ('T', 'A', 'C', 'G')


def resolve_base_evidence(evidence):
    """Highest evidence support wins; only ties use the user's base preference.

    Each source contributes at most its maximum supplied weight per candidate,
    so repeated PDF labels cannot outvote a table by duplication. OCR confidence
    admits a readable letter; it is not itself biological evidence strength.
    """
    support = {}
    for item in evidence:
        base, source = item['base'], item['source']
        weight = item.get('weight', 1.0)
        if base not in BASE_PREFERENCE or not isinstance(source, str) or not source:
            raise ValueError('Base evidence requires A/C/G/T and a named source')
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0:
            raise ValueError('Evidence weight must be finite and positive')
        support[(source, base)] = max(weight, support.get((source, base), 0))
    scores = {base: sum(w for (source, b), w in support.items() if b == base)
              for base in BASE_PREFERENCE if any(b == base for _, b in support)}
    maximum = max(scores.values(), default=0)
    winners = [base for base in BASE_PREFERENCE if base in scores
               and math.isclose(scores[base], maximum, rel_tol=1e-12, abs_tol=1e-12)]
    conflict = len(scores) > 1
    return {'selected_base': winners[0] if winners else None,
            'conflict': conflict, 'severity': 'notice' if conflict else None,
            'selection_reason': ('preference_tie_break' if len(winners) > 1 else
                                 'stronger_evidence' if conflict else 'source_agreement' if len(support) > 1 else 'single_source'),
            'preference_order': list(BASE_PREFERENCE), 'support': scores,
            'evidence': [{'source': source, 'base': base, 'weight': weight}
                         for (source, base), weight in sorted(support.items())]}
