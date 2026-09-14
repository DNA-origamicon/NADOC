"""Run/watch one managed charged-wall job and persist periodic profile diagnostics.

Invoke through scripts/test_guard.sh with slow=1. This never starts production,
changes run parameters, or treats a good screening fit as equilibrium certification.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from backend.api.routes_md import _workspace, start_md_job
from backend.api.routes_md_surface_profiles import generate, SurfaceProfileRequest
from backend.core.md_job import MdJob


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('job_id')
    parser.add_argument('--start',action='store_true')
    parser.add_argument('--interval',type=float,default=60)
    args=parser.parse_args()
    if args.interval < 10: parser.error('interval must be at least 10 seconds')
    ws=Path(_workspace());job=MdJob.load(args.job_id,ws)
    target=job.job_dir(ws)/'surface_profile_monitor.jsonl'
    if args.start: print(json.dumps(await start_md_job(job.job_id)),flush=True)
    previous=None
    while True:
        job=MdJob.load(args.job_id,ws)
        row=dict(timestamp=time.time(),job_id=job.job_id,status=job.status.value,error=job.error)
        try:
            result=await asyncio.to_thread(generate,job.job_id,SurfaceProfileRequest().model_dump())
            signature=[(s['file'],s['complete_frames']) for s in result['sources']]
            row.update(frames=result['frames'],available_frames=result['available_frames'],
                       net_charge_e=result['net_charge_e'],bulk_Na_mM=result['bulk_Na_mM'],bulk_Cl_mM=result['bulk_Cl_mM'],
                       fit=result['screening_fit'],reference_debye_nm=result['reference_debye_nm'],
                       block_lambda_nm=result['block_lambda_nm'],first_last_concentration_rms_mM=result['first_last_concentration_rms_mM'])
            if signature!=previous:
                from backend.core.namd_surface_profiles import persist_profile
                persist_profile(job.job_dir(ws)/f"surface_profiles_{result['available_frames']:07d}.json",result)
                previous=signature
        except Exception as exc:
            row['analysis_pending']=getattr(exc,'detail',None) or str(exc)
        with target.open('a') as f:f.write(json.dumps(row,allow_nan=False)+'\n')
        print(json.dumps(row,allow_nan=False),flush=True)
        if job.status.value in ('completed','failed','stopped','cancelled'): break
        await asyncio.sleep(args.interval)


if __name__=='__main__': asyncio.run(main())
