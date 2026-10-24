"""Write the licence policy to space/license_policy.json for the browser app.

Run after changing scripts/license_policy.py. test_space_sync.py fails if the
exported file is out of date.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from license_policy import export_rules  # noqa: E402

TARGET = pathlib.Path(__file__).resolve().parent.parent / "space" / "license_policy.json"


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(export_rules(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
