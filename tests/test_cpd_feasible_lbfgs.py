import numpy as np
from experiments.cpd_anti_additive.feasible_lbfgs import minimize_feasible


def test_anisotropic_quadratic_descent_and_step_cap():
    weights=np.array([1.,10.,100.,2.,20.,200.]);target=np.array([.2,-.1,.3,-.2,.15,.1])
    states=[np.zeros(6)];energies=[]
    def evaluate(x):
        delta=x-target;return .5*np.dot(weights*delta,delta),weights*delta
    def accepted(x,e,g,i,a):states.append(x.copy());energies.append(e)
    result=minimize_feasible(evaluate,states[0],lambda x:True,accepted,gtol=1e-7,maxiter=1000)
    assert result['success']
    assert np.max(abs(result['x']-target))<1e-7
    assert all(b<=a for a,b in zip(energies,energies[1:]))
    assert all(np.max(np.linalg.norm((b-a).reshape(-1,3),axis=1))<=.050000000001 for a,b in zip(states,states[1:]))


def test_no_infeasible_energy_call_or_checkpoint():
    seen=[]
    def feasible(x):return x[0]>=.2
    def evaluate(x):
        assert feasible(x);seen.append(x.copy());return .5*float(x@x),x.copy()
    result=minimize_feasible(evaluate,np.array([.25,0.,0.]),feasible,maxiter=100)
    assert not result['success']  # Constrained boundary is not a stationary point.
    assert all(x[0]>=.2 for x in seen)
    assert result['x'][0]>=.2
