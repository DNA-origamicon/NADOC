"""Limited-memory BFGS with Armijo descent and pre-acceptance path guards."""
import numpy as np


def minimize_feasible(evaluate, initial, feasible, accepted=None, *, maxiter=1500,
                      gtol=.001, max_atom_step=.05, max_linesearch=24, memory=10):
    x=np.asarray(initial,dtype=float).copy()
    if not feasible(x):raise ValueError('Initial geometry is infeasible')
    e,g=evaluate(x);history=[];evaluations=1
    def result(success,message,iteration):
        return dict(x=x,energy=float(e),gradient=g,success=success,message=message,
                    iterations=iteration,evaluations=evaluations)
    for iteration in range(maxiter+1):
        if np.max(np.linalg.norm(g.reshape(-1,3),axis=1))<=gtol:
            return result(True,'Independent gradient threshold reached',iteration)
        if iteration==maxiter:return result(False,'Iteration budget reached',iteration)
        q=g.copy();alphas=[]
        for s,y,rho in reversed(history):
            a=rho*np.dot(s,q);alphas.append(a);q-=a*y
        scale=np.dot(history[-1][0],history[-1][1])/np.dot(history[-1][1],history[-1][1]) if history else 1.
        z=max(scale,1e-12)*q
        for (s,y,rho),a in zip(history,reversed(alphas)):
            z+=s*(a-rho*np.dot(y,z))
        direction=-z
        if not np.isfinite(direction).all() or np.dot(direction,g)>=0:
            history=[];direction=-g
        largest=np.max(np.linalg.norm(direction.reshape(-1,3),axis=1))
        direction*=min(1.,max_atom_step/largest)
        slope=float(np.dot(g,direction));alpha=1.;found=False
        for _ in range(max_linesearch):
            trial=x+alpha*direction
            if feasible(trial):
                te,tg=evaluate(trial);evaluations+=1
                if np.isfinite(te) and np.isfinite(tg).all() and te<=e+1e-4*alpha*slope:
                    found=True;break
            alpha*=.5
        if not found:return result(False,'No feasible Armijo step; stop for audit',iteration)
        s=trial-x;y=tg-g;curvature=float(np.dot(s,y))
        if curvature>1e-10*np.linalg.norm(s)*np.linalg.norm(y) and curvature>0:
            history.append((s,y,1/curvature));history=history[-memory:]
        x,e,g=trial,te,tg
        if accepted is not None:accepted(x,e,g,iteration+1,alpha)
