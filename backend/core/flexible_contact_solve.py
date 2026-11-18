"""Repair initial contacts, then close tethers subject to rigid-body clearance."""
import numpy as np
from scipy.optimize import least_squares, minimize


def solve_contact_constrained(lengths, contacts, contour, x, max_nfev):
    evaluations = 0
    repair_limit = min(max_nfev, 150)
    iteration_limit = min(max_nfev, 500)
    if np.any(contacts.gaps(x) < -.001):
        # Numerical initialization only. No intermediate pose is authored.
        repaired = least_squares(
            lambda v: np.r_[np.minimum(contacts.gaps(v), 0), 1e-5*v], x,
            max_nfev=repair_limit, ftol=1e-9, xtol=1e-9, gtol=1e-9)
        x = repaired.x
        evaluations += repaired.nfev

    def objective(v):
        excess = np.maximum(lengths(v)-contour, 0)
        return float(excess @ excess + 1e-10*(v @ v))

    constraints = [{'type': 'ineq', 'fun': contacts.gaps}] if len(contacts.ia) else []
    fitted = minimize(objective, x, method='SLSQP', constraints=constraints,
                      options={'maxiter': iteration_limit, 'ftol': 1e-12})
    # The caller independently checks every tether and contact; an optimizer
    # success flag is neither necessary nor sufficient for accepting a pose.
    return fitted.x, evaluations + fitted.nfev, dict(
        method='SLSQP', maxiter=iteration_limit, ftol=1e-12, motion_penalty=1e-10,
        contact_constraint='gap >= 0', repair_max_nfev=repair_limit,
        repair_motion_penalty=1e-5, repair_tolerance=1e-9,
        iterations=fitted.nit, optimizer_success=bool(fitted.success),
        optimizer_message=str(fitted.message))
