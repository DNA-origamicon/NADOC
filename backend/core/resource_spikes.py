"""Time-weighted peak characterization; no inferred universal failure probability."""
import math


def summarize_series(samples, *, warmup_s=5., absolute_mib=64., relative=.05):
    """Piecewise-constant samples (seconds, MiB); last point closes observation.

    A spike episode crosses median + max(absolute_mib, relative*median).
    Episodes still high at observation end are marked right-censored; they may
    be sustained capacity growth. Sampling cannot bound shorter unseen peaks.
    """
    values=[(float(t),float(v)) for t,v in samples]
    if len(values)<2 or any(not math.isfinite(t) or not math.isfinite(v) or v<0 for t,v in values):
        raise ValueError('At least two finite nonnegative measurements required')
    if any(b[0]<a[0] for a,b in zip(values,values[1:])):raise ValueError('Measurements must be ordered')
    start=values[0][0]+warmup_s;end=values[-1][0]
    intervals=[(max(start,t),u,v) for (t,v),(u,_) in zip(values,values[1:]) if u>max(start,t)]
    if not intervals:raise ValueError('No observation after warmup')
    duration=end-start;ordered=sorted((v,b-a) for a,b,v in intervals)
    def quantile(q):
        total=0
        for v,dt in ordered:
            total+=dt
            if total>=q*duration:return v
        return ordered[-1][0]
    median=quantile(.5);threshold=median+max(absolute_mib,relative*median)
    episodes=[];active=None
    for a,b,v in intervals:
        if v>threshold:
            if active is None:active=dict(start_s=a,end_s=b,peak_mib=v)
            else:active.update(end_s=b,peak_mib=max(v,active['peak_mib']))
        elif active is not None:
            episodes.append(active);active=None
    if active is not None:episodes.append(active)
    for e in episodes:e.update(duration_s=e['end_s']-e['start_s'],right_censored=e['end_s']==end)
    return dict(observed_s=duration,mean_mib=sum((b-a)*v for a,b,v in intervals)/duration,
        median_mib=median,p95_mib=quantile(.95),p99_mib=quantile(.99),
        peak_mib=max(v for _,_,v in intervals),startup_peak_mib=max(v for t,v in values if t<=start),
        threshold_mib=threshold,episodes=episodes,episode_count=len(episodes),
        episodes_per_observed_hour=len(episodes)*3600/duration,
        fraction_above_threshold=sum(e['duration_s'] for e in episodes)/duration,
        maximum_sampling_gap_s=max(u-t for (t,_),(u,_) in zip(values,values[1:])),
        limitation='Observed episodes at this resolution; not a bound on unsampled peaks or future runs.')


def summarize_startup(samples, *, startup_end_s, running_start_s, running_end_s,
                      absolute_mib=64., relative=.05):
    """Compare startup with a measured running window, excluding shutdown.

    Boundaries use the same clock as samples. Callers supply engine markers;
    a fixed warmup or an arbitrary fraction of a short run is not a substitute.
    This distinguishes an initial rise to retained capacity from an overshoot.
    It does not establish whether any particular allocation is reclaimable.
    """
    values=[(float(t),float(v)) for t,v in samples]
    boundaries=(startup_end_s,running_start_s,running_end_s,absolute_mib,relative)
    if (len(values)<2 or not all(math.isfinite(x) for x in boundaries)
            or absolute_mib<0 or relative<0
            or any(not math.isfinite(t) or not math.isfinite(v) or v<0 for t,v in values)
            or any(b[0]<a[0] for a,b in zip(values,values[1:]))):
        raise ValueError('Ordered finite samples and nonnegative thresholds required')
    if not (values[0][0] <= startup_end_s <= running_start_s < running_end_s <= values[-1][0]):
        raise ValueError('Startup and running windows must be observed and ordered')

    def window(start,end):
        # Piecewise-constant carry into the explicitly observed window.
        prior=next(v for t,v in reversed(values) if t<=start)
        points=[(start,prior)]+[(t,v) for t,v in values if start<t<end]
        at_end=next(v for t,v in reversed(values) if t<=end)
        return points+[(end,at_end)]

    startup_peak=max(v for t,v in values if t<=startup_end_s)
    running=summarize_series(window(running_start_s,running_end_s),warmup_s=0,
                             absolute_mib=absolute_mib,relative=relative)
    tolerance=max(absolute_mib,relative*running['median_mib'])
    extra=max(0.,startup_peak-running['peak_mib'])
    if extra>tolerance:
        classification='startup_overshoot'
    elif running['median_mib']-startup_peak>tolerance:
        classification='continued_growth'
    else:
        classification='no_distinct_startup_overshoot'
    return dict(startup_peak_mib=startup_peak,
        running_median_mib=running['median_mib'],running_peak_mib=running['peak_mib'],
        startup_extra_above_running_peak_mib=extra,
        startup_end_s=startup_end_s,running_start_s=running_start_s,
        running_end_s=running_end_s,classification=classification,
        classification_tolerance_mib=tolerance,
        maximum_sampling_gap_s=max(u-t for (t,_),(u,_) in zip(values,values[1:])),
        limitation='Observed window comparison; no bound on unsampled peaks or proof that live buffers can be released.')
