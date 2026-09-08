import json
from pathlib import Path

from backend.core.base_keys import base_family, parse_base_key


FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "base_key_cases.json").read_text()
)


def test_shared_valid_base_key_fixtures():
    for case in FIXTURES["valid"]:
        parsed = parse_base_key(case["key"])
        assert parsed is not None, case["key"]
        assert parsed.to_dict() == case["parsed"]
        assert base_family(case["key"]) == case["family"]


def test_shared_invalid_base_key_fixtures():
    for key in FIXTURES["invalid"]:
        assert parse_base_key(key) is None, key
