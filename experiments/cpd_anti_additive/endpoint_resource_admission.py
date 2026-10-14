"""Plan-scoped operational memory reserve; native cgroup limits stay unchanged."""
from experiments.cpd_anti_additive.corrected_core_stage1 import read, pin, checked


def memory_requirement(root, plan):
    path = root/'resource_admission_revision.json'
    if not path.exists():
        return 12*1024**3, None
    review = read(path)
    if checked(review['native_plan']) != root/'plan.json':
        raise ValueError('Resource review belongs to a different plan')
    if not review['proceed'] or not review['scientific_plan_unchanged']:
        raise ValueError('Resource review does not admit this unchanged job')
    if (review['minimum_available_memory_gib'], review['service_memory_gib'], review['reserve_memory_gib']) != (11, 8, 3):
        raise ValueError('Unreviewed memory reserve')
    if (plan['service_memory_gib'], plan['psi4_memory_gib'], plan['threads'], plan['hard_seconds'], plan['max_new_gradients']) != (8, 4, 4, 5400, 20):
        raise ValueError('Reviewed resource envelope changed')
    for evidence in review['native_memory_evidence']:
        checked(evidence)
    if not review['native_memory_evidence']:
        raise ValueError('Missing measured memory evidence')
    return 11*1024**3, pin(path)
