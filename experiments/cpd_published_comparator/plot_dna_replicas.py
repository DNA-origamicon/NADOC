"""Standalone diagnostic plots for the short replicated DNA campaign."""

import argparse
import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main(root):
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    for system, color in [("cpd", "#1769aa"), ("control", "#cb6b20")]:
        for replica in (1, 2, 3):
            folder = root / system / f"replica-{replica}"
            if not (folder / "analysis.json").exists():
                continue
            r = json.loads((folder / "analysis.json").read_text())
            m = r["metrics"]
            t = [x["production_ps"] for x in m]
            style = ["-", "--", ":"][replica - 1]
            label = f"{system} {replica}"
            axes[0, 0].plot(
                t,
                [x["aligned_heavy_rmsd_initial_A"] for x in m],
                style,
                color=color,
                label=label,
                alpha=0.85,
            )
            axes[1, 0].plot(
                t,
                [x["central_contact_fraction"] for x in m],
                style,
                color=color,
                alpha=0.7,
            )
            keys = []
            energy = []
            for line in (folder / "run.log").read_text().splitlines():
                if line.startswith("ETITLE:"):
                    keys = line.split()[1:]
                if line.startswith("ENERGY:"):
                    e = dict(zip(keys, map(float, line.split()[1:])))
                    if e["TS"] > 60000:
                        energy.append(e)
            axes[0, 1].plot(
                [(e["TS"] - 60000) * 0.002 for e in energy],
                [e["TEMP"] for e in energy],
                style,
                color=color,
                alpha=0.5,
            )
            if system == "cpd":
                distances = np.array([x["lesion_bonds_A"] for x in m])
                for i, bond_color in enumerate(["#6b4597", "#33946c"]):
                    axes[1, 1].plot(
                        t,
                        distances[:, i],
                        style,
                        color=bond_color,
                        alpha=0.7,
                        label=["C5–C5", "C6–C6"][i] if replica == 1 else None,
                    )
    axes[0, 0].set_ylabel("Aligned DNA heavy-atom RMSD (Å)")
    axes[0, 0].set_title("Relative to initial solute")
    axes[0, 0].legend(ncol=2, fontsize=8)
    axes[0, 1].set_ylabel("Temperature (K)")
    axes[0, 1].axhline(300, color="black", lw=0.7)
    axes[0, 1].set_title("NPT production")
    axes[1, 0].set_ylabel("Central base-pair contact fraction")
    axes[1, 0].set_ylim(-0.05, 1.05)
    axes[1, 0].set_title("Donor–acceptor distance < 3.5 Å; diagnostic")
    axes[1, 1].set_ylabel("CPD crosslink length (Å)")
    axes[1, 1].legend()
    axes[1, 1].set_title("Three independent replicas")
    for ax in axes.flat:
        ax.set_xlabel("Production time (ps)")
        ax.grid(alpha=0.2)
    fig.suptitle(
        "Replicated DNA short stability pilot — not an equilibrium validation",
        fontsize=13,
    )
    fig.savefig(root / "replica_diagnostics.png", dpi=180)
    fig.savefig(root / "replica_diagnostics.pdf")
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    main(p.parse_args().root.resolve())
