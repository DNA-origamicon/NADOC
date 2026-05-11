"""Phase 1 sub-domain smoke test against a live `just dev` backend.

Loads ``workspace/hinge.nadoc``, exercises every new endpoint added in Phase 1,
prints PASS/FAIL per step. Run with:

    export PATH="$HOME/.local/bin:$PATH"
    uv run python -m scripts.smoke_test_subdomains
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any

import httpx

BACKEND = "http://127.0.0.1:8000"
NADOC_PATH = os.path.abspath("workspace/hinge.nadoc")
NADOC_SUBDOMAIN_NS_LITERAL = "6f8a8b1e-5b3a-4b1f-8c2a-d0e5b3f1a204"


PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"


def step(name: str) -> None:
    print(f"\n=== {name} ===")


def ok(msg: str) -> None:
    print(f"[{PASS}] {msg}")


def bad(msg: str) -> None:
    print(f"[{FAIL}] {msg}")


def info(msg: str) -> None:
    print(f"[{INFO}] {msg}")


def assert_eq(label: str, got: Any, expected: Any) -> bool:
    if got == expected:
        ok(f"{label}: {got!r}")
        return True
    bad(f"{label}: got {got!r}, expected {expected!r}")
    return False


def assert_true(label: str, cond: bool) -> bool:
    if cond:
        ok(label)
        return True
    bad(label)
    return False


def main() -> int:
    failures = 0

    with httpx.Client(base_url=BACKEND, timeout=30.0) as cx:
        # 1. Backend reachable (use /openapi.json — always 200, no design state required)
        step("1. Health check")
        try:
            r = cx.get("/openapi.json")
            r.raise_for_status()
            ok(f"backend live on {BACKEND}")
        except Exception as exc:
            bad(f"backend not reachable: {exc}")
            print("\nStart the backend first: `just dev` from /home/joshua/NADOC")
            return 1

        # 2. Load hinge.nadoc
        step("2. POST /api/design/load with hinge.nadoc")
        r = cx.post("/api/design/load", json={"path": NADOC_PATH})
        if r.status_code != 200:
            bad(f"load failed: {r.status_code} {r.text[:300]}")
            return 1
        ok(f"loaded {NADOC_PATH}")
        design = r.json()

        # 3. Find an overhang (design dict is nested under "design" key in the response)
        step("3. Find an overhang in the design")
        design_dict = design.get("design") or design  # fallback for older shape
        ovhgs = design_dict.get("overhangs") or []
        if not ovhgs:
            bad(f"no overhangs in {NADOC_PATH} — design has 0 overhang specs")
            return 1
        ovhg = ovhgs[0]
        ovhg_id = ovhg["id"]
        info(f"using overhang {ovhg_id} (total: {len(ovhgs)})")

        # 4. GET sub-domains for that overhang
        step("4. GET /api/design/overhang/{id}/sub-domains")
        r = cx.get(f"/api/design/overhang/{ovhg_id}/sub-domains")
        if r.status_code != 200:
            bad(f"list failed: {r.status_code} {r.text[:300]}")
            return 1
        listing = r.json()
        sub_domains = listing["sub_domains"]
        assert_eq("sub_domain count for backward-compat overhang", len(sub_domains), 1)
        sd0 = sub_domains[0]
        whole_length = sd0["length_bp"]
        info(f"whole-overhang sub_domain length_bp={whole_length}, id={sd0['id']}")

        # 4b. Verify deterministic UUID5
        expected_id = str(uuid.uuid5(uuid.UUID(NADOC_SUBDOMAIN_NS_LITERAL), f"{ovhg_id}:whole"))
        if not assert_eq("deterministic UUID5", sd0["id"], expected_id):
            failures += 1

        # 5. Split at midpoint
        step("5. POST split at midpoint")
        split_at = max(1, whole_length // 2)
        r = cx.post(
            f"/api/design/overhang/{ovhg_id}/sub-domains/split",
            json={"sub_domain_id": sd0["id"], "split_at_offset": split_at},
        )
        if r.status_code != 200:
            bad(f"split failed: {r.status_code} {r.text[:300]}")
            return 1
        # Re-list
        sub_domains = cx.get(f"/api/design/overhang/{ovhg_id}/sub-domains").json()["sub_domains"]
        if not assert_eq("sub_domain count after split", len(sub_domains), 2):
            failures += 1
        total_after = sum(sd["length_bp"] for sd in sub_domains)
        if not assert_eq("Σ lengths preserved", total_after, whole_length):
            failures += 1
        sd_5p, sd_3p = sub_domains
        info(f"5' half: id={sd_5p['id']} length={sd_5p['length_bp']}")
        info(f"3' half: id={sd_3p['id']} length={sd_3p['length_bp']}")
        if not assert_eq("5' half kept original ID", sd_5p["id"], sd0["id"]):
            failures += 1

        # 6. PATCH name + color + sequence_override on the 5' half
        step("6. PATCH name + color + sequence_override on 5' half")
        override = "A" * sd_5p["length_bp"]
        r = cx.patch(
            f"/api/design/overhang/{ovhg_id}/sub-domains/{sd_5p['id']}",
            json={
                "name": "smoke_test_locked",
                "color": "#ff8800",
                "sequence_override": override,
                "notes": "Phase 1 smoke test",
            },
        )
        if r.status_code != 200:
            bad(f"patch failed: {r.status_code} {r.text[:300]}")
            failures += 1
        else:
            ok("patch returned 200")
            patched = cx.get(f"/api/design/overhang/{ovhg_id}/sub-domains").json()["sub_domains"][0]
            if not assert_eq("name", patched["name"], "smoke_test_locked"):
                failures += 1
            if not assert_eq("color", patched["color"], "#ff8800"):
                failures += 1
            if not assert_eq("sequence_override", patched["sequence_override"], override):
                failures += 1

        # 7. Recompute annotations
        step("7. POST recompute-annotations on 5' half")
        r = cx.post(
            f"/api/design/overhang/{ovhg_id}/sub-domains/{sd_5p['id']}/recompute-annotations"
        )
        if r.status_code != 200:
            bad(f"recompute failed: {r.status_code} {r.text[:300]}")
            failures += 1
        else:
            patched = cx.get(f"/api/design/overhang/{ovhg_id}/sub-domains").json()["sub_domains"][0]
            info(f"Tm={patched['tm_celsius']}°C  GC%={patched['gc_percent']}  "
                 f"hairpin={patched['hairpin_warning']}  dimer={patched['dimer_warning']}")
            if not assert_true("gc_percent computed", patched["gc_percent"] is not None):
                failures += 1
            # Tm may be None for all-A homopolymers if NN params don't cover them — accept either.

        # 8. Top-level overhang sequence write → expect 409
        step("8. PATCH /api/design/overhang/{id} with new sequence — expect 409 (override conflict)")
        r = cx.patch(f"/api/design/overhang/{ovhg_id}", json={"sequence": "G" * whole_length})
        if r.status_code == 409:
            ok(f"correctly rejected with 409: {r.json().get('detail')}")
        else:
            bad(f"expected 409, got {r.status_code}: {r.text[:200]}")
            failures += 1

        # 9. PATCH /api/design/tm-settings
        step("9. PATCH /api/design/tm-settings (Na+ to 1000 mM)")
        r = cx.patch("/api/design/tm-settings", json={"na_mM": 1000.0})
        if r.status_code != 200:
            bad(f"tm-settings patch failed: {r.status_code} {r.text[:300]}")
            failures += 1
        else:
            ok("tm-settings patched")
            patched = cx.get(f"/api/design/overhang/{ovhg_id}/sub-domains").json()["sub_domains"][0]
            # Cache should be invalidated; tm_celsius back to None until next recompute
            if not assert_eq("Tm cache invalidated", patched["tm_celsius"], None):
                failures += 1

        # 10. Merge back
        step("10. POST merge — expect 1 sub-domain again")
        # Clear override first so merge isn't impeded
        cx.patch(
            f"/api/design/overhang/{ovhg_id}/sub-domains/{sd_5p['id']}",
            json={"sequence_override": None},
        )
        r = cx.post(
            f"/api/design/overhang/{ovhg_id}/sub-domains/merge",
            json={"sub_domain_a_id": sd_5p["id"], "sub_domain_b_id": sd_3p["id"]},
        )
        if r.status_code != 200:
            bad(f"merge failed: {r.status_code} {r.text[:300]}")
            failures += 1
        else:
            sub_domains = cx.get(f"/api/design/overhang/{ovhg_id}/sub-domains").json()["sub_domains"]
            if not assert_eq("sub_domain count after merge", len(sub_domains), 1):
                failures += 1
            if not assert_eq("merged length restored", sub_domains[0]["length_bp"], whole_length):
                failures += 1
            if not assert_eq("survivor kept A's ID", sub_domains[0]["id"], sd_5p["id"]):
                failures += 1

        # 11. Round-trip via save/load
        step("11. Save + reload round-trip (verify sub_domains preserved)")
        tmp_path = "/tmp/hinge_smoke_test.nadoc"
        # Use POST /design/save with absolute path
        r = cx.post("/api/design/save", json={"path": tmp_path})
        if r.status_code != 200:
            bad(f"save failed: {r.status_code} {r.text[:300]}")
            failures += 1
        else:
            ok(f"saved to {tmp_path}")
            # Split again so we have something non-trivial to round-trip
            sd0_id = sub_domains[0]["id"]
            cx.post(
                f"/api/design/overhang/{ovhg_id}/sub-domains/split",
                json={"sub_domain_id": sd0_id, "split_at_offset": split_at},
            )
            cx.patch(
                f"/api/design/overhang/{ovhg_id}/sub-domains/{sd0_id}",
                json={"name": "round_trip_test", "color": "#00ff00"},
            )
            # Save again, then reload
            r = cx.post("/api/design/save", json={"path": tmp_path})
            r.raise_for_status()
            r = cx.post("/api/design/load", json={"path": tmp_path})
            r.raise_for_status()
            reloaded = cx.get(f"/api/design/overhang/{ovhg_id}/sub-domains").json()["sub_domains"]
            if not assert_eq("sub_domain count after reload", len(reloaded), 2):
                failures += 1
            if not assert_eq("name survives round-trip", reloaded[0]["name"], "round_trip_test"):
                failures += 1
            if not assert_eq("color survives round-trip", reloaded[0]["color"], "#00ff00"):
                failures += 1

        # Cleanup: reload pristine hinge.nadoc so user's app state isn't littered
        step("12. Cleanup: reload pristine hinge.nadoc")
        cx.post("/api/design/load", json={"path": NADOC_PATH})
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        ok("cleanup done")

    print(f"\n{'=' * 50}")
    if failures == 0:
        print(f"{PASS}: all smoke-test steps passed")
        return 0
    print(f"{FAIL}: {failures} step(s) failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
