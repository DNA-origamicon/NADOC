"""Identical NAMD package finalization on local and remote preparation hosts."""
from __future__ import annotations
import json


def finalize_package(job_dir, package_subdir, name_stem, body, seed_kwargs_graphene):
    from backend.api.routes_md import _harmonicize_seed_anchors, _audit_external_force_configs
    # NAMD consumes one fixedAtoms union; retain the semantic groups for the UI.
    package_path = job_dir / package_subdir
    manifest_path = package_path / "manifest.json"
    if manifest_path.exists():
        _manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _manifest["anchor_groups"] = {
            "structure": list(body.anchors or []),
            "surface": list(body.surface_anchors or []),
        }
        if body.oxdna_job_id and (body.anchors or body.surface_anchors):
            _manifest["anchor_inheritance"] = {
                "source_engine": "oxdna",
                "source_job_id": body.oxdna_job_id,
            }
        _text = json.dumps(_manifest, indent=2)
        manifest_path.write_text(_text, encoding="utf-8")
        mirror = package_path / "nadoc_md_run.json"
        if mirror.exists():
            mirror.write_text(_text, encoding="utf-8")
    if body.graphene_nanopore and seed_kwargs_graphene is not None:
        # The descriptor is deliberately package-local and in the same recentered
        # frame as the DNA seed. The atomistic graphene builder consumes this file;
        # keeping it beside the frozen package also makes previews/retries reproducible.
        import json as _json
        nanopore = seed_kwargs_graphene
        package_path = job_dir / package_subdir
        (package_path / "graphene_nanopore.json").write_text(
            _json.dumps(nanopore, indent=2), encoding="utf-8"
        )
        # NAMD fixedAtoms reads the B column from a full-system PDB. Mark only the
        # GRPH segment and force CUDA offload: GPU-resident NAMD rejects fixed atoms.
        system_pdb = package_path / f"{name_stem}.pdb"
        # Reuse the DNA-anchor marker when one exists: NAMD permits one fixedAtoms
        # file, so that full-system marker must be the union of graphene + both DNA
        # anchor sets. With no DNA anchors, create the graphene-only marker.
        confs = list(package_path.glob("*.conf"))
        existing_marker = None
        for conf in confs:
            for ln in conf.read_text(encoding="utf-8").splitlines():
                if ln.lstrip().startswith("fixedAtomsFile"):
                    candidate = package_path / ln.split(None, 1)[1].strip()
                    if candidate.exists():
                        existing_marker = candidate
                        break
            if existing_marker:
                break
        marker_source = existing_marker or system_pdb
        marker_lines = []
        for line in marker_source.read_text(encoding="utf-8").splitlines():
            if line.startswith(("ATOM", "HETATM")):
                line = line.ljust(80)
                prior = float(line[60:66].strip() or 0.0)
                b = 1.0 if line[72:76].strip().startswith("GR") else prior
                line = line[:60] + f"{b:6.2f}" + line[66:]
            marker_lines.append(line)
        marker_name = existing_marker.name if existing_marker else "graphene_fixed.pdb"
        (package_path / marker_name).write_text("\n".join(marker_lines) + "\n", encoding="utf-8")
        fixed_block = (
            f"fixedAtoms         on\nfixedAtomsFile     {marker_name}\n"
            "fixedAtomsCol      B\n"
        )
        for conf in confs:
            text_conf = conf.read_text(encoding="utf-8")
            if "fixedAtomsFile" not in text_conf:
                anchor = next((ln for ln in text_conf.splitlines(True) if ln.lstrip().startswith("coordinates")), None)
                if anchor:
                    text_conf = text_conf.replace(anchor, anchor + fixed_block, 1)
            conf.write_text(text_conf, encoding="utf-8")
        manifest_path = package_path / "manifest.json"
        if manifest_path.exists():
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["graphene_nanopore"] = nanopore
            manifest["graphene_nanopore"]["fixed_atoms_file"] = marker_name
            manifest["graphene_nanopore"]["model"] = (
                "fixed neutral CA sites using CHARMM aromatic-carbon Lennard-Jones parameters"
            )
            # Production children inherit this marker through the ordinary anchor
            # channel, keeping the membrane fixed even when no DNA anchor exists.
            manifest.setdefault("files", {})["anchors"] = marker_name
            manifest_path.write_text(_json.dumps(manifest, indent=2), encoding="utf-8")
    # The package, not the executor, defines the physics. Harmonicize every relax
    # package that has DNA anchors and/or graphene so local, Alpine and RunPod stage
    # byte-identical GPU-compatible confs. This was accidentally gated on oxDNA or
    # graphene-only, leaving native DNA+graphene jobs on fixedAtoms.
    if body.anchors or body.surface_anchors or body.graphene_nanopore:
        _harmonicize_seed_anchors(
            job_dir / package_subdir,
            name_stem=name_stem,
            force_constant=body.anchor_k or 0.02,
            graphene_force_constant=50.0,
            force_gpu_resident=(body.gpu_resident == "on"),
        )
    _audit_external_force_configs(job_dir / package_subdir)
