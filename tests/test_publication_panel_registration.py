import numpy as np
from backend.core.publication_panel_registration import match_panel_strip,panel_grid


def test_normalized_correlation_recovers_offset_without_label_or_reference_design():
    rng=np.random.default_rng(15)
    image=rng.integers(0,256,(90,120,3),dtype=np.uint8)
    moving=image[43:70,21:101]
    result=match_panel_strip(image,moving,scale=1,strip_height=20,crop_left=0)
    assert result['status']=='supported_image_overlap'
    assert result['peaks'][0]['translation_xy']==[21.,43.]
    assert not result['native_routing_resolved']


def test_repeated_pattern_keeps_aliases_and_is_not_accepted():
    rng=np.random.default_rng(31)
    block=rng.integers(0,256,(20,40,3),dtype=np.uint8)
    image=np.tile(block,(4,3,1))
    result=match_panel_strip(image,block,scale=1,strip_height=20,crop_left=0)
    assert result['status']=='ambiguous_or_no_overlap'
    assert result['peak_margin']<.01


def test_non_cadnano_image_does_not_invent_grid():
    assert panel_grid(np.full((100,100,3),255,dtype=np.uint8)) is None


def test_pdf_native_decoder_handles_d014_captioned_raster_pages():
    from pathlib import Path
    import pytest,pymupdf
    from backend.core.publication_panel_registration import register_panels
    source=Path('experiments/origami_publication_catalog/assets/sources/PMC6906287-41467_2019_13284_MOESM2_ESM.pdf')
    if not source.exists():pytest.skip('Optional publication fixture unavailable')
    with pymupdf.open(source) as doc:
        assert isinstance(register_panels(doc[2])['omitted'],list)
        evidence=register_panels(doc[44])
    supported=[p for p in evidence['comparisons'] if p['status']=='supported_image_overlap']
    assert len(supported)==1
    assert supported[0]['peaks'][0]['correlation']>.8
    assert not supported[0]['native_routing_resolved']
