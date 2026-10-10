"""Writes the API's OpenAPI schema to openapi.json at the repo root.

The schema is committed so the UI can generate its types from it and
check its interfaces against the real responses (see the UI's
src/app/api). tests/test_contract.py fails when this file is out of date,
so regenerate it after changing any request or response model:

    python scripts/export_openapi.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RP_FASTAPI_API_KEY", "schema-export")

from src.main import app  # noqa: E402


def schema_text() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    (ROOT / "openapi.json").write_text(schema_text(), encoding="utf-8", newline="\n")
    print("openapi.json written")
