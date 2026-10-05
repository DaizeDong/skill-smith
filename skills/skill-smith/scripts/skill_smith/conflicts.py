"""Pure selection over one catalog, capability observation and private policy."""
from copy import deepcopy
import hashlib
import json


SELECTOR_FIELDS = {"source_id", "kind", "name", "client", "scope", "relative_path", "install_name"}


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def validate_policy(policy):
    """Validate schema without selecting sources or interpreting observations."""
    if not isinstance(policy, dict) or type(policy.get('schema_version')) is not int or policy['schema_version'] != 1:
        raise ValueError('schema_version')
    if not isinstance(policy.get('entries'), list):
        raise ValueError('invalid_policy_entry')
    identities = set()
    for rule in policy['entries']:
        if not isinstance(rule, dict):
            raise ValueError('invalid_policy_entry')
        identity, selector = rule.get('id'), rule.get('selector')
        if (not isinstance(identity, str) or not identity or identity in identities
            or not isinstance(selector, dict) or not selector
            or set(selector) - SELECTOR_FIELDS
            or not all(isinstance(v, str) and v for v in selector.values())
            or any(not _strings(rule.get(k, [])) for k in ('tasks', 'formats', 'requires'))
            or rule.get('tier', 'main') not in ('main', 'fallback', 'specialist')):
            raise ValueError('invalid_policy_entry')
        identities.add(identity)


def validate_capabilities(capabilities):
    """Check observation shape; unknown statuses never acquire support."""
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get('capabilities'), dict):
        raise ValueError('invalid_selection_input')
    for name, observation in capabilities['capabilities'].items():
        if (not isinstance(name, str) or not name or not isinstance(observation, dict)
            or not isinstance(observation.get('status'), str) or not observation['status']
            or not _strings(observation.get('evidence', []))):
            raise ValueError('invalid_selection_input')


def fingerprint(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def matches(entry, selector):
    """Exact typed identity; no path, name, market or version guessing."""
    return bool(selector) and not (set(selector) - SELECTOR_FIELDS) and all(entry.get(k) == v for k, v in selector.items())


def capability_gaps(required, capabilities):
    gaps = []
    for name in required:
        observation = capabilities.get("capabilities", {}).get(name, {})
        if not isinstance(observation, dict) or observation.get("status") != "supported" or not observation.get("evidence"):
            gaps.append(name)
    return gaps


def select(request, capabilities, policy, snapshot):
    """Return selected/ambiguous/blocked/unavailable, never a deployment order.

    Policy entries have id, selector, tasks, formats, requires, and tier
    (main/fallback/specialist). An explicit id/selector skips applicability and
    tier preferences, but never skips capability or source checks.
    """
    if policy is None:
        return {"status": "uninitialized", "reason": "runtime_policy_missing", "selection": None}
    if capabilities is None:
        return {"status": "blocked", "reason": "capability_snapshot_missing", "selection": None}
    if not all(isinstance(value, dict) for value in (request, capabilities, policy, snapshot)):
        return {"status": "unsupported", "reason": "invalid_selection_input", "selection": None}
    if policy.get("schema_version") != 1 or snapshot.get("schema_version") != 1:
        return {"status": "unsupported", "reason": "schema_version"}
    try:
        validate_policy(policy)
        validate_capabilities(capabilities)
    except ValueError as exc:
        return {"status": "unsupported", "reason": str(exc), "selection": None}
    candidates = []
    override = request.get("override")
    for rule in policy.get("entries", []):
        if not isinstance(rule, dict) or not rule.get("id") or not isinstance(rule.get("selector"), dict):
            return {"status": "unsupported", "reason": "invalid_policy_entry"}
        if override is not None:
            if isinstance(override, str) and rule["id"] != override:
                continue
            if not isinstance(override, (str, dict)):
                return {"status": "unsupported", "reason": "invalid_override"}
        else:
            if rule.get("tasks") and request.get("task") not in rule["tasks"]:
                continue
            if rule.get("formats") and request.get("format") not in rule["formats"]:
                continue
        for record in snapshot.get("records", []):
            for ep in record.get("entrypoints", []):
                if not matches(ep, rule["selector"]) or (isinstance(override, dict) and not matches(ep, override)):
                    continue
                reasons = []
                if record.get("status", {}).get("resolved") != "yes" or not ep.get("source_hash"):
                    reasons.append("source_unresolved")
                if record.get("status", {}).get("enabled") == "no":
                    reasons.append("source_disabled")
                required = sorted(set(rule.get("requires", []) + request.get("requires", [])))
                reasons += ["capability:" + name for name in capability_gaps(required, capabilities)]
                candidates.append({"policy_id": rule["id"], "entrypoint": deepcopy(ep),
                                   "tier": rule.get("tier", "main"), "applicability": int(bool(rule.get("formats"))), "blocked": reasons})
    applicable = candidates
    if override is None and candidates:
        specificity = max(c["applicability"] for c in candidates)
        applicable = [c for c in candidates if c["applicability"] == specificity]
    available = [c for c in applicable if not c["blocked"]]
    result = {"candidates": candidates, "selection": None, "policy_hash": fingerprint(policy),
              "source_snapshot_hash": fingerprint(snapshot), "capability_snapshot_hash": fingerprint(capabilities),
              "runtime_discovery": "unchecked", "deployment": "not_requested"}
    if not available:
        result.update(status="blocked" if candidates else "unavailable",
                      reason="explicit_selection_unavailable" if override is not None else "no_eligible_entry")
        return result
    if override is None:
        # Format applicability is tested before these preferences. Specialists
        # remain independently selectable and are never removed from inventory.
        rank = {"main": 0, "specialist": 0, "fallback": 1}
        if any(c["tier"] not in rank for c in available):
            return dict(result, status="unsupported", reason="unknown_tier")
        best = min(rank[c["tier"]] for c in available)
        available = [c for c in available if rank[c["tier"]] == best]
    # Two rules may refer to the very same exact entrypoint. Deduplicate only
    # exact identities, never equal names across markets or source records.
    unique = {}
    for candidate in available:
        ep = candidate["entrypoint"]
        key = tuple(ep.get(k) for k in ("source_id", "kind", "client", "scope", "relative_path", "resolved_path"))
        unique.setdefault(key, candidate)
    if len(unique) != 1:
        return dict(result, status="ambiguous", reason="equal_candidates")
    return dict(result, status="selected", reason="user_override" if override is not None else "policy",
                selection=next(iter(unique.values())))
