#pragma once

// A VMMC cluster may reuse internal energies only if its chosen pair images
// undergo the same rigid rotation. The inverse rotation gives the same residual
// norm, so rejecting a violation is a symmetric restriction of the proposals.
// Vec and Matrix are oxDNA's LR_vector / LR_matrix in the native backend.
template<class Vec, class Matrix>
bool nadoc_vmmc_periodic_pair_is_rigid(const Vec &old_r, const Vec &new_r,
                                      const Matrix &rotation, double box_side) {
    const double tolerance = 1.e-8 * (1. + box_side);
    return (new_r - rotation * old_r).norm() <= tolerance * tolerance;
}
