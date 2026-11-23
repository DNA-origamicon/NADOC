"""Optional float64, device-resident GJF for linear stiffness/Stokes friction.

Only sampled states cross to the host. Host sample storage preserves the CPU API;
VRAM is independent of trajectory length. No implicit precision/model changes.
"""

import numpy as np

from backend.physics.trajectory_storage import allocate_samples


class CudaUnavailable(RuntimeError):
    """CUDA cannot be admitted; auto mode can select CPU before integration."""


def required_bytes(stiffness):
    return (
        stiffness.nnz * 16 + (stiffness.shape[0] + 1) * 8 + stiffness.shape[0] * 8 * 48
    )


class LinearGJF:
    def __init__(self, stiffness, mass, gamma, external, anchors):
        try:
            import torch

            if not torch.cuda.is_available():
                raise CudaUnavailable("CUDA is not available")
            free, total = torch.cuda.mem_get_info()
            need = required_bytes(stiffness)
            if need > min(max(0, free - 512 * 1024**2), total * 0.5):
                raise CudaUnavailable(f"CUDA headroom: need {need} bytes")
            self.torch = torch
            self.device = torch.device("cuda")
            self.k = torch.sparse_csr_tensor(
                torch.from_numpy(stiffness.indptr.astype(np.int64)),
                torch.from_numpy(stiffness.indices.astype(np.int64)),
                torch.from_numpy(stiffness.data.astype(np.float64, copy=False)),
                size=stiffness.shape,
                device=self.device,
            )
            self.m, self.gamma, self.external, self.anchors = [
                torch.as_tensor(x, dtype=torch.float64, device=self.device)
                for x in (mass, gamma, external, anchors)
            ]
            # Force one actual sparse operation before auto mode commits to CUDA.
            torch.mv(self.k, torch.zeros_like(self.m))
            torch.cuda.synchronize()
        except (ImportError, RuntimeError) as exc:
            raise CudaUnavailable(str(exc)) from exc

    def integrate(
        self,
        q0,
        *,
        kT,
        dt,
        n_steps,
        n_equil,
        sample_every,
        seed=0,
        progress_cb=None,
        rng=None,
        v0=None,
        translation_only=False,
    ):
        """rng is an optional NumPy oracle for matched-impulse validation only."""
        from backend.physics.snupi_dynamics import _GJFDiverged, _report_progress

        t = self.torch
        q = t.as_tensor(q0, dtype=t.float64, device=self.device).clone()
        v = (
            t.zeros_like(q)
            if v0 is None
            else t.as_tensor(v0, dtype=t.float64, device=self.device).clone()
        )
        half = self.gamma * dt / (2 * self.m)
        b = 1 / (1 + half)
        a = (1 - half) * b
        bd, bd2 = b * dt, b * dt * dt / (2 * self.m)
        bh, dh, bm = b * dt / (2 * self.m), dt / (2 * self.m), b / self.m
        sig = t.sqrt(2 * self.gamma * kT * dt)
        generator = t.Generator(device=self.device).manual_seed(seed)
        sigma_cpu = sig.cpu().numpy() if rng is not None else None

        def force(x):
            return self.external - t.mv(self.k, x) - self.anchors * x

        f = force(q)
        sample_shape = np.asarray(q0).reshape(-1, 6)[:, :3] if translation_only else q0
        samples = allocate_samples(sample_shape, n_steps, n_equil, sample_every)
        index = 0
        for step in range(n_steps):
            beta = (
                t.as_tensor(
                    rng.standard_normal(q.shape) * sigma_cpu, device=self.device
                )
                if rng is not None
                else t.randn(
                    q.shape, dtype=t.float64, device=self.device, generator=generator
                )
                * sig
            )
            q = q + bd * v + bd2 * f + bh * beta
            new = force(q)
            v = a * v + dh * (a * f + new) + bm * beta
            f = new
            if step >= n_equil and (step - n_equil) % sample_every == 0:
                sampled = q.reshape(-1, 6)[:, :3] if translation_only else q
                samples[index] = sampled.cpu().numpy()
                index += 1
            if step % 500 == 0 or step == n_steps - 1:
                if not bool(t.isfinite(q).all()) or not bool(t.isfinite(v).all()):
                    raise _GJFDiverged(f"CUDA GJF diverged at step {step} (dt={dt})")
                _report_progress(progress_cb, step + 1, n_steps)
        return samples, v.cpu().numpy()


def select_backend(backend, stiffness, mass, gamma, external, anchors, *, supported):
    """Resolve optional acceleration before a trajectory; never change force models."""
    if backend not in {"cpu", "cuda", "auto"}:
        raise ValueError("SNUPI backend must be cpu, cuda or auto")
    cuda = None
    reason = None
    if backend != "cpu":
        if not supported:
            reason = "CUDA supports linear Stokes dynamics without simulated tails"
            if backend == "cuda":
                raise ValueError(reason)
        else:
            try:
                cuda = LinearGJF(stiffness, mass, gamma, external, anchors)
            except CudaUnavailable as exc:
                if backend == "cuda":
                    raise
                reason = str(exc)
    execution = {
        "backend": "cuda" if cuda else "cpu",
        "fallback_reason": reason,
        "precision": "float64",
        "rng": "torch-cuda" if cuda else "numpy",
    }
    if cuda is not None:
        execution.update(
            device=cuda.torch.cuda.get_device_name(),
            torch_version=cuda.torch.__version__,
        )
    return cuda, execution
