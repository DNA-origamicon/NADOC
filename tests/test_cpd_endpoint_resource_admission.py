import pytest
from experiments.cpd_anti_additive.corrected_core_stage1 import pin, save
from experiments.cpd_anti_additive.endpoint_resource_admission import memory_requirement


def test_default_memory_floor_is_unchanged(tmp_path):
    assert memory_requirement(tmp_path, {}) == (12*1024**3, None)


@pytest.fixture
def reviewed(tmp_path):
    plan = dict(service_memory_gib=8, psi4_memory_gib=4, threads=4, hard_seconds=5400, max_new_gradients=20)
    save(tmp_path/'plan.json', plan)
    evidence = tmp_path/'memory.txt'; evidence.write_text('Measured fixture')
    review = dict(native_plan=pin(tmp_path/'plan.json'), proceed=True, scientific_plan_unchanged=True,
                  minimum_available_memory_gib=11, service_memory_gib=8, reserve_memory_gib=3,
                  native_memory_evidence=[pin(evidence)])
    save(tmp_path/'resource_admission_revision.json', review)
    return tmp_path, plan, review


def test_review_applies_only_to_exact_bounded_plan(reviewed):
    root, plan, review = reviewed
    assert memory_requirement(root, plan)[0] == 11*1024**3
    with pytest.raises(ValueError, match='envelope'):
        memory_requirement(root, {**plan, 'service_memory_gib': 9})


def test_cannot_remove_reserve_or_change_plan(reviewed):
    root, plan, review = reviewed
    review['reserve_memory_gib'] = 0
    save(root/'resource_admission_revision.json', review)
    with pytest.raises(ValueError, match='reserve'):
        memory_requirement(root, plan)
    save(root/'plan.json', {**plan, 'hard_seconds': 9000})
    with pytest.raises(ValueError, match='Changed source'):
        memory_requirement(root, plan)
