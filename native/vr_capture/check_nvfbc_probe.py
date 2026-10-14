#!/usr/bin/env python3
"""Build and test the optional NvFBC capability probe without loading NVIDIA.

Supply the reviewed NVIDIA-authored MIT API 1.9 header explicitly. This tool
never downloads an SDK or accepts its terms. Its fake library aborts if the
probe creates a capture session. All generated files stay in a new output dir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HEADER_SHA256 = "f6f8b21b9f05b7e24c77e5d9c6d141ddf01c606b71e6fe5e74426c0cc128cee6"
MOCK = r'''
#include <NvFBC.h>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdio>
namespace {
const char* mode() { const char* p=getenv("NADOC_NVFBC_PROBE_TEST"); return p?p:"success"; }
NVFBCSTATUS create(NVFBC_SESSION_HANDLE* h, NVFBC_CREATE_HANDLE_PARAMS* p) {
 assert(p->dwVersion == NVFBC_CREATE_HANDLE_PARAMS_VER);
 assert(p->privateData == nullptr && p->privateDataSize == 0);
 assert(p->eBackend == NVFBC_BACKEND_DIRECT && p->bUseEGL == NVFBC_TRUE);
 if (!strcmp(mode(), "unsupported")) return NVFBC_ERR_UNSUPPORTED;
 *h=42; return NVFBC_SUCCESS;
}
NVFBCSTATUS destroy(NVFBC_SESSION_HANDLE h, NVFBC_DESTROY_HANDLE_PARAMS* p) {
 assert(h==42 && p->dwVersion == NVFBC_DESTROY_HANDLE_PARAMS_VER);
 fprintf(stderr,"mock handle destroyed\n"); return NVFBC_SUCCESS;
}
NVFBCSTATUS status(NVFBC_SESSION_HANDLE h, NVFBC_GET_STATUS_PARAMS* p) {
 assert(h==42 && p->dwVersion == NVFBC_GET_STATUS_PARAMS_VER);
 assert(p->dwPid==123 && p->dwDbusTimeoutMs == 1000);
 if (!strcmp(mode(), "dbus")) return NVFBC_ERR_DBUS;
 p->bIsCapturePossible=NVFBC_TRUE; p->bCanCreateNow=NVFBC_TRUE;
 p->dwCaptureTargetCount=1; p->captureTargetSizes[0]={2160,1200};
 if (!strcmp(mode(), "denied")) p->bIsCapturePossible=NVFBC_FALSE;
 if (!strcmp(mode(), "oversized")) p->dwCaptureTargetCount=500;
 return NVFBC_SUCCESS;
}
const char* error(NVFBC_SESSION_HANDLE h) { assert(h==42); return "mock D-Bus \"error\"\n"; }
NVFBCSTATUS forbidden(NVFBC_SESSION_HANDLE, NVFBC_CREATE_CAPTURE_SESSION_PARAMS*) { abort(); }
}
extern "C" NVFBCSTATUS NvFBCCreateInstance(NVFBC_API_FUNCTION_LIST* p) {
 assert(p->dwVersion == NVFBC_VERSION);
 if (!strcmp(mode(), "version")) return NVFBC_ERR_API_VERSION;
 p->nvFBCCreateHandle=create; p->nvFBCDestroyHandle=destroy;
 p->nvFBCGetStatus=status; p->nvFBCGetLastErrorStr=error;
 p->nvFBCCreateCaptureSession=forbidden;
 return NVFBC_SUCCESS;
}
'''


def check(header, output):
    header = Path(header).resolve(strict=True)
    if hashlib.sha256(header.read_bytes()).hexdigest() != HEADER_SHA256:
        raise ValueError("Header differs from the reviewed, pinned NVIDIA API 1.9 artifact")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    include = output / "include"
    include.mkdir()
    shutil.copy2(header, include / "NvFBC.h")
    mock = output / "mock_nvfbc.cpp"
    mock.write_text(MOCK)
    compiler = shutil.which("c++")
    if not compiler:
        raise RuntimeError("c++ compiler unavailable")
    source = Path(__file__).with_name("nvfbc_probe.cpp")
    probe = output / "nvfbc_probe"
    flags = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I" + str(include)]
    subprocess.run(flags + [str(source), "-ldl", "-o", str(probe)], check=True, timeout=30)
    subprocess.run(flags + ["-shared", "-fPIC", str(mock), "-o", str(output / "libnvidia-fbc.so.1")],
                   check=True, timeout=30)
    checks = []
    for mode, expected in (("success", 0), ("unsupported", 2), ("dbus", 2),
                           ("denied", 2), ("oversized", 2), ("version", 2)):
        env = os.environ.copy()
        env.update(LD_LIBRARY_PATH=str(output), NADOC_NVFBC_PROBE_TEST=mode)
        # Ensure outside library injections cannot supersede the fake driver.
        env.pop("LD_PRELOAD", None)
        env.pop("LD_AUDIT", None)
        run = subprocess.run([str(probe), "--pid", "123"], env=env,
                             capture_output=True, text=True, timeout=5)
        rows = [json.loads(line) for line in run.stdout.splitlines()]
        assert run.returncode == expected, (mode, run.returncode, run.stderr)
        if mode not in ("unsupported", "version"):
            assert rows[-1]["stage"] == "destroy_handle"
            assert "mock handle destroyed" in run.stderr
        else:
            assert "mock handle destroyed" not in run.stderr
        checks.append({"case": mode, "exit": run.returncode, "events": rows})
    for pid in ("0", "-1", "abc", "4294967296"):
        run = subprocess.run([str(probe), "--pid", pid], capture_output=True, text=True, timeout=5)
        assert run.returncode == 64 and not run.stdout
        checks.append({"case": "invalid_pid_" + pid, "exit": run.returncode})
    report = {"all_passed": True, "real_nvidia_library_loaded": False,
              "header_sha256": HEADER_SHA256,
              "probe_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "checks": checks}
    (output / "checks.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = check(args.header, args.output)
    print(json.dumps({"all_passed": report["all_passed"], "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
