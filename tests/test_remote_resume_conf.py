"""The cell-shrink resume — without it, "bounded retry" means "fails four times".

An NPT box relaxes ~3% to equilibrium density and crosses NAMD's fixed patch grid:
"Periodic cell has become too small for original patch grid!". That is self-healing —
but ONLY if the restart rebuilds the grid at the SMALLER box.

The chain script used to just re-run the original conf, whose extendedSystem points at
the PREVIOUS segment's .xsc — i.e. the ORIGINAL cell. So NAMD rebuilt the same grid, the
box shrank into the same wall, and all four retries failed identically. Measured on the
live 3x6x400 pod before the fix:

    conf (original) : 156.636 x  89.136 x 1436.190
    restart @ 4000  : 151.972 x  86.482 x 1393.426    (-3.0% on every axis)
"""

from __future__ import annotations

import subprocess

import pytest

from backend.core.md_protocols import _RESUME_DROP as PROTOCOL_DROP
from backend.core.remote_resume_conf import (
    _RESUME_DROP,
    build_resume_conf,
    restart_step_of,
)

# The real .xsc NAMD wrote on the pod, verbatim.
LIVE_XSC = """\
#$LABELS step a_x a_y a_z b_x b_y b_z c_x c_y c_z o_x o_y o_z
4000 151.97204282 0 0 0 86.4819071529 0 0 0 1393.42633991 78.318 44.568 718.095
"""

CONF = """\
structure          s.psf
coordinates        s.pdb
cellBasisVector1   156.636  0.000    0.000
cellBasisVector2   0.000    89.136   0.000
cellBasisVector3   0.000    0.000    1436.190
timestep           1
binCoordinates     output/s_00_min.coor
binVelocities      output/s_00_min.vel
extendedSystem     output/s_00_min.xsc
outputName         output/s_01_p10
dcdFile            output/s_01_p10.dcd
xstFile            output/s_01_p10.xst
run                120000
"""


class TestResumeConf:
    def test_reads_the_checkpoint_step_from_the_xsc(self):
        assert restart_step_of(LIVE_XSC) == 4000

    def test_takes_the_LAST_data_line_not_the_first(self):
        """An .xsc accretes one line per restart write; the newest is the last."""
        assert restart_step_of(LIVE_XSC + "8000 1 0 0 0 1 0 0 0 1 0 0 0\n") == 8000

    def test_resume_points_at_the_segments_OWN_restart_files(self):
        """THE fix. The original conf's extendedSystem is the MINIMISATION's box; the
        segment's own restart.xsc is the SHRUNKEN one. Reading the wrong one is what made
        every retry die at the identical step."""
        out = build_resume_conf(CONF, "s_01_p10", 4000, 120_000)
        assert "extendedSystem     output/s_01_p10.restart.xsc" in out
        assert "binCoordinates     output/s_01_p10.restart.coor" in out
        assert "binVelocities      output/s_01_p10.restart.vel" in out
        # ...and NOT the original box any more.
        assert "output/s_00_min.xsc" not in out
        assert "output/s_00_min.coor" not in out

    def test_runs_only_the_remaining_steps(self):
        out = build_resume_conf(CONF, "s_01_p10", 4000, 120_000)
        assert "firsttimestep      4000" in out
        assert "run                116000" in out
        assert "run                120000" not in out

    def test_keeps_writing_the_SAME_dcd_so_tier_a_can_still_judge(self):
        """Deliberately unlike md_protocols.build_remote_resume_conf, which writes a
        .cont<k>.dcd to preserve the partial.

        Tier-A early-stop reads its WC base-pairing series off output/<seg>.dcd. If the
        continuation went elsewhere, that series would hold only the few PRE-shrink
        frames, fall under the evaluator's window, and report HOLD forever — the segment
        would silently lose its ability to bridge. The discarded frames are the box
        equilibrating at a cell NAMD has just declared invalid; nobody wants them.
        """
        out = build_resume_conf(CONF, "s_01_p10", 4000, 120_000)
        assert "dcdFile            output/s_01_p10.dcd" in out
        assert ".cont" not in out

    def test_refuses_a_checkpoint_at_or_past_the_end(self):
        with pytest.raises(ValueError, match="at/past"):
            build_resume_conf(CONF, "s_01_p10", 120_000, 120_000)

    def test_drop_list_stays_in_lockstep_with_md_protocols(self):
        """This file is VENDORED to the pod with no NADOC on sys.path. If the protocol's
        drop-list gains a directive and this copy doesn't, the resume conf silently keeps
        a stale directive that pins it back to the original start."""
        assert _RESUME_DROP == PROTOCOL_DROP


class TestChainScriptActuallyResumes:
    """Execute the generated bash against a fake namd that shrinks once — the live
    failure — and prove the retry uses the resume conf."""

    def _fake_namd_that_shrinks_once(self, tmp_path):
        p = tmp_path / "fake_namd"
        p.write_text(
            "#!/bin/bash\n"
            'conf="${!#}"\n'
            'name=$(basename "$conf" .conf)\n'
            'name=${name%.resume}\n'
            'echo "$conf" >> confs_used.txt\n'
            "mkdir -p output\n"
            # First invocation: write a restart checkpoint, then die exactly as NAMD does.
            'if [ ! -f "output/${name}.restart.xsc" ]; then\n'
            '  printf "#$LABELS step a_x\\n4000 151.97 0 0 0 86.48 0 0 0 1393.4 0 0 0\\n"'
            ' > "output/${name}.restart.xsc"\n'
            '  echo restart > "output/${name}.restart.coor"\n'
            '  echo restart > "output/${name}.restart.vel"\n'
            "  echo 'FATAL ERROR: Periodic cell has become too small for original"
            " patch grid!'\n"
            "  exit 1\n"
            "fi\n"
            # Second invocation (the resume): succeed.
            'echo coords > "output/${name}.coor"\n'
            "exit 0\n"
        )
        p.chmod(0o755)
        return p

    def test_the_retry_uses_the_resume_conf_and_the_segment_completes(self, tmp_path):
        import shutil

        from backend.core import remote_resume_conf
        from backend.core.runpod_script import (
            RESUME_CONF_NAME,
            ChainStep,
            render_chain_script,
        )

        # Stage the pod-side writer exactly as the executor does.
        shutil.copy(remote_resume_conf.__file__, tmp_path / RESUME_CONF_NAME)
        (tmp_path / "s_01_p10.conf").write_text(CONF)

        script = tmp_path / "chain.sh"
        script.write_text(render_chain_script(
            steps=[ChainStep("s_01_p10", steps=120_000)],
            remote_dir=str(tmp_path),
            namd_bin=str(self._fake_namd_that_shrinks_once(tmp_path)),
            threads=2,
        ))
        script.chmod(0o755)
        proc = subprocess.run(["bash", str(script)], cwd=tmp_path,
                              capture_output=True, text=True, timeout=120)

        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert (tmp_path / "nadoc_status").read_text().strip() == "completed"

        used = (tmp_path / "confs_used.txt").read_text().split()
        assert used == ["s_01_p10.conf", "s_01_p10.resume.conf"], (
            f"the retry must use the RESUME conf, not re-run the original: {used}"
        )
        # And the resume conf really points at the shrunken cell.
        resumed = (tmp_path / "s_01_p10.resume.conf").read_text()
        assert "extendedSystem     output/s_01_p10.restart.xsc" in resumed
        assert "run                116000" in resumed
