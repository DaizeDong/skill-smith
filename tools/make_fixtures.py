"""Generate the synthetic public report examples; never imports runtime data."""
import argparse
import hashlib
import json
from pathlib import Path


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = {
        "tool": "fleet_check", "schema": 2, "utc": "2000-01-01T00:00:00Z", "duration_s": 0,
        "exit": 0, "verdict": "GREEN", "digest": "Synthetic schema example; no fleet was inspected",
        "coverage": {"evaluated": 0, "not_evaluated": 1},
        "totals": {"pass": 0, "fail": 0, "warn": 0, "skip": 0, "unknown": 1},
        "checks": {}, "failures": [], "unobserved": ["synthetic: not observed"],
        "warnings": [], "ci_execution": {}}
    for name in ("fleet-check-status.json.example", "fleet-check-status.json.tmp.example"):
        write_json(Path(args.out) / name, report)
    description = "Use to summarize synthetic report records and return a concise evidence table."
    write_json(Path(args.out) / "worklist.json.example", [{
        "path": "<absolute-path-to-synthetic-skill>/SKILL.md", "name": "acme-report",
        "cap": 60, "old": description, "old_len": len(description), "new": ""}])


if __name__ == "__main__":
    main()
