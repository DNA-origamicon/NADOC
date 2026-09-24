import pytest
from frontend.scrywrite.mcp_bridge import Bridge, tool_result
from tools.scrywrite_inspector.visual_metrics import evaluate


def measurement(pixels=100):
    row = {'class_id': 3, 'pixels': pixels, 'bounds': [10, 20, 10, 10] if pixels else None,
           'centroid': [15, 25] if pixels else None, 'fill_ratio': 1 if pixels else None,
           'moment_axes': [11.5, 11.5] if pixels else None}
    return {'status': 'complete', 'source': 'application_stencil',
            'xr_end_frame_succeeded': True, 'eyes': [{'masks': [row]}, {'masks': [row]}]}


def test_presence_bounds_and_negative_control():
    rules = [{'eye': 0, 'class_id': 3, 'ranges': {'pixels': [90, 110], 'cx': [14, 16], 'width': [9, 11]}}]
    assert evaluate(measurement(), rules)['passed']
    assert not evaluate(measurement(0), rules)['passed']
    assert not evaluate({'status': 'failed'}, rules)['passed']
    assert evaluate(measurement(0), [{'eye': 1, 'class_id': 3, 'ranges': {'pixels': [0, 0]}}])['passed']


@pytest.mark.parametrize('ranges', [{}, {'radius': [1, 2]}, {'width': [None, None]},
                                    {'pixels': [2, 1]}, {'pixels': [0, float('nan')]}])
def test_invalid_expectations(ranges):
    with pytest.raises(ValueError):
        evaluate(measurement(), [{'eye': 0, 'class_id': 3, 'ranges': ranges}])


@pytest.mark.parametrize('roi', [[0, 0, 0, 1], [.9, 0, .2, 1], [0, 0, 1, float('nan')], [0, 0, 1]])
def test_invalid_roi_before_connect(roi):
    with pytest.raises(ValueError):
        Bridge('/absent').call('scrywrite_measure', {'session': '1-2', 'expected_sequence': 0, 'roi': roi})


def test_measure_waits_for_own_sequence_and_reports_failure():
    class Fake(Bridge):
        def request(self, command):
            if command != 'observe':
                assert command == '1-2 5 measure 0 0 1 1'
            return {'session': '1-2', 'measurement': {'status': 'failed', 'command_sequence': 5}}
    result = Fake().call('scrywrite_measure', {'session': '1-2', 'expected_sequence': 4})
    assert tool_result(result, measure=True)['isError']
    with pytest.raises(ValueError):
        evaluate(measurement(), [])


def test_mcp_measure_returns_compact_text_only():
    from frontend.scrywrite.mcp_bridge import dispatch
    class Fake:
        def call(self, name, args):
            return {'session': '1-2', 'command_sequence': 1,
                    'measurement': measurement(), 'controls': ['large semantic state']}
    response = dispatch(Fake(), {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                'params': {'name': 'scrywrite_measure'}})['result']
    assert not response['isError']
    assert set(response['structuredContent']) == {'session', 'command_sequence', 'measurement'}
    assert [item['type'] for item in response['content']] == ['text']
