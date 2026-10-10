"""The committed openapi.json must match the API, because the UI generates
its types from it (see scripts/export_openapi.py)."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RP_FASTAPI_API_KEY", "test-key-for-ci-only")

from scripts.export_openapi import schema_text  # noqa: E402


def test_committed_schema_is_current():
    committed = (ROOT / "openapi.json").read_text(encoding="utf-8")
    assert json.loads(committed) == json.loads(schema_text()), (
        "openapi.json is out of date; run: python scripts/export_openapi.py"
    )


def test_every_public_read_has_a_typed_response():
    schema = json.loads(schema_text())
    for path, operations in schema["paths"].items():
        get = operations.get("get")
        if not get or path == "/health":
            continue
        content = get["responses"]["200"].get("content", {}).get("application/json", {})
        assert "$ref" in content.get("schema", {}), f"GET {path} has no response model"
