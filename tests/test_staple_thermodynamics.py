"""Numerical parity with the temperature view; no authored molecular fixtures."""
import json
import subprocess

import pytest

from backend.core.staple_thermodynamics import domain_melting_temperature, staple_folding_temperature


@pytest.mark.parametrize('sequences,distances', [
    (['ATGCGTACGTAGCTAGCTAG'], []),
    (['ATGCGTACGTAGCT', 'GCGATATCGATCGA'], [42]),
    (['AAAAAAATTTTTTT', 'CGCGCGCGCGCGCG', 'ATGCGTAGCTAG'], [1200, 11.5]),
])
def test_temperature_view_parity(sequences, distances):
    script = """
      import {domainMeltingTemperature, stapleFoldingTemperature} from './frontend/src/scene/staple_temperature.js';
      const [seqs, loops] = JSON.parse(process.argv[1]);
      console.log(JSON.stringify([seqs.map(domainMeltingTemperature), stapleFoldingTemperature(seqs, loops)]));
    """
    expected = json.loads(subprocess.check_output(
        ['node', '--input-type=module', '-e', script, json.dumps([sequences, distances])], text=True))
    assert [domain_melting_temperature(s) for s in sequences] == pytest.approx(expected[0], abs=1e-10)
    assert staple_folding_temperature(sequences, distances) == pytest.approx(expected[1], abs=1e-10)


def test_unknown_sequence_and_zero_loop_are_not_scored():
    assert domain_melting_temperature('ANNN') is None
    assert staple_folding_temperature(['ATGC', 'ATGC'], [0]) is None


def test_recorded_bundle_projection_matches_temperature_view():
    from backend.api import headless_build as hb
    from backend.core.models import LatticeType
    from backend.core.staple_thermodynamics import estimate_staple_temperatures
    from scripts.agent_structure_guard import audit

    with hb.scratch_session():
        hb.create_bundle([(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)], 84,
                         lattice=LatticeType.HONEYCOMB, name='Temperature projection parity')
        hb.auto_scaffold()
        design = hb.full_autostaple(experimental={})
        assert audit(design)['status'] == 'verified'
        script = """
          import {estimateStapleTemperatures} from './frontend/src/scene/staple_temperature.js';
          import fs from 'node:fs';
          const result = estimateStapleTemperatures(JSON.parse(fs.readFileSync(0, 'utf8')));
          console.log(JSON.stringify(Object.fromEntries([...result].map(([id, r]) => [id, r.total]))));
        """
        expected = json.loads(subprocess.check_output(
            ['node', '--input-type=module', '-e', script], input=design.model_dump_json(), text=True))
        actual = estimate_staple_temperatures(design)
        assert any(t is not None for t in actual.values())
        assert actual.keys() == expected.keys()
        for sid in actual:
            assert actual[sid] == (pytest.approx(expected[sid], abs=1e-10) if expected[sid] is not None else None)
