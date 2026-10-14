import json

import numpy as np
import pytest

from experiments.cpd_isomer_formation.geometry import (
    KEYS, INDEX, catalog, eligible, features, local_image, planar_reactant_audit,
)


def coordinates(product):
    d = json.loads(open(product["definition"]["path"]).read())
    return np.array([d["source_ring_coordinates_angstrom"][k] for k in KEYS])


@pytest.mark.parametrize("index", range(8))
def test_all_reviewed_product_stereochemistries_and_proper_rotation(index):
    products = catalog()
    xyz = coordinates(products[index])
    # Product geometry checks identity/parity only, never reactant occupancy.
    result = features(xyz, products)
    assert result["signs_match"][index]
    same_family = [i for i,p in enumerate(products) if p["family"] == products[index]["family"]]
    assert result["signs_match"][same_family].sum() == 1
    q, _ = np.linalg.qr(np.array([[1.,2.,3.],[-2.,4.,1.],[3.,-2.,5.]]))
    if np.linalg.det(q) < 0:
        q[:,0] *= -1
    moved = features(xyz @ q + [300.,-80.,7.], products)
    for name in result:
        np.testing.assert_allclose(result[name], moved[name], atol=1e-9)
    assert not eligible(result).any(), "Covalent product distances cannot count as reactant occupancy"


def test_endpoint_exchange_changes_ordered_cis_syn_assignment():
    products = catalog()
    xyz = coordinates(products[0])
    swapped = np.concatenate([xyz[6:], xyz[:6]])
    assert features(swapped, products)["signs_match"][1]
    assert not features(swapped, products)["signs_match"][0]


def test_local_periodic_images_recover_geometry():
    xyz = coordinates(catalog()[0]) + 30
    wrapped = xyz.copy()
    wrapped[6:] += [40.,0.,0.]
    wrapped[0] -= [0.,40.,0.]
    fixed = local_image(wrapped[None], np.array([40,40,40,90,90,90],dtype=np.float32))[0]
    np.testing.assert_allclose(fixed, xyz, atol=1e-5)


def test_coplanar_and_degenerate_approaches_are_not_assigned():
    xyz = coordinates(catalog()[0])
    xyz[:,2] = 0
    assert not eligible(features(xyz)).any()
    assert not eligible(features(np.zeros((12,3)))).any()


def test_independent_planar_precursors_cover_all_eight_with_correct_cis_trans():
    audit = planar_reactant_audit()
    assert audit["passed"]
    assert audit["family_pass"] == {"syn": True, "anti": True}
    assert all(c["relationship_passed"] for c in audit["cases"])


def test_old_anti_definitions_and_c6_only_workaround_are_rejected():
    products = catalog()
    for product in products:
        if product["family"] == "anti":
            for center in product["centers"]:
                if center["center"] == INDEX["1:C5"]:
                    center["expected_sign"] *= -1
    # Reproduce the historical sentinel: no planar anti approach can match.
    audit = planar_reactant_audit(products)
    assert not audit["passed"]
    assert all(not c["matched_products"] for c in audit["cases"] if c["family"] == "anti")
    # A C6-only workaround restores coverage but gets cis/trans wrong.
    for product in products:
        if product["family"] == "anti":
            for center in product["centers"]:
                if center["center"] == INDEX["1:C6"]:
                    center["expected_sign"] *= -1
    audit = planar_reactant_audit(products)
    assert not audit["passed"]
    anti = [c for c in audit["cases"] if c["family"] == "anti"]
    assert all(c["unique"] and not c["relationship_passed"] for c in anti)


@pytest.mark.parametrize("first,second", [(4,4), (5,5), (6,7), (7,6)])
def test_anti_endpoint_exchange_matches_ordered_partner(first, second):
    products = catalog()
    xyz = coordinates(products[first])
    swapped = np.concatenate([xyz[6:], xyz[:6]])
    assert features(swapped, products)["signs_match"][second]
    assert features(swapped, products)["signs_match"][4:].sum() == 1
