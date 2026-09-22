"""Exploratory recording/hand clusters, not participant diagnoses or skill labels.

Usage: uv run --with h5py --with scikit-learn python -m tools.vr_motion.cluster ROOT OUTPUT
ROOT is the extracted BEHAVIOR raw directory. Originals are read-only.
"""
import argparse
import io
import tarfile
import json
from pathlib import Path
import numpy as np

FEATURES = ['speed_median_m_s', 'speed_p90_m_s', 'pause_fraction',
            'acceleration_median_m_s2', 'turning_median_deg']


def features(frames, hand, head):
    """Head-relative translation removes shared locomotion; not intended-path error.

    Derivatives only join consecutive, valid, <=100ms, <=25cm intervals.
    Acceleration and turning use consecutive accepted intervals, never gap bridges.
    """
    n = len(frames)
    if n < 4:
        raise ValueError('too few frames')
    dt = frames[1:, 3]
    positions = hand[:, 1:4]-head[:, 1:4]
    tracked = (hand[:, 0] > 0) & (head[:, 0] > 0) & np.isfinite(positions).all(axis=1)
    delta = np.diff(positions, axis=0)
    steps = np.linalg.norm(delta, axis=1)
    timing = np.isfinite(dt) & (dt > 0) & (dt <= .1) & (np.diff(frames[:, 0]) == 1)
    jumps = steps > .25
    good = tracked[1:] & tracked[:-1] & timing & ~jumps
    velocity = np.zeros_like(delta)
    velocity[good] = delta[good]/dt[good, None]
    speed = np.linalg.norm(velocity, axis=1)
    pairs = good[1:] & good[:-1]
    mid_dt = (dt[1:]+dt[:-1])/2
    acc = np.linalg.norm(np.diff(velocity, axis=0)[pairs], axis=1)/mid_dt[pairs]
    moving = pairs & (speed[1:] > .05) & (speed[:-1] > .05)
    cosine = np.sum(velocity[1:][moving]*velocity[:-1][moving], axis=1)/(speed[1:][moving]*speed[:-1][moving])
    angles = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    quality = {'frames': n, 'tracked_fraction': float(tracked.mean()),
               'valid_interval_fraction': float(good.mean()),
               'bad_timing_fraction': float((~timing).mean()),
               'jump_fraction': float(jumps.mean()), 'valid_intervals': int(good.sum())}
    values = None
    if good.sum() >= 100 and len(acc) >= 50 and len(angles) >= 20:
        values = dict(zip(FEATURES, map(float, [np.median(speed[good]), np.quantile(speed[good], .9),
            np.mean(speed[good] < .05), np.median(acc), np.median(angles)])))
    quality['eligible'] = bool(values and quality['tracked_fraction'] >= .95
        and quality['valid_interval_fraction'] >= .9 and quality['jump_fraction'] <= .01)
    return quality, values


def fit(rows, k=4):
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score, silhouette_score
    from sklearn.preprocessing import RobustScaler
    eligible = [r for r in rows if r['quality']['eligible']]
    if len(eligible) < k*3:
        raise ValueError('insufficient quality-qualified recordings for clustering')
    raw = np.array([[r['features'][f] for f in FEATURES] for r in eligible])
    transformed = np.log1p(raw)
    # Remove task/hand group location, not task-dependent spread. Retain raw
    # units in summaries and warn that this cannot identify participant skill.
    centered = transformed.copy()
    groups = {}
    for i, row in enumerate(eligible):
        groups.setdefault((row['task'], row['hand']), []).append(i)
    for indices in groups.values():
        centered[indices] -= np.median(transformed[indices], axis=0)
    scaler = RobustScaler(quantile_range=(25, 75))
    matrix = np.clip(scaler.fit_transform(centered), -5, 5)
    model = KMeans(n_clusters=k, random_state=42, n_init=20).fit(matrix)
    labels = model.labels_
    stability = [adjusted_rand_score(labels, KMeans(n_clusters=k, random_state=s, n_init=10).fit_predict(matrix)) for s in (1, 7, 19, 61, 101)]
    clusters = []
    for c in range(k):
        idx = np.where(labels == c)[0]
        for i in idx:
            eligible[i]['cluster'] = int(c)
        distances = np.linalg.norm(matrix[idx]-model.cluster_centers_[c], axis=1)
        representatives = [eligible[i]['id'] for i in idx[np.argsort(distances)[:3]]]
        clusters.append({'cluster': c, 'recording_hands': len(idx),
            'median_raw_features': dict(zip(FEATURES, np.median(raw[idx], axis=0).tolist())),
            'task_adjusted_center': dict(zip(FEATURES, model.cluster_centers_[c].tolist())),
            'representatives': representatives})
    return {'features': FEATURES, 'k': k, 'eligible': len(eligible), 'excluded': len(rows)-len(eligible),
        'silhouette': float(silhouette_score(matrix, labels)),
        'seed_stability_adjusted_rand': stability,
        'normalization': 'log1p; subtract task/hand median; global IQR scaling; clip +/-5',
        'small_task_hand_groups': sum(len(x) < 3 for x in groups.values()),
        'scaler_center': scaler.center_.tolist(), 'scaler_scale': scaler.scale_.tolist(),
        'clusters': clusters}


def main():
    import h5py
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    def recordings():
        if args.root.is_file():
            # Sequential archive reads avoid thousands of random HDD seeks from
            # chunked HDF5. Only one recording is held in memory at a time.
            with tarfile.open(args.root, 'r|gz') as archive:
                for member in archive:
                    if member.isfile() and member.name.endswith('.hdf5'):
                        with archive.extractfile(member) as stream:
                            yield member.name, io.BytesIO(stream.read())
        else:
            for path in sorted(args.root.rglob('*.hdf5')):
                yield str(path.relative_to(args.root)), io.BytesIO(path.read_bytes())
    count = 0
    for index, (name, content) in enumerate(recordings()):
        with content, h5py.File(content) as source:
            frames = source['frame_data'][()]
            head = source['vr/vr_device_data/hmd'][()]
            for hand in ('left', 'right'):
                quality, values = features(frames, source[f'vr/vr_device_data/{hand}_controller'][()], head)
                rows.append({'id': f'{Path(name).name}:{hand}', 'file': name,
                    'hand': hand, 'task': str(source.attrs.get('/metadata/atus_activity', 'unknown')),
                    'quality': quality, 'features': values, 'cluster': None})
        count += 1
        if index % 25 == 0:
            print(f'Measured {index+1} recordings', flush=True)
    rows.sort(key=lambda row: row['id'])
    (args.output/'features.json').write_text(json.dumps(rows, indent=2, allow_nan=False)+'\n')
    summary = fit(rows)
    summary.update(schema='nadoc-motion-clusters-1', root=str(args.root.resolve()), recordings=count,
        scope='Exploratory recording-hand styles, NOT individual motor skill. Head-relative translational speed, acceleration and turning combine movement, head motion and sensor effects. No intended target/accuracy labels. Five source participants; no athlete/child/caffeine labels. Seed stability is not external validation.')
    (args.output/'clusters.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    (args.output/'assignments.json').write_text(json.dumps(rows, indent=2, allow_nan=False)+'\n')
    from .cluster_report import write_report
    write_report(args.output)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
