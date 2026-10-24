"""Fail if the Space's licence rules have drifted from the Python policy.

The browser app reimplements classify() in JavaScript, reading its rules from
space/license_policy.json. If that export goes stale, the public tool grades
licences by different rules than the published dataset -- so regenerate and
compare rather than trusting anyone to remember.

Run: python scripts/test_space_sync.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from license_policy import export_rules  # noqa: E402

EXPORT = ROOT / "space" / "license_policy.json"


def main():
    if not EXPORT.exists():
        print(f"FAILED - {EXPORT} is missing")
        print("  generate with: python scripts/export_license_rules.py")
        return 1

    on_disk = json.loads(EXPORT.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(export_rules()))  # normalise tuples to lists

    if on_disk != current:
        print("FAILED - space/license_policy.json is stale")
        for key in sorted(set(on_disk) | set(current)):
            if on_disk.get(key) != current.get(key):
                print(f"  {key}: disk={on_disk.get(key)} policy={current.get(key)}")
        print("  regenerate with: python scripts/export_license_rules.py")
        return 1

    print(f"ok - exported licence rules match ({len(current)} rule groups)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
