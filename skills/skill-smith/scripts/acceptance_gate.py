#!/usr/bin/env python3
"""Validate frozen evidence contracts; independent reviewers decide acceptance.

Hashes establish artifact integrity, not the truth of a measurement or physical holdout isolation.
The independent evaluator owns the policy, raw results and provenance. Synthetic bundles can test
this contract but never produce an accepted skill. Caller-authored attestations also require
independent result approval, so this command never awards acceptance.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

LOCAL_GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), "score must be a finite number")
    require(0 <= value <= 1, "score must be between zero and one")
    return value


def validate_policy(policy):
    require(policy.get("schema") == 1, "unsupported policy schema")
    brief = policy.get("brief", {})
    require(isinstance(brief, dict), "brief must be an object")
    for field in ("task", "inputs", "deliverables", "platforms", "proof_tasks"):
        require(bool(brief.get(field)), "brief missing " + field)
    tasks = brief["proof_tasks"]
    require(isinstance(tasks, list) and all(isinstance(t, str) and t for t in tasks), "invalid proof tasks")
    require(len(tasks) >= 3 and len(set(tasks)) == len(tasks), "at least three distinct paired proof tasks are required")
    task_hashes = policy.get("proof_task_sha256")
    require(isinstance(task_hashes, dict) and set(task_hashes) == set(tasks), "proof task input hashes missing")
    require(all(isinstance(value, str) and len(value) == 64 for value in task_hashes.values()), "invalid proof task input hash")
    number(policy.get("min_lift", 0))
    require(number(policy.get("trigger_threshold", 0.9)) >= 0.9, "trigger threshold cannot be below 0.9")
    queries = policy.get("queries")
    require(isinstance(queries, list) and queries, "held-out queries missing")
    require(all(isinstance(q, dict) and isinstance(q.get("id"), str) and q["id"]
                and type(q.get("expected")) is bool and isinstance(q.get("query_sha256"), str)
                and len(q["query_sha256"]) == 64 for q in queries), "invalid held-out query")
    require(len({q["id"] for q in queries}) == len(queries), "duplicate held-out query ID")
    require(len({q["query_sha256"] for q in queries}) == len(queries), "duplicate held-out query content")
    require({q["expected"] for q in queries} == {True, False}, "held-out queries need positive and negative cases")
    train = policy.get("training_query_sha256", [])
    require(isinstance(train, list), "training query hashes must be a list")
    require(not ({q["query_sha256"] for q in queries} & set(train)), "training/holdout overlap")
    require(policy.get("not_applicable", []) in ([], ["G8"]), "only G8 may be explicitly not applicable")
    if policy.get("not_applicable"):
        require(bool(policy.get("config_not_applicable_reason")), "G8 needs an independently reviewed applicability reason")


def load_evidence(root, reference, candidate, policy_hash):
    require(isinstance(reference, dict), "invalid artifact reference")
    relative = reference.get("path")
    require(isinstance(relative, str) and relative, "artifact path missing")
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()), "artifact escaped the evidence directory")
    require(sha256(path) == reference.get("sha256"), "artifact hash mismatch")
    data = read_json(path)
    require(data.get("schema") == 1, "unsupported evidence schema")
    require(data.get("candidate_sha256") == candidate, "evidence belongs to another candidate")
    require(data.get("policy_sha256") == policy_hash, "evidence belongs to another policy")
    require(data.get("measurement") == "measured", "evidence was not measured")
    provenance = data.get("provenance", {})
    require(isinstance(provenance, dict), "measurement provenance missing")
    for key in ("evaluator", "request_id", "backend"):
        require(isinstance(provenance.get(key), str) and provenance[key].strip(), "provenance missing " + key)
    require(type(provenance.get("fixture")) is bool, "provenance must explicitly distinguish synthetic fixtures")
    return data


def eval_lift(data, policy):
    pairs = data.get("pairs")
    require(isinstance(pairs, list) and all(isinstance(p, dict) for p in pairs), "paired measurements missing")
    ids = [p.get("id") for p in pairs]
    require(len(ids) == len(set(ids)) and set(ids) == set(policy["brief"]["proof_tasks"]), "paired task set differs from the frozen brief")
    require(all(p.get("input_sha256") == policy["proof_task_sha256"][p["id"]] for p in pairs), "paired task input changed")
    differences = [number(p.get("with_skill")) - number(p.get("without_skill")) for p in pairs]
    lift = sum(differences) / len(differences)
    require(lift > 0 and lift >= policy.get("min_lift", 0), "paired mean lift did not meet the frozen bar")
    return {"status": "passed", "mean_lift": lift, "pairs": len(pairs), "min_lift": policy.get("min_lift", 0)}


def eval_triggers(data, policy):
    require(data.get("held_out") is True, "trigger measurements are not held out")
    trials = data.get("trials")
    require(isinstance(trials, list) and all(isinstance(t, dict) for t in trials), "trigger trials missing")
    expected = {q["id"]: q for q in policy["queries"]}
    ids = [t.get("id") for t in trials]
    require(len(ids) == len(set(ids)) and set(ids) == set(expected), "trigger set differs from frozen held-out queries")
    scores = {True: [], False: []}
    for trial in trials:
        query = expected[trial["id"]]
        require(trial.get("query_sha256") == query["query_sha256"], "trigger query content changed")
        require(type(trial.get("expected")) is bool and trial["expected"] == query["expected"], "expected trigger label changed")
        require(type(trial.get("triggered")) is bool, "trigger outcome must be boolean")
        scores[query["expected"]].append(trial["triggered"] == query["expected"])
    positive = sum(scores[True]) / len(scores[True])
    negative = sum(scores[False]) / len(scores[False])
    threshold = policy.get("trigger_threshold", 0.9)
    require(positive >= threshold and negative >= threshold, "positive or negative trigger rate below threshold")
    return {"status": "passed", "positive_rate": positive, "negative_rate": negative, "threshold": threshold}


def evaluate(manifest_path, policy_path, policy_pin, candidate_sha256, stage="local"):
    report = {"schema": 1, "accepted": False, "contract_valid": False, "verdict": "rejected", "gates": {},
              "candidate_sha256": candidate_sha256, "policy_sha256": policy_pin, "stage": stage,
              "evidence_assurance": "hash-checked evaluator attestations; no physical read isolation or independent live execution inferred"}
    try:
        require(sha256(policy_path) == policy_pin, "frozen policy hash mismatch")
        policy = read_json(policy_path)
        validate_policy(policy)
    except (OSError, ValueError, TypeError) as exc:
        report.update(verdict="invalid_policy", reason=str(exc))
        return report
    try:
        manifest = read_json(manifest_path)
        require(manifest.get("schema") == 1, "unsupported manifest schema")
        require(manifest.get("candidate_sha256") == candidate_sha256, "manifest candidate mismatch")
        require(manifest.get("policy_sha256") == policy_pin, "manifest policy mismatch")
        refs = manifest.get("gates")
        require(isinstance(refs, dict), "gate references missing")
        require(stage in ("local", "published"), "invalid acceptance stage")
    except (OSError, ValueError, TypeError) as exc:
        report.update(reason=str(exc))
        return report
    synthetic = False
    required = LOCAL_GATES + (("G6b",) if stage == "published" else ())
    for gate in required:
        if gate in policy.get("not_applicable", []):
            report["gates"][gate] = {"status": "not_applicable", "reason": policy["config_not_applicable_reason"]}
            continue
        if gate not in refs:
            report["gates"][gate] = {"status": "missing", "reason": "required measurement artifact missing"}
            continue
        try:
            data = load_evidence(Path(manifest_path).parent, refs[gate], candidate_sha256, policy_pin)
            synthetic |= data["provenance"]["fixture"]
            require(data.get("gate") == gate, "artifact gate ID mismatch")
            require(data.get("status") == "passed" and type(data.get("exit_code")) is int
                    and data["exit_code"] == 0, "gate did not complete successfully")
            if gate == "G1":
                row = eval_lift(data, policy)
            elif gate == "G2":
                row = eval_triggers(data, policy)
            else:
                row = {"status": "passed"}
            row["artifact_sha256"] = refs[gate]["sha256"]
            row["provenance"] = data["provenance"]
            report["gates"][gate] = row
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report["gates"][gate] = {"status": "rejected", "reason": str(exc)}
    report["contract_valid"] = all(r["status"] in ("passed", "not_applicable") for r in report["gates"].values())
    report["verdict"] = ("synthetic_only" if synthetic else "independent_review_required") if report["contract_valid"] else "rejected"
    report["acceptance_scope"] = "contract_only; independent approval of actual evaluator results is required"
    report["resume_gates"] = [g for g, row in report["gates"].items() if row["status"] not in ("passed", "not_applicable")]
    return report


def candidate_snapshot(root):
    """Bind bytes, file modes, gitlinks and inspected submodule revisions to one snapshot."""
    root = Path(root).resolve()
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              check=True, timeout=30).stdout.decode("utf-8")
    indexed = {}
    for entry in filter(None, git("ls-files", "--stage", "-z").split("\0")):
        metadata, name = entry.split("\t", 1)
        mode, revision, stage = metadata.split()
        require(stage == "0", "candidate contains unresolved index stages: " + name)
        indexed[name] = {"mode": mode, "revision": revision}
    names = set(indexed) | set(filter(None, git("ls-files", "--others", "--exclude-standard", "-z").split("\0")))
    records = []
    for name in sorted(names):
        path = root / name
        require(not path.is_symlink() and path.resolve().is_relative_to(root), "candidate path escapes through a link: " + name)
        entry = indexed.get(name, {})
        record = {"path": name, "index_mode": entry.get("mode")}
        if entry.get("mode") == "160000":
            record.update(kind="submodule", gitlink=entry["revision"])
            if not (path / ".git").exists():
                record["state"] = "uninitialized"
            else:
                record["head"] = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                                 capture_output=True, check=True, timeout=30).stdout.decode().strip()
                record["content"] = candidate_snapshot(path)
        elif path.is_file():
            record.update(kind="file", content=sha256(path))
            # Windows does not expose Git's executable bit through stat; index_mode binds it.
            record["worktree_executable"] = bool(path.stat().st_mode & 0o111) if os.name != "nt" else None
        elif path.is_dir():
            raise ValueError("unrecognized candidate directory: " + name)
        else:
            record["kind"] = "deleted"
        records.append(record)
    return hashlib.sha256(json.dumps({"schema": 2, "files": records}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--policy")
    parser.add_argument("--policy-sha256")
    parser.add_argument("--stage", choices=("local", "published"), default="local")
    parser.add_argument("--snapshot", action="store_true", help="print candidate content hash without evaluating")
    args = parser.parse_args(argv)
    try:
        candidate = candidate_snapshot(args.repo)
        if args.snapshot:
            print(candidate)
            return 0
        if not all((args.manifest, args.policy, args.policy_sha256)):
            parser.error("--manifest, --policy and independently pinned --policy-sha256 are required")
        for name in (args.manifest, args.policy):
            require(not Path(name).resolve().is_relative_to(Path(args.repo).resolve()), "runtime evidence belongs outside the tool repository")
        report = evaluate(args.manifest, args.policy, args.policy_sha256, candidate, args.stage)
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if report["accepted"] else 1
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"accepted": False, "verdict": "error", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
