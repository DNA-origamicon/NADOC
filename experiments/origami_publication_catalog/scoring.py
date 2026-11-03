"""Image-only reconstruction score v2: coverage and missing topology gate detail."""
WEIGHTS = {'scaffold_routing': 25, 'staple_routes_and_ends': 30,
           'base_register_and_indels': 20, 'helix_layout': 15, 'legibility': 10}
CAPS = {'complete_design_map': 100, 'partial_design': 35,
        'component_only': 35, 'conceptual_illustration': 15}

def reconstruction_score(components, image_kind):
    assert set(components) == {'whole_design_coverage', *WEIGHTS}
    assert all(isinstance(v, int) and 0 <= v <= 4 for v in components.values())
    detail = sum(components[k] * w / 4 for k, w in WEIGHTS.items())
    score = detail * components['whole_design_coverage'] / 4
    cap = CAPS[image_kind]
    # Even a complete silhouette cannot compensate for missing route/register information.
    essential = min(components[k] for k in ('scaffold_routing', 'staple_routes_and_ends', 'base_register_and_indels', 'helix_layout'))
    cap = min(cap, {0: 15, 1: 35, 2: 60, 3: 85, 4: 100}[essential])
    return min(round(score), cap)
