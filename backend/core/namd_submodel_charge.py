"""Charge accounting for unchanged, whole-residue simulation crops.

CHARMM's natural 5TER/3TER residues have -0.47/-0.53 e. A crop need
not retain them in pairs. Preserve charges, neutralize to the nearest integer,
and explicitly audit the residual instead of labelling it neutral.
"""

import hashlib
import math

from backend.core.md_charge import audit_psf, parse_psf_atoms


def record_charge_policy(source_psf, cropped_psf):
    source = audit_psf(source_psf, require_dna_hydrogens=True,
                       require_dna_residue_charge=True)
    if not source.passed:
        raise ValueError("Invalid submodel source topology: " + "; ".join(source.errors))
    charge = math.fsum(a.charge for a in parse_psf_atoms(cropped_psf))
    return {
        "kind": "preserve_source_nearest_integer_counterions",
        "cropped_psf_sha256": hashlib.sha256(cropped_psf.encode()).hexdigest(),
        "dna_charge_e": charge,
        "counterion_charge_e": -round(charge),
        "residual_charge_e": charge - round(charge),
        "approximation": "Unmodified DNA partial charges; integer counterions; fractional residual under periodic PME",
    }


def charge_policy(metadata, psf):
    """Only a freshly recorded, matching crop can use the boundary exception."""
    receipt = metadata.get("submodel")
    if not receipt:
        return None
    policy = receipt.get("charge_policy")
    if not policy or policy.get("kind") != "preserve_source_nearest_integer_counterions":
        raise ValueError("Submodel lacks its recorded charge policy; prepare again")
    if policy["cropped_psf_sha256"] != hashlib.sha256(psf.encode()).hexdigest():
        raise ValueError("Submodel charge policy does not match cropped topology")
    charge = math.fsum(a.charge for a in parse_psf_atoms(psf))
    if not math.isfinite(charge) or charge > 0 or any(
        not math.isclose(policy[key], value, abs_tol=1e-8)
        for key, value in (
            ("dna_charge_e", charge),
            ("counterion_charge_e", -round(charge)),
            ("residual_charge_e", charge - round(charge)),
        )
    ):
        raise ValueError("Invalid submodel charge accounting")
    return policy


def audit_options(policy, *, final=False):
    return {} if policy is None else {
        "expected_total_charge": policy["residual_charge_e" if final else "dna_charge_e"]
    }
