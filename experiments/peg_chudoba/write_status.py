"""Produce a concise evidence-based snapshot alongside the detailed history."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path


def main():
    root=Path(__file__).parent
    chain=json.loads((root/'campaign_comparison.json').read_text())
    eos=json.loads((root/'eos_comparison.json').read_text())
    rows=[r for r in chain['comparisons'] if r['cutoff']=='zero_tail']
    pressure=[r for r in eos['estimates'] if r['cutoff']=='zero_tail']
    live=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            if (proc/'comm').read_text().strip()!='oxDNA':continue
            directory=(proc/'cwd').resolve();meta=json.loads((directory/'run.json').read_text())
            if (proc/'exe').resolve()!=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA':continue
            process_state=(proc/'stat').read_text().split(') ',1)[1].split()[0]
            if process_state=='Z':continue
            live.append(dict(pid=int(proc.name),directory=str(directory),cutoff=meta.get('cutoff','raw'),sampling=meta['sampling'],
                process_state=process_state,suspended=process_state in ('T','t')))
        except (OSError,ValueError):pass
    verification=json.loads((root/'verification_zero_tail_manifest.json').read_text())
    library=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/src/liboxdna_common.so'
    library_verified=hashlib.sha256(library.read_bytes()).hexdigest()==verification['hashes'].get(str(library))
    timestamp=datetime.now(timezone.utc).isoformat()
    sampled=[r for r in rows if not r['extension_recommended']]
    disagreements=[dict(n=r['n'],temperature_K=r['temperature_K']) for r in sampled
        if (r['two_sem_overlaps_published_interval'] is False or
            (r['published_plotted_interval'] is None and not r['within_two_sem_plus_digitization']))]
    status=dict(generated_utc=timestamp,status='Incomplete; not a benchmark reproduction claim',primary_convention='zero_tail',
        chain_states_with_three_replicas=len(rows),published_chain_states=chain['unique_published_states'],
        chain_states_flagged_for_extension=sum(r['extension_recommended'] for r in rows),
        chain_states_passing_sampling_checks=len(sampled),
        sampled_chain_states_outside_comparison_intervals=disagreements,
        eos_states_with_three_replicas=sum(len(r['replica_ids'])>=3 for r in pressure),published_eos_states=eos['published_states'],
        current_library_matches_validation=library_verified,final_journal_main_text_verified=False,live_engines=live,
        unsuspended_engine_count=sum(not r['suspended'] for r in live),suspended_engine_count=sum(r['suspended'] for r in live))
    (root/'status.json').write_text(json.dumps(status,indent=2)+'\n')
    lines=['# PEG port and benchmark status','',f'Generated {timestamp}. **Incomplete; reproduction is not yet established.**','',
        'The CPU/CUDA port uses one chemical EO bead per repeat, the published bonded terms, temperature-dependent Mie-plus-Gaussian pair interactions, direct-neighbor exclusion, and the outer-tail removal reconstructed from Figure 4(b). Earlier raw and globally shifted runs are controls.','',
        f"- Chain coverage: {len(rows)}/{chain['unique_published_states']} states have three completed zero-tail replicas; {status['chain_states_flagged_for_extension']} currently recommend extension.",
        f"- Pressure coverage: {status['eos_states_with_three_replicas']}/{eos['published_states']} states have three completed zero-tail replicas.",
        f"- Chain agreement screening: {len(sampled)} states pass current sampling checks; {len(disagreements)} fall outside the comparison intervals. This comparison includes two simulation SEMs, plotted published intervals where available, and digitization bounds; the published error-bar type is unspecified. It does not establish exact marker agreement.",
        f'- Current engine library matches the recorded 91-check validation build: {library_verified}.',
        '- Final journal main text remains unverified; the preprint and final SI are available. The final PDF was requested from the user.',
        '- Surface, DNA cross-interactions, and electric-field response are not validated by these bulk benchmarks.','',
        '| Temperature (K) | Completed chain states | Flagged for extension |','| --- | ---: | ---: |']
    for t in sorted({r['temperature_K'] for r in rows}):
        cohort=[r for r in rows if r['temperature_K']==t]
        lines.append(f"| {t:g} | {len(cohort)} | {sum(r['extension_recommended'] for r in cohort)} |")
    lines+=['','Evidence: [chain comparisons](campaign_comparison.json), [pressure comparisons](eos_comparison.json), [test provenance](verification_zero_tail_manifest.json), [potential-curve audit](reference/potential_curve_audit.json), [radius-definition audit](reference/rg_definition_audit.json), and [published intervals](reference/published_chain_intervals.json).',
        '',f"{status['unsuspended_engine_count']} benchmark engines were unsuspended and {status['suspended_engine_count']} were suspended when this snapshot was generated. Their PIDs, paths, samplers, conventions and process states are recorded in [status.json](status.json). A snapshot does not establish later liveness. See [serial scheduling](SERIAL_SCHEDULING.md); elapsed run times include pauses and are unsuitable for isolated performance comparisons.",
        '', 'Run `python -m experiments.peg_chudoba.compare_campaigns`, `python -m experiments.peg_chudoba.compare_eos`, then `python -m experiments.peg_chudoba.write_status` to refresh. See [README.md](README.md) for commands, limitations and investigation history.','']
    (root/'STATUS.md').write_text('\n'.join(lines))
    print(json.dumps({k:v for k,v in status.items() if k!='live_engines'}))


if __name__=='__main__':main()
