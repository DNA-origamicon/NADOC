from backend.parameterization.photoproduct_terms import (
    build_term_inventory,
    enumerate_graph_terms,
)


def test_graph_term_enumerator_canonicalizes_paths():
    terms = enumerate_graph_terms([("B", "A"), ("B", "C"), ("C", "D")])
    assert terms["bonds"] == [["A", "B"], ["B", "C"], ["C", "D"]]
    assert ["A", "B", "C"] in terms["angles"]
    assert terms["dihedrals"] == [["A", "B", "C", "D"]]


def test_cis_syn_inventory_includes_order_changes_and_every_generated_term():
    inventory = build_term_inventory("TT-CPD", "cis-syn")
    assert len(inventory["changed_bond_orders"]) == 2
    assert {
        (item["precursor_order"], item["product_order"])
        for item in inventory["changed_bond_orders"]
    } == {("double", "single")}
    generated = inventory["newly_generated_terms"]
    assert len(generated["bonds"]) == 2
    assert len(generated["angles"]) == 12
    # Adding both crosslinks changes paths around each new edge and around the
    # neighboring intrabase edges; psfgen must regenerate and parameterize all.
    assert len(generated["dihedrals"]) == 42
    assert inventory["stereochemical_impropers"]["status"] == "review-required"
    assert inventory["parameter_status"] == "unassigned"
