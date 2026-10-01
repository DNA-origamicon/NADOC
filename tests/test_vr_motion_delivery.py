import numpy as np
import pytest
from tools.vr_workflows.motion_delivery import speed_trace
from tools.vr_motion.model import summary, validate_trace


@pytest.mark.parametrize('speed',[30,60,120])
def test_speed_sweep_reaches_requested_speed_and_returns_home_before_release(speed):
    trace=speed_trace([.3,1.2,-.35],speed)
    validate_trace(trace,playable=True)
    assert summary(trace)['hands']['right']['angular_deg_s_p95'] == pytest.approx(speed,rel=.05)
    samples=trace['samples']
    assert samples[-1]['hands']['right']['orientation']==[0,0,0,1]
    assert samples[-5]['hands']['right']['orientation']==[0,0,0,1]
    assert trace['events'][-1]['pressed'] is False
    assert np.max(np.diff([s['t'] for s in samples]))<.051
    assert all(s['hands']['right']['position']==[.3,1.2,-.35] for s in samples)
