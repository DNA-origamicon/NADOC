"""Planning arithmetic only; these allocations and RTX PRO rates are estimates.
Run with python3 experiments/peg_validation_benchmark/estimate_campaign.py.
"""
from pathlib import Path
import csv
import json

# name, independent conditions/windows, replicas, equil ns, sampling ns,
# atom range, RTX PRO 6000 Blackwell ns/day (slow, central, fast)
ROWS = [
 ('free_chains',4,3,20,100,'25000-60000',200,350,500),
 ('solution_concentrations',3,3,20,100,'30000-100000',150,250,400),
 ('grafted_surfaces',4,3,50,200,'120000-220000',100,160,250),
 ('dna_approach_windows',32,2,5,20,'100000-250000',60,110,180),
 ('finite_size_controls',2,2,50,100,'250000-500000',50,80,125),
]
PILOT = [
 ('pilot_free_chain',1,3,10,50,'25000-60000',200,350,500),
 ('pilot_surface',1,3,20,100,'120000-220000',100,160,250),
 ('pilot_dna_windows',8,2,5,10,'100000-250000',60,110,180),
]
FIELD = [('additional_uniform_field_states',8,3,50,200,'150000-350000',80,130,200)]


def calculate(rows):
    result = []
    for name, conditions, replicas, equil, production, atoms, slow, central, fast in rows:
        ns = conditions * replicas * (equil + production)
        item = dict(name=name,conditions=conditions,replicas=replicas,equil_ns=equil,
            production_ns=production,atoms=atoms,total_ns=ns,
            throughput_ns_day=dict(slow=slow,central=central,fast=fast))
        item['gpu_hours_with_25pct_overhead'] = dict(
            low=1.25*24*ns/fast,central=1.25*24*ns/central,high=1.25*24*ns/slow)
        result.append(item)
    hours={key:sum(row['gpu_hours_with_25pct_overhead'][key] for row in result)
           for key in ['low','central','high']}
    return dict(rows=result,total_ns=sum(row['total_ns'] for row in result),gpu_hours=hours,
        single_gpu_days={key:value/24 for key,value in hours.items()},
        indicative_gpu_rental_usd={
            'low_at_1_69_per_hour':hours['low']*1.69,
            'central_at_1_69_per_hour':hours['central']*1.69,
            'high_at_2_09_per_hour':hours['high']*2.09})


if __name__ == '__main__':
    root=Path(__file__).resolve().parent
    report=dict(schema='nadoc.peg-calibration-estimate.v1',date='2026-09-09',
        target_gpu='One full NVIDIA RTX PRO 6000 Blackwell 96 GB; not Ada or MIG',
        rate_evidence='Forecast ranges, not measured PEG or RTX PRO throughput',
        overhead_fraction=.25,cloud_spend_this_task_usd=0,
        neutral=calculate(ROWS),pilot=calculate(PILOT),field_addition=calculate(FIELD),
        exclusions=['adaptive convergence extensions','new surface/solvent/chemistry',
            'constant-potential electrode calibration','kinetic validation',
            'storage charges','analyst time','large parameterization iterations beyond routine overhead'])
    (root/'campaign_estimate.json').write_text(json.dumps(report,indent=2)+'\n')
    with (root/'campaign_estimate.csv').open('w',newline='') as handle:
        writer=csv.writer(handle)
        writer.writerow(['campaign','stage','conditions','replicas','equil_ns','production_ns',
            'atoms','total_ns','low_gpu_hours','central_gpu_hours','high_gpu_hours'])
        for label in ['pilot','neutral','field_addition']:
            for row in report[label]['rows']:
                writer.writerow([label,*[row[k] for k in ['name','conditions','replicas','equil_ns',
                    'production_ns','atoms','total_ns']],
                    *[round(row['gpu_hours_with_25pct_overhead'][k],2) for k in ['low','central','high']]])
    print(json.dumps({key:{k:v for k,v in report[key].items() if k!='rows'}
                      for key in ['pilot','neutral','field_addition']},indent=2))
