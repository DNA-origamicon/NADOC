"""Regenerate summaries from saved extraction without rereading the trajectory."""
from pathlib import Path
p=Path(__file__).with_name('analyze.py');source=p.read_text();exec(compile(source[:source.index('raw=DCDFile')],str(p),'exec'))
z=np.load(O/'timeseries.npz');time=z['time_ns'];n=len(time);dt=fm['dt_ns'];nearest=z['nearest_ion_DNA_A'];localdist=z['local_Mg_distance_A'];counts=z['counts'];net=z['net_charge_e'];compensation=(net+93)/93;boxvol=z['box_volume_A3'];volumes=z['shell_volume_A3'];hist=z['shell_counts'];frames=z['density_sample_frames'];rescontact=z['residue_Mg_contact_8A'];resocc=rescontact.sum(0);rescounts=rescontact.sum((0,2));resany=rescontact.any(2).sum(0);verify=[]
exec(compile(source[source.index('def stats'):],str(p),'exec'))
