"""Render every native menu state offscreen and retain a browsable formatting atlas."""

import argparse
from collections import Counter
import html
import json
import os
from pathlib import Path
import subprocess
import time

from PIL import Image, ImageDraw

from tools.vr_workflows.tour_catalog import ROOT


def report(output: Path, *, baseline: Path | None = None, renderer_exit_code: int | None = None) -> dict:
    """Write evidence before deciding whether validation passed, including partial runs."""
    source = output / "states.jsonl"
    states = [json.loads(line) for line in source.read_text().splitlines()] if source.exists() else []
    failures = [row for row in states if row["layout"] not in ("valid", "not-instrumented")]
    pixel_failures = [row["name"] for row in states if not row.get("pixels_visible", True)]
    missing = [row["image"] for row in states if not (output / row["image"]).is_file()]
    groups = Counter(row["name"].split("-")[0] for row in states)
    completion_path = output / "render-complete.json"
    completion = json.loads(completion_path.read_text()) if completion_path.exists() else {}
    complete = completion.get("complete") is True and completion.get("rendered_states") == len(states)
    if renderer_exit_code is None:
        renderer_exit_code = completion.get("renderer_exit_code", 0)
    summary = {
        "passed": bool(states) and complete and renderer_exit_code == 0 and not failures and not missing and not pixel_failures,
        "complete": complete,
        "native_checks": completion,
        "renderer_exit_code": renderer_exit_code,
        "rendered_states": len(states),
        "groups": dict(groups),
        "layout_failures": [{key: row[key] for key in ("name", "layout", "layout_detail")} for row in failures],
        "missing_images": missing,
        "uninstrumented_states": [row["name"] for row in states if row["layout"] == "not-instrumented"],
        "pixel_failures": pixel_failures,
        "observation": "Production OpenGL, identity panel pose, orthographic camera fitted to bounds, 1200 x 1200 pixels. No OpenXR session, tracked-head override, or desktop capture. Dynamic states are deterministic fixtures; native menu pixels are real.",
        "baseline": str(baseline) if baseline else None,
        "gallery_state_key": {
            "wheels": ["midrange", "hover", "minimum", "maximum", "midrange"],
            "buttons": ["idle", "hover", "pressed", "selected", "disabled"],
            "cards": ["closed", "open and hover", "open", "selected child", "disabled and open"],
        },
    }
    sheets = []
    for start in range(0, len(states), 12):
        sheet = Image.new("RGB", (1200, 1696), "#101722")
        draw = ImageDraw.Draw(sheet)
        for offset, state in enumerate(states[start:start + 12]):
            x, y = (offset % 3) * 400, (offset // 3) * 424
            path = output / state["image"]
            if path.is_file():
                with Image.open(path) as image:
                    image.thumbnail((400, 400))
                    sheet.paste(image, (x, y))
            draw.text((x + 8, y + 401), state["name"][:54], fill="white")
            if state["layout"] not in ("valid", "not-instrumented") or not state.get("pixels_visible", True):
                draw.rectangle((x + 1, y + 1, x + 398, y + 398), outline="#fa5f65", width=3)
        name = f"contact-sheet-{start // 12 + 1:03}.jpg"
        sheet.save(output / name, quality=92)
        sheets.append(name)
    summary["contact_sheets"] = sheets
    review_states = [row for row in states if not row["name"].startswith(("part-", "assembly-")) or (row["name"].startswith("part-") and row["name"].endswith("page-1")) or row["name"] == "assembly-right-assembly-expanded-page-1"]
    review_sheets = []
    for start in range(0, len(review_states), 6):
        sheet = Image.new("RGB", (1200, 1872), "#101722")
        draw = ImageDraw.Draw(sheet)
        for offset, state in enumerate(review_states[start:start + 6]):
            x, y = (offset % 2) * 600, (offset // 2) * 624
            path = output / state["image"]
            if path.is_file():
                with Image.open(path) as image:
                    image.thumbnail((600, 600))
                    sheet.paste(image, (x, y))
            draw.text((x + 8, y + 601), state["name"], fill="white")
        name = f"review-sheet-{start // 6 + 1:03}.jpg"
        sheet.save(output / name, quality=94)
        review_sheets.append(name)
    summary["review_sheets"] = review_sheets
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    intro = f"<p>{html.escape(summary['observation'])}</p><p>{len(states)} states; {len(failures)} layout failures; {len(pixel_failures)} pixel failures; {len(missing)} missing images; complete: {complete}; renderer exit: {renderer_exit_code}. Red outlines identify layout or pixel failures. Individual images open at full resolution.</p>"
    if baseline:
        intro += f'<p>Baseline: <a href="{html.escape(os.path.relpath(baseline / "index.html", output))}">comparison atlas</a></p>'
    cards = []
    for row in states:
        name, image = html.escape(row["name"]), html.escape(row["image"])
        problem = row["layout"] not in ("valid", "not-instrumented") or not row.get("pixels_visible", True)
        details = {"texts": row["texts"], "pixel_regions": row.get("text_regions", []), "pixels_visible": row.get("pixels_visible")}
        cards.append(f'<article class="{"failure" if problem else ""}"><a href="{image}"><img loading="lazy" src="{image}" alt="{name}"></a><b>{name}</b><p>{html.escape(row["layout_detail"] or row["layout"])}</p><details><summary>Rendered text, scale and pixel regions</summary><pre>{html.escape(json.dumps(details, indent=2))}</pre></details></article>')
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>VR menu formatting atlas</title><style>body{background:#101722;color:#e4edf8;font:15px system-ui;margin:24px}a{color:#8fcfff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:18px}article{border:1px solid #35465b;padding:10px;overflow:auto}article.failure{border:3px solid #fa5f65}img{width:100%;height:auto}pre{white-space:pre-wrap}</style><h1>VR menu formatting atlas</h1>' + intro + '<div class="grid">' + ''.join(cards) + '</div>')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--viewtools-stream", type=Path, help="Production .viewtools stream, or directory of .bin streams retained from an isolated browser session")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--validate", action="store_true", help="Return failure after retaining images/report when a layout audit fails")
    args = parser.parse_args()
    output = args.output or ROOT / ".development-artifacts/vr-menu-formatting" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=args.report_only)
    result = None if args.report_only else 0
    if not args.report_only:
        build = ROOT / "native/vr_viewer/build"
        env = {**os.environ, "PATH": "/usr/bin:/bin:" + os.environ.get("PATH", "")}
        with (output / "build.log").open("w") as log:
            subprocess.run(["cmake", "-S", str(ROOT / "native/vr_viewer"), "-B", str(build)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            subprocess.run(["cmake", "--build", str(build), "--target", "nadoc-vr-menu-render-audit", "-j1"], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        command = [str(build / "nadoc-vr-menu-render-audit"), str(output.resolve())]
        if args.viewtools_stream:
            command.append(str(args.viewtools_stream.resolve()))
        with (output / "render.log").open("w") as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=False).returncode
    summary = report(output, baseline=args.baseline, renderer_exit_code=result)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(output / "index.html", flush=True)
    if result or (args.validate and not summary["passed"]):
        raise SystemExit(result or 1)


if __name__ == "__main__":
    main()
