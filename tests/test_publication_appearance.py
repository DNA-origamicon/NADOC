from backend.core.publication_appearance import staple_colors, figure_order


def test_observed_stroke_wins_and_unique_palette_maps_table_only_routes():
    paths=[{'color':[1,.5,0],'table_row':{'color':'#f7931e'}}, {'table_row':{'color':'#f7931e'}}]
    result=staple_colors(paths)
    assert [r['color'] for r in result]==['#ff8000','#ff8000']
    assert result[0]['basis']=='source PDF route stroke'
    assert result[1]['basis'].startswith('table color mapped')
    assert 'color' not in paths[1]


def test_conflicting_palette_is_not_guessed():
    result=staple_colors([{'color':[1,0,0],'table_row':{'color':'#ee0000'}},
                          {'color':[.8,0,0],'table_row':{'color':'#ee0000'}},
                          {'table_row':{'color':'#ee0000'}},{'table_row':{}}])
    assert result[2]['color']=='#ee0000'
    assert result[2]['basis']=='table color; no unique observed figure palette mapping'
    assert result[3]['color'] is None


def test_row_order_uses_figure_positions_not_numbers_and_keeps_auxiliary_ties():
    assert figure_order({'8':40,'2':10,'19':30},{8:{'source_helix':8},2:{'source_helix':2},
        20:{'source_helix':19},19:{'source_helix':19}})==[2,19,20,8]
