# One brief, complete delivery

Collect these fields together and reuse answers already present in the request:

| Field | Required decision |
|---|---|
| Task and audience | One job and the person who judges the result |
| Inputs | Formats, size, source access and private-data boundary |
| Deliverables | Files, required content, failure states and how the user opens them |
| Platforms | Host, operating systems and installed capabilities |
| Configuration | Credential references and private companion; use G8 if configuration-bearing |
| Alternatives | Research findings, existing skills and overlap |
| Proof | Paired tasks, held-out positive/negative queries, evaluator and thresholds |
| Actions | Existing authorization for edits, installation, external calls or publication |

Freeze the proof policy before implementing. Policy, evaluator inputs, transcripts and results are
DATA in the private versioned companion. Public examples come from the fixture generator. A fixture
exercises the gate, but cannot prove live usefulness.

The final handoff contains:

- Candidate repo, base HEAD, current content hash, uncommitted diff and submodule revisions.
- Brief, research references, policy hash, evaluator identity and actual backend metadata.
- Manifest with artifact hashes, measurements, test commands and exit codes.
- External readiness: measured, unavailable, not run or not selected, per selected capability.
- Installed alias/resource and remote checks if those actions were part of the request.
- Remaining gates and a resume command using the same candidate and pinned policy.

`acceptance_gate.py` reports `resume_gates`. Re-running only reads existing artifacts; it does not
repeat external work. Ask the selected evaluator to regenerate missing evidence. Candidate changes
invalidate artifacts bound to the previous hash; policy changes require a newly reviewed pin.

For two clean rounds, use separate reviewer contexts and retain their source/result hashes. Changes
to code, docs, packaging, fixtures, scope or oracle reset the streak. Hashes protect integrity;
they do not make files unreadable to another process under the same account.
