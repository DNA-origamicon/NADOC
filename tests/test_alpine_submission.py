import asyncio
from types import SimpleNamespace

from backend.core import alpine_submission as submission
from backend.core.md_job import MdJob, MdStatus, new_job


def test_durable_receipt_prevents_old_poll_from_replacing_resume(tmp_path):
    job = new_job(design_name='test', protocol='equilibrium_aware_namd', name_stem='test', package_subdir='package')
    job.execution_target = 'alpine'
    job.slurm_job_id = 'old'
    job.queued_at = 1
    job.save(tmp_path)
    old = MdJob.load(job.job_id, tmp_path)
    old_text = (job.job_dir(tmp_path) / 'job.json').read_text()
    job.slurm_job_id = 'new'
    job.queued_at = 2
    job.status = MdStatus.running
    job.resubmit_count = 1
    submission.record_submission(job, tmp_path)
    job.save(tmp_path)
    old.save(tmp_path)
    assert MdJob.load(job.job_id, tmp_path).slurm_job_id == 'new'
    # Also tolerate a still-running old-code worker which knows nothing of the guard.
    (job.job_dir(tmp_path) / 'job.json').write_text(old_text)
    recovered = MdJob.load(job.job_id, tmp_path)
    assert recovered.slurm_job_id == 'new'
    assert recovered.status == MdStatus.running
    assert recovered.resubmit_count == 1


def test_resume_recovers_accepted_allocation_without_resubmitting(tmp_path):
    job = new_job(design_name='test', protocol='equilibrium_aware_namd', name_stem='test', package_subdir='package')
    job.execution_target = 'alpine'
    job.slurm_job_id = 'old'
    job.queued_at = 1
    job.remote_scratch_dir = '/scratch/test'
    job.save(tmp_path)
    class Conn:
        async def run(self, command):
            assert 'sbatch' not in command
            if command.startswith('squeue'):
                text = '123|/scratch/test|RUNNING\n456|/scratch/unrelated|RUNNING\n'
            elif command.startswith('scontrol'):
                text = ('JobId=123 WorkDir=/scratch/test SubmitTime=2026-11-22T11:16:50 '
                        'Partition=artxpro6000 QOS=gpu-long NumCPUs=16 TimeLimit=7-00:00:00 '
                        'ReqTRES=cpu=16,mem=48G TresPerNode=gres/gpu:rtx_pro_6000_2g.48gb:1')
            else:
                text = '1795371410\n'
            return SimpleNamespace(rc=0, stdout=text)
    assert asyncio.run(submission.recover_active_submission(job, tmp_path, Conn()))
    restored = MdJob.load(job.job_id, tmp_path)
    assert restored.slurm_job_id == '123'
    assert restored.resources['walltime_h'] == 168
    assert restored.resources['mem_gb'] == 48
    assert restored.resources['gres_type'] == 'rtx_pro_6000_2g.48gb'
    assert restored.status == MdStatus.running
