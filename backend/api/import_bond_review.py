"""Read-only bond-review notices at lattice-import publication boundaries.

The complete report belongs to the import response. The real import feature's
label retains the initial review flag and counts; neither is a scientific
approval or an authoring command, and historical replay is unchanged.
"""


def assess_import_bonds(design):
    from backend.core.design_bond_review import review_design_bonds

    return review_design_bonds(design, include_geometry=False)


def import_review_label(label, review):
    if not review["review_required"]:
        return label
    counts = review["counts"]
    return (f"{label} · REVIEW REQUIRED: forced bonds "
            f"{counts['matched_forced_bonds']}/{counts['backbone_bonds']}; junctions "
            f"{counts['matched_forced_interhelix_bonds']}/{counts['interhelix_bonds']}")


def attach_import_review(response, review):
    response["import_bond_review"] = review
    if not review["review_required"]:
        return
    counts, ratios = review["counts"], review["ratios"]
    response.setdefault("import_warnings", []).append(
        "Bond review required: forced ligations cover "
        f"{counts['matched_forced_bonds']}/{counts['backbone_bonds']} backbone bonds "
        f"({ratios['forced_all']:.1%}) and "
        f"{counts['matched_forced_interhelix_bonds']}/{counts['interhelix_bonds']} "
        f"interhelix junction bonds ({ratios['forced_interhelix']:.1%}). "
        "Either fraction above 20% requires review. Inspect crossover assignment "
        "and bond geometry before use; this flag records no approval.")
