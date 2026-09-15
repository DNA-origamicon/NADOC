"""Compare frozen CPU/CUDA stage settings, including seeds and force caps."""

import hashlib
import json


def settings(text):
    result = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError("Unrecognized stage input line: " + line)
        key, value = (part.strip() for part in line.split("=", 1))
        if key in result:
            raise ValueError("Duplicate stage setting: " + key)
        result[key] = value
    return result


def matching_protocol(cpu_text, cuda_text):
    cpu, cuda = settings(cpu_text), settings(cuda_text)
    if cpu.get("backend") != "CPU":
        raise ValueError("CPU reference must use CPU")
    expected = "CPU" if cpu.get("sim_type") == "MC" else "CUDA"
    if cuda.get("backend") != expected:
        raise ValueError("Incorrect comparison backend")
    ignored = {"backend", "backend_precision", "use_edge"}

    def physics(values):
        return {
            k: v
            for k, v in values.items()
            if k not in ignored and not k.startswith("CUDA_")
        }

    a, b = physics(cpu), physics(cuda)
    if a != b:
        changed = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        raise ValueError("CPU/CUDA stage settings differ: " + ", ".join(changed))
    required = {
        "sim_type",
        "steps",
        "seed",
        "T",
        "interaction_type",
        "salt_concentration",
        "external_forces",
    }
    if cpu.get("sim_type") == "MD":
        required |= {"dt", "thermostat"}
    if not required <= set(a):
        raise ValueError(
            "Missing explicit physical settings: "
            + ", ".join(sorted(required - set(a)))
        )
    return hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest()
