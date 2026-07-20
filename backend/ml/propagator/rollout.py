"""Autoregressive rollout — training + evaluation (dev-order #4).

Trains the dual-head GNN (Δposition + Δvelocity) on consecutive full-atomistic frames,
then advances the state by feeding its OWN prediction back in, measuring how RMSD grows
vs the true NAMD trajectory and WHERE error accumulates (DNA vs solvent). This is the
first real MVP milestone: does a learned atomistic propagator stay stable, and for how
many steps? (Not a speed test — see gnn.py for that.)

Neighbour list: rebuilt from the current coordinates every ``edge_refresh`` steps (as
classical MD reuses a neighbour list across steps). Training reuses the frame-0 list
(atoms move <~1 Å over the segment; a fair approximation for a short first milestone).

torch is an optional ad-hoc dep (see gnn.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def load(npz_path: str | Path) -> dict:
    npz_path = Path(npz_path)
    d = dict(np.load(npz_path))
    man = json.loads((npz_path.parent / (npz_path.stem + "_manifest.json")).read_text())
    d["dt_fs"] = man["dt_fs"]
    d["manifest"] = man
    return d


def _edges(pos: np.ndarray, cutoff: float) -> np.ndarray:
    from backend.ml.propagator.gnn import radius_edges  # noqa: PLC0415
    return radius_edges(pos, cutoff)


def _min_image_np(disp, box):
    b = np.asarray(box, dtype=np.float64)
    if b.shape != (3,) or not np.all(b > 0):
        return disp
    return disp - b * np.round(disp / b)


def train(npz_path, *, hidden=48, layers=2, cutoff=4.5, epochs=6, n_frames=None,
          lr=1e-3, device="cuda", seed=0, rollout_steps=1, noise=0.0,
          vel_reg=0.0, checkpoint=False, log=print):
    """Train the dual-head propagator with a (Δx, Δv) loss (std-normalised).

    ``rollout_steps`` > 1 = multi-step / BPTT training: unroll the model that many
    steps from each start frame and sum the loss against the true future frames, so
    the model learns to stay stable UNDER ITS OWN accumulated error (the standard fix
    for autoregressive blow-up). ``noise`` adds Gaussian position jitter to inputs
    (denoising-style robustness). ``vel_reg`` penalises predicted speeds above a
    physical cap (1.5× the max true speed) — directly targets the single-atom velocity
    runaway that blows up the rollout. ``checkpoint`` = gradient checkpointing so the
    multi-step unroll fits memory (recompute forward in backward → ~1× activation
    memory instead of K×; slower)."""
    import torch.utils.checkpoint as tcp  # noqa: PLC0415
    import torch  # noqa: PLC0415

    from backend.ml.propagator.gnn import PaiNNLite  # noqa: PLC0415

    d = load(npz_path)
    pos, vel, box = d["positions"], d["velocities"], d["box_ang"]
    T = pos.shape[0]
    nf = (T - 1) if n_frames is None else min(n_frames, T - 1)
    dev = torch.device(device if torch.cuda.is_available() else "cpu")

    z = torch.from_numpy(d["z"].astype("int64")).to(dev)
    edges = torch.from_numpy(_edges(pos[0], cutoff)).to(dev)   # fixed frame-0 list
    posT = torch.from_numpy(pos).to(dev)
    velT = torch.from_numpy(vel).to(dev)
    boxT = torch.from_numpy(box).to(dev)

    dx_all = _min_image_np(pos[1:nf + 1] - pos[:nf], box)
    dv_all = vel[1:nf + 1] - vel[:nf]
    dx_std = float(np.sqrt((dx_all ** 2).mean()) + 1e-8)
    dv_std = float(np.sqrt((dv_all ** 2).mean()) + 1e-8)
    v_cap = 1.5 * float(np.sqrt((vel[:nf] ** 2).sum(-1)).max())   # physical speed ceiling
    log(f"train: {nf} frames, {pos.shape[1]} atoms, {edges.shape[1]} edges, "
        f"dx_std={dx_std:.4f} dv_std={dv_std:.4f} v_cap={v_cap:.2f}, device={dev} | "
        f"K={rollout_steps} noise={noise} vel_reg={vel_reg} ckpt={checkpoint}")

    model = PaiNNLite(hidden=hidden, n_layers=layers, cutoff=cutoff).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    g = np.random.default_rng(seed)
    idx = np.arange(nf)
    K = max(1, rollout_steps)
    valid = idx[idx < nf - K]                              # need K true future frames
    for ep in range(epochs):
        g.shuffle(valid)
        tot = 0.0
        for t in valid:
            x, v = posT[t], velT[t]
            if noise > 0:
                x = x + noise * torch.randn_like(x)
            loss = 0.0
            for s in range(K):                             # unroll K steps (BPTT)
                if checkpoint:
                    dx_p, dv_p = tcp.checkpoint(model, z, x, v, edges, use_reentrant=False)
                else:
                    dx_p, dv_p = model(z, x, v, edges)
                x = x + dx_p
                v = v + dv_p
                tx = posT[t + s + 1]
                dxt = (x - tx) - boxT * torch.round((x - tx) / boxT)
                loss = loss + (dxt ** 2).mean() / dx_std ** 2 \
                    + ((v - velT[t + s + 1]) ** 2).mean() / dv_std ** 2
                if vel_reg > 0:                            # penalise super-physical speeds
                    sp = torch.sqrt((v ** 2).sum(-1) + 1e-8)
                    loss = loss + vel_reg * (torch.relu(sp - v_cap) ** 2).mean()
            loss = loss / K
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss.item())
        log(f"epoch {ep}: mean normalised loss {tot / max(1, len(valid)):.4f}")
    return model, {"dx_std": dx_std, "dv_std": dv_std, "cutoff": cutoff,
                   "rollout_steps": K, "noise": noise}


def rollout(model, npz_path, *, start=0, horizon=100, cutoff=4.5, edge_refresh=10,
            device="cuda", v_clamp=None):
    """Autoregressive rollout: feed predictions back; RMSD vs truth (all/DNA/solvent).

    ``v_clamp`` (Å/[NAMD vel unit]): if set, cap each atom's speed to this physical
    ceiling after every step — an inference-time physical constraint that directly
    targets the diagnosed single-atom velocity runaway (quick test of whether a
    restoring/conservation term is the missing ingredient)."""
    import torch  # noqa: PLC0415

    d = load(npz_path)
    pos, vel, box = d["positions"], d["velocities"], d["box_ang"]
    is_dna = d["is_dna"].astype(bool)
    dev = torch.device(device if torch.cuda.is_available() else "cpu")
    z = torch.from_numpy(d["z"].astype("int64")).to(dev)
    boxT = torch.from_numpy(box).to(dev)
    x = torch.from_numpy(pos[start]).to(dev)
    v = torch.from_numpy(vel[start]).to(dev)
    model.eval()
    curve = []
    H = min(horizon, pos.shape[0] - start - 1)
    diverged_at = None
    with torch.no_grad():
        edges = torch.from_numpy(_edges(x.cpu().numpy(), cutoff)).to(dev)
        for k in range(H):
            # Divergence guard: an autoregressive propagator can blow up; detect it
            # and stop cleanly (record the last stable step) rather than crash the
            # neighbour-list rebuild on NaN/inf.
            if not torch.isfinite(x).all():
                diverged_at = k
                break
            if k > 0 and k % edge_refresh == 0:
                edges = torch.from_numpy(_edges(x.cpu().numpy(), cutoff)).to(dev)
            dx, dv = model(z, x, v, edges)
            x = x + dx
            v = v + dv
            if v_clamp is not None:                      # physical speed ceiling
                sp = torch.sqrt((v ** 2).sum(-1, keepdim=True) + 1e-8)
                v = v * torch.clamp(v_clamp / sp, max=1.0)
            true = torch.from_numpy(pos[start + k + 1]).to(dev)
            err = x - true
            err = err - boxT * torch.round(err / boxT)
            e2 = (err ** 2).sum(-1).cpu().numpy()
            rmsd_all = float(np.sqrt(e2.mean()))
            curve.append({"step": k + 1, "rmsd_all": rmsd_all,
                          "rmsd_dna": float(np.sqrt(e2[is_dna].mean())),
                          "rmsd_solvent": float(np.sqrt(e2[~is_dna].mean()))})
            if not np.isfinite(rmsd_all) or rmsd_all > 50.0:   # unphysical → diverged
                diverged_at = k + 1
                break
    if curve:
        curve[-1]["diverged_at"] = diverged_at
    return curve


def ballistic_reference(npz_path, *, start=0, horizon=100):
    """No-model baseline: hold each atom fixed (RMSD = pure thermal drift of the true
    trajectory from the start frame). The learned rollout must stay BELOW this."""
    d = load(npz_path)
    pos, box = d["positions"], d["box_ang"]
    is_dna = d["is_dna"].astype(bool)
    x0 = pos[start]
    H = min(horizon, pos.shape[0] - start - 1)
    curve = []
    for k in range(H):
        err = _min_image_np(x0 - pos[start + k + 1], box)
        e2 = (err ** 2).sum(-1)
        curve.append({"step": k + 1, "rmsd_all": float(np.sqrt(e2.mean())),
                      "rmsd_dna": float(np.sqrt(e2[is_dna].mean())),
                      "rmsd_solvent": float(np.sqrt(e2[~is_dna].mean()))})
    return curve


def propagate_trajectory(model, npz_path, *, start=0, horizon=100, cutoff=4.5,
                         edge_refresh=10, device="cuda", v_clamp=None) -> np.ndarray:
    """Run the autoregressive rollout and RETURN the predicted coordinates
    [n_frames, n_atoms, 3] (start frame + each stable predicted step, stopping at
    divergence). For visualisation, not scoring."""
    import torch  # noqa: PLC0415

    d = load(npz_path)
    pos, vel = d["positions"], d["velocities"]
    dev = torch.device(device if torch.cuda.is_available() else "cpu")
    z = torch.from_numpy(d["z"].astype("int64")).to(dev)
    x = torch.from_numpy(pos[start]).to(dev)
    v = torch.from_numpy(vel[start]).to(dev)
    model.eval()
    frames = [x.cpu().numpy().copy()]
    H = min(horizon, pos.shape[0] - start - 1)
    with torch.no_grad():
        edges = torch.from_numpy(_edges(x.cpu().numpy(), cutoff)).to(dev)
        for k in range(H):
            if k > 0 and k % edge_refresh == 0:
                edges = torch.from_numpy(_edges(x.cpu().numpy(), cutoff)).to(dev)
            dx, dv = model(z, x, v, edges)
            x = x + dx
            v = v + dv
            if v_clamp is not None:
                sp = torch.sqrt((v ** 2).sum(-1, keepdim=True) + 1e-8)
                v = v * torch.clamp(v_clamp / sp, max=1.0)
            if not torch.isfinite(x).all():
                break
            frames.append(x.cpu().numpy().copy())
    return np.stack(frames)


def write_dcd(coords: np.ndarray, psf: str, out_dcd: str) -> str:
    """Write a [T, N, 3] coordinate array to a DCD paired with ``psf`` (VMD-loadable).

    A PSF carries no coordinates, so load the array as an in-memory trajectory
    (MemoryReader) before writing — a bare ``Universe(psf)`` has no frame to set."""
    import MDAnalysis as mda  # noqa: PLC0415
    from MDAnalysis.coordinates.memory import MemoryReader  # noqa: PLC0415
    u = mda.Universe(psf)
    if u.atoms.n_atoms != coords.shape[1]:
        raise ValueError(f"psf has {u.atoms.n_atoms} atoms, coords have {coords.shape[1]}")
    u.load_new(np.asarray(coords, dtype=np.float32), format=MemoryReader)
    with mda.Writer(out_dcd, n_atoms=u.atoms.n_atoms) as w:
        for _ in u.trajectory:
            w.write(u.atoms)
    return out_dcd


def report(npz_path, *, hidden=48, layers=2, cutoff=4.5, epochs=6, n_frames=None,
           horizon=100, start=None):
    """Train + roll out + print RMSD-growth curves vs the frozen-atom reference."""
    d = load(npz_path)
    T = d["positions"].shape[0]
    start = (T // 2) if start is None else start           # roll out on a held-out tail
    tr_frames = n_frames if n_frames is not None else start - 1
    model, stats = train(npz_path, hidden=hidden, layers=layers, cutoff=cutoff,
                         epochs=epochs, n_frames=tr_frames)
    roll = rollout(model, npz_path, start=start, horizon=horizon, cutoff=cutoff)
    base = ballistic_reference(npz_path, start=start, horizon=horizon)
    print(f"\n=== rollout — {Path(npz_path).name} (start frame {start}, dt={d['dt_fs']:.0f} fs) ===")
    print(f"{'step':>5} {'ps':>6} {'model_all':>10} {'model_DNA':>10} {'model_solv':>11} "
          f"{'frozen_all':>11}")
    for m, b in zip(roll, base):
        if m["step"] % max(1, len(roll) // 12) == 0 or m["step"] == 1:
            print(f"{m['step']:>5} {m['step'] * d['dt_fs'] / 1000:>6.3f} "
                  f"{m['rmsd_all']:>10.3f} {m['rmsd_dna']:>10.3f} {m['rmsd_solvent']:>11.3f} "
                  f"{b['rmsd_all']:>11.3f}")
    return {"rollout": roll, "frozen": base, "stats": stats, "start": start}
