from backend.core.models import Design, PhotoproductJunction


def test_all_registered_tt_cpd_stereoisomers_round_trip_as_design_intent():
    for stereochemistry in (
        "cis-syn",
        "cis-syn-II",
        "trans-syn-I",
        "trans-syn-II",
        "cis-anti-I",
        "cis-anti-II",
        "trans-anti-I",
        "trans-anti-II",
    ):
        lesion = PhotoproductJunction(
            base_key_1="h0:1:FORWARD",
            base_key_2="h0:2:FORWARD",
            stereochemistry=stereochemistry,
        )
        loaded = Design.from_json(Design(photoproduct_junctions=[lesion]).to_json())
        assert loaded.photoproduct_junctions[0].stereochemistry == stereochemistry


def test_legacy_trans_anti_shorthand_migrates_to_ordered_isomer_i():
    lesion = PhotoproductJunction.model_validate(
        {
            "base_key_1": "h0:1:FORWARD",
            "base_key_2": "h0:2:FORWARD",
            "stereochemistry": "trans-anti",
        }
    )
    assert lesion.stereochemistry == "trans-anti-I"


def test_manual_photoproduct_round_trip_preserves_order_and_chemistry_intent():
    lesion = PhotoproductJunction(
        base_key_1="h:alpha:3:FORWARD",
        base_key_2="__xb__:xo:with:colon:1",
        patch_order="base-key-2-first",
        orientation_method="canonical-key-order:parameters-unavailable",
    )
    loaded = Design.from_json(Design(photoproduct_junctions=[lesion]).to_json())
    assert loaded.photoproduct_junctions == [lesion]
    assert loaded.photoproduct_junctions[0].formation == "manual"


def test_legacy_scadnano_photoproduct_migrates_losslessly_but_stays_unresolved():
    raw = {
        "t1_stable_id": "h0_f_5_t",
        "t2_stable_id": "h1_r_5_t",
        "photoproduct_id": "TT-CPD",
    }
    lesion = PhotoproductJunction.model_validate(raw)
    assert lesion.formation == "legacy-scadnano"
    assert lesion.base_key_1 is None
    assert lesion.model_dump()["t1_stable_id"] == raw["t1_stable_id"]
    assert lesion.model_dump()["t2_stable_id"] == raw["t2_stable_id"]


def test_legacy_producer_token_is_preserved_without_widening_supported_chemistry():
    lesion = PhotoproductJunction.model_validate(
        {
            "t1_stable_id": "old-1",
            "t2_stable_id": "old-2",
            "photoproduct_id": "legacy-producer-token",
        }
    )
    assert lesion.product == "TT-CPD"
    assert lesion.photoproduct_id == "legacy-producer-token"
    assert lesion.formation == "legacy-scadnano"
