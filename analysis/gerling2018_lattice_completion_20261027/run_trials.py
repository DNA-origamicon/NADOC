"""Controlled whole-list trials; each output retains its actual parameters."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PREVIOUS = ROOT / "analysis/gerling2018_revnano_variations_20261027"


def main():
    selected = json.loads((PREVIOUS / "selected_best.json").read_text())["42hb13"]
    source = ROOT / selected["path"] / "input.rev"
    trials = [
        ("parity", []),
        ("loopout_edges_only", ["--loopout-graph"]),
        ("context_only", ["--context-weight", "1"]),
        ("loopout_context", ["--loopout-graph", "--context-weight", "1"]),
        ("loopout_context_lattice", ["--loopout-graph", "--context-weight", "1", "--lattice-edges", str(OUT/"lattice_edges.json"), "--lattice-bonus", "3"]),
    ]
    report = []
    reference = json.loads((ROOT / "backend/data/gerling2018_42hb13.json").read_text())["sequences"]
    scaffold = (ROOT / "backend/core/p7560.txt").read_text().strip()
    comp = scaffold.translate(str.maketrans("ACGT", "TGCA"))
    annotations = json.loads((ROOT / selected["path"] / "annotations.json").read_text())
    for label, flags in trials:
        dest = OUT / "trials" / label
        dest.mkdir(parents=True, exist_ok=True)
        if not (dest / "solver/summary.json").exists():
            (dest / "input.rev").write_text(source.read_text())
            (dest / "annotations.json").write_text(json.dumps(annotations, indent=2)+"\n")
            command = [str(ROOT/".venv/bin/python"), str(OUT/"runner/run.py"), str(dest/"input.rev"),
                       "--output", str(dest/"solver"), "--workers", "4", "--mu-min", "5",
                       "--sigma", "4", "--beta", ".2", "--ordered-pruning"] + flags
            with (dest / "solver.log").open("w") as log:
                process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            assert process.returncode in (0,2), (label, process.returncode)
        summary = json.loads((dest / "solver/summary.json").read_text())
        result = {"label": label, "path": str(dest.relative_to(ROOT)),
                  "seconds": summary["solver_seconds"], "parameters": summary["scientific_parameters"],
                  "context": summary["loopout_context"], "placed": 0, "covered": 0}
        if (dest / "solver/contactmap.json").exists():
            st, sc, circ = json.loads((dest / "solver/contactmap.json").read_text())
            occupied = set()
            assert circ and len(sc) == len(scaffold)
            for sid, m in st.items():
                i = int(sid)
                assert m["sequence53"] == reference[i]["sequence"]
                expected = {p for seg in annotations[i]["segments"] if seg["kind"] == "unpaired_T_candidate"
                            for p in range(seg["start_1based"]-1, seg["end_1based"])}
                assert expected == {p for p,b in enumerate(m["base_i53"]) if b < 0}
                for k,p in enumerate(m["base_i53"]):
                    if p < 0:
                        continue
                    assert m["sequence53"][k] == comp[p] and p not in occupied
                    assert sc[str(p)]["staple_id"] == i and sc[str(p)]["staple_base_id"] == k
                    occupied.add(p)
            result.update(placed=len(st), covered=len(occupied), placed_published_ids=[reference[int(s)]["index"] for s in st])
            if label == "parity":
                old = json.loads((PREVIOUS / "42hb13_best_contactmap.json").read_text())
                assert old == [st,sc,circ]
                result["exact_baseline_parity"] = True
        report.append(result)
        (OUT / "trial_results.json").write_text(json.dumps(report, indent=2)+"\n")
        print(label, result["placed"], result["covered"], result["seconds"], flush=True)


if __name__ == "__main__":
    main()
