"""Bounded additive cis-syn research qualification, separate from full release."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

PACKAGE_NOTICE = """PRELIMINARY CPD RESEARCH PACKAGE

Cis-syn v6, CHARMM36 additive, adjacent internal TT on one strand.
Use ordinary masses and at most 2 fs; Drude and HMR are not qualified.
Inspect native startup and the trajectory for each new design. This is not a
claim of converged lesion-opening populations or quantitative free energies.
Frozen qualification, limitations and evidence hashes are in
forcefield/photoproducts/tt-cpd-cis-syn/preliminary-v6/preliminary_review.json.
The full topology and placement audits are in photoproduct_forcefield_manifest.json.
"""

REQUIRED_ASSETS = frozenset(
    {
        "topology",
        "parameters",
        "coordinate_template",
        "topology_audit_spec",
        "preliminary_review",
        "chemical_definition",
        "patch_charge_scope",
    }
)


def preliminary_qualification(entry: dict, audit: dict, root: Path) -> dict:
    """Require a hash-verified review and every loadable asset; never pass release gates."""
    unavailable = {"available": False, "status": "unqualified"}
    if entry.get("id") != "tt-cpd-cis-syn" or not audit["passed"]:
        return unavailable
    if not REQUIRED_ASSETS.issubset(audit["declared"]):
        return unavailable
    review = json.loads(
        (root / entry["assets"]["preliminary_review"]["path"]).read_text()
    )
    if (
        review.get("schema") != "nadoc.cpd-preliminary-review.v1"
        or review.get("decision") != "accepted"
        or review.get("forcefield") != "CHARMM36-additive"
        or review.get("product_id") != entry["id"]
        or not review.get("limitations")
    ):
        return unavailable
    for kind in (
        "topology",
        "parameters",
        "coordinate_template",
        "topology_audit_spec",
    ):
        if review.get("asset_hashes", {}).get(kind) != entry["assets"][kind]["sha256"]:
            return unavailable
    if not review.get("evidence"):
        return unavailable
    review_root = (
        root / entry["assets"]["preliminary_review"]["path"]
    ).parent.resolve()
    for record in review["evidence"]:
        evidence = (review_root / record["path"]).resolve()
        if (
            not evidence.is_relative_to(review_root)
            or not evidence.is_file()
            or hashlib.sha256(evidence.read_bytes()).hexdigest() != record["sha256"]
        ):
            return unavailable
    return {
        "available": True,
        "status": "preliminary-research",
        "forcefield": review["forcefield"],
        "contexts": ["adjacent-internal-TT"],
        "limitations": review["limitations"],
        "version": review["version"],
    }


def validate_preliminary_endpoints(endpoints: list, model=None) -> None:
    """Restrict this release to native adjacent TT; full topology checks internality."""
    from backend.core.photoproducts import _relationship

    if len(endpoints) != 2 or any(e.base != "T" for e in endpoints):
        raise ValueError("Preliminary cis-syn requires two resolved thymidines.")
    relation = _relationship(*endpoints)
    if not relation["adjacent"] or relation["extra_pairing"] != "native-native":
        raise ValueError("Preliminary cis-syn supports adjacent TT on one strand only.")
    if model is not None:
        from backend.core.base_keys import atom_base_key

        for endpoint in endpoints:
            selected = [a for a in model.atoms if atom_base_key(a) == endpoint.key]
            if not selected:
                raise ValueError("Preliminary CPD endpoint has no atoms.")
            residue = selected[0]
            residues = {
                a.seq_num for a in model.atoms if a.chain_id == residue.chain_id
            }
            if residue.seq_num in (min(residues), max(residues)):
                raise ValueError(
                    "Preliminary cis-syn supports internal TT only; terminal lesions are not qualified."
                )


def validate_preliminary_design(design) -> None:
    from backend.core.base_keys import resolve_base_keys

    for lesion in design.photoproduct_junctions:
        if lesion.product != "TT-CPD" or lesion.stereochemistry != "cis-syn":
            continue
        endpoints, errors = resolve_base_keys(
            design, [lesion.base_key_1, lesion.base_key_2], require_atoms=False
        )
        if errors:
            raise ValueError(
                f"Preliminary cis-syn endpoint resolution failed: {errors}"
            )
        validate_preliminary_endpoints(endpoints)


def validate_internal_patch(entry: dict, derived: list, model) -> None:
    if "preliminary_review" not in entry.get("assets", {}):
        return
    if (
        derived[0]["segid"] != derived[1]["segid"]
        or derived[1]["resid"] != derived[0]["resid"] + 1
    ):
        raise ValueError(
            "Preliminary cis-syn patch endpoints must follow adjacent 5′→3′ residues."
        )
    for endpoint in derived:
        # Stable keys establish identity; chain-local sequence numbers establish termini.
        from backend.core.base_keys import atom_base_key

        selected = [a for a in model.atoms if atom_base_key(a) == endpoint["base_key"]]
        if not selected:
            raise ValueError("Preliminary CPD endpoint has no atoms.")
        chain = selected[0].chain_id
        residues = {a.seq_num for a in model.atoms if a.chain_id == chain}
        if endpoint["resid"] in (min(residues), max(residues)):
            raise ValueError(
                "Preliminary cis-syn supports internal TT only; terminal lesions are not qualified."
            )


def preliminary_order_valid(endpoints, model) -> bool:
    """Atomistic residues are numbered in strand traversal (5′→3′) order."""
    from backend.core.base_keys import atom_base_key

    by_key = {atom_base_key(a): (a.chain_id, a.seq_num) for a in model.atoms}
    first, second = (by_key.get(e.key) for e in endpoints)
    return bool(
        first and second and first[0] == second[0] and second[1] == first[1] + 1
    )
