---
name: sesip-security-audit
description: Use when performing security code audit for IoT/embedded products, reviewing SESIP compliance, or conducting adversarial second-pass vulnerability review
---

# SESIP Security Audit Methodology

## Overview

Complete security audit workflow combining initial vulnerability discovery with false-positive filtering. Minimizes hallucinations through strict evidence requirements and multi-phase validation.

**Core principle:** Every finding must be traceable to explicit evidence (file paths + symbols + snippets). Distinguish facts from inferences.

## When to Use

- SESIP certification assessments for IoT/embedded devices
- Pre-certification security audits
- Second-pass adversarial review of vulnerability findings
- Security peer review requiring minimal false positives

**Trigger signals:**
- "Audit this codebase for security issues"
- "SESIP assessment coming up"
- "Review these findings for false positives"
- "Need to verify vulnerability findings"

## Audit Phases

### Phase A — Purpose and Architecture

Identify repository characteristics:
- **Purpose**: Library, service, CLI, firmware, app, etc.
- **Stack**: Languages, frameworks, build system, entry points
- **Runtime**: Daemon, plugin, server, mobile app, kernel module
- **Trust boundaries**: Data flows between untrusted/trusted zones
- **History**: Known vulnerabilities (if provided)

### Phase B — Isolation Map

Split repo into bounded audit units. For each unit document:
- Paths and responsibilities
- Entry points / exported APIs
- Untrusted inputs
- Privileged operations
- External interfaces (network/IPC/file/UI/serialization)
- External dependencies
- Testing hooks (unit tests, fuzz targets, harnesses)
- Risk profile (attack surface level)

### Phase C — Function Inventory

Per section, enumerate 10-30 security-relevant functions/classes grouped by:
- Parsing, auth, storage, crypto, protocol

Identify hotspots:
- Parsing, boundary checks, memory ownership, deserialization, privilege transitions, concurrency

### Phase D — Vulnerability Analysis

Generate prompt pack per section:
1. Deep manual audit (white-box)
2. Input-surface audit
3. Memory safety audit (C/C++/Rust unsafe, JNI, NAPI, FFI)
4. AuthN/AuthZ and privilege boundary audit
5. Supply-chain and dependency risk audit
6. False-positive and hallucination filter

## Finding Report Format

Every vulnerability must produce both human-readable and JSON output.

### Required Fields

| Field | Description |
|-------|-------------|
| Vuln ID | Format: VULN-S{n}-{###} |
| Name | Short, specific title |
| Confidence | Likely / Possible / Unclear + rationale |
| Description | What is wrong and where |
| Evidence | file path(s), symbol(s), line numbers, minimal snippet |
| Files affected | List of affected files |
| Attack scenario | How attacker reaches it |
| Impact | Confidentiality / Integrity / Availability |
| Preconditions | Permissions, config, build flags |
| Fix recommendation | Concrete remediation |
| Patch direction | What kind of change is needed |
| Verification steps | How to confirm the fix |

### Finding JSON Schema

```json
{
  "vuln_id": { "type": "string", "pattern": "^[A-Z0-9]+-S[0-9]+-[0-9]{3}$" },
  "title": { "type": "string" },
  "confidence": { "enum": ["likely", "possible", "unclear"] },
  "severity": { "enum": ["critical", "high", "medium", "low", "informational", "not_visible"] },
  "severity_rationale": { "type": "string" },
  "description": { "type": "string" },
  "evidence": [{ "file": "", "symbol": "", "lines": "", "snippet": "" }],
  "files_affected": [{ "type": "string" }],
  "attack_scenario": {
    "untrusted_inputs": [],
    "entry_point": "",
    "trigger_steps": []
  },
  "impact": {
    "confidentiality": "none|low|medium|high|not_visible",
    "integrity": "none|low|medium|high|not_visible",
    "availability": "none|low|medium|high|not_visible",
    "scope_notes": ""
  },
  "preconditions": [],
  "reproduction": { "level": "", "steps": [] },
  "fix_recommendation": { "type": "string" },
  "patch_direction": { "type": "string" },
  "verification": { "tests": [], "code_checks": [], "runtime_checks": [] },
  "tags": []
}
```

## Severity Normalization

| Rating | Definition |
|--------|------------|
| **CRITICAL** | RCE, auth bypass, sandbox escape, widespread data exfiltration |
| **HIGH** | Privilege escalation, significant data exposure, exploitation plausible with constraints |
| **MEDIUM** | DoS, limited data exposure, specific config/timing needed |
| **LOW** | Minor info leak, hard-to-exploit edge cases |
| **INFORMATIONAL** | Best-practice gaps, risky patterns, no clear exploit |
| **NOT VISIBLE** | Cannot estimate due to missing context |

**Rules:**
- Possible/Unclear ≠ Critical unless evidence is very strong
- Missing reachability context → severity = not_visible

## Anti-Hallucination Rules

1. **Only claim what you can prove**: File paths + symbols + exact evidence
2. **Clear separation**: Observed facts | Inferences (marked) | Hypotheses/Questions
3. **Label all findings**: Likely / Possible / Unclear + rationale
4. **Never infer implementation from naming alone**
5. **If not visible, say "Not visible"** and list what's needed

## False Positive Detection

When reviewing findings, classify each as:

| Result | Definition |
|--------|------------|
| **Confirmed** | Strong, direct evidence |
| **Partially supported** | Some evidence, key assumptions unproven |
| **False positive** | Incorrect, misleading, or unsupported |
| **Hallucination** | References code paths not visible in evidence |

### Mandatory Validation Checks

1. **Evidence existence**: Files, symbols, line numbers exist in provided repo tree
2. **Data-flow reachability**: Untrusted inputs actually reach vulnerable code
3. **Boundary & context**: Privileged/sandboxed context, OS protections
4. **API semantics**: APIs used as claimed, not mitigated by guarantees
5. **Exploitability realism**: Preconditions realistic, stated impact accurate

### False Positive Review Record

```
Vuln ID:
Original confidence:
Original severity:
Validation result: Confirmed / Partially supported / False positive / Hallucination
Key evidence validated:
Key assumptions that failed:
Reasoning:
Recommended action: Keep as-is / Downgrade confidence / Downgrade severity / Mark as informational / Reject finding
```

### JSON Output for Review

```json
{
  "vuln_id": "VULN-S1-001",
  "validation_result": "false_positive",
  "original_confidence": "likely",
  "original_severity": "high",
  "revised_confidence": "unclear",
  "revised_severity": "informational",
  "evidence_validated": [{"file": "path", "symbol": "foo()", "status": "exists"}],
  "failed_assumptions": ["Untrusted input not externally reachable"],
  "reasoning": "Code path not reachable from untrusted inputs",
  "recommended_action": "downgrade_and_keep_as_note"
}
```

## Quick Reference

| Check | Question |
|-------|----------|
| Evidence | File + symbol + line number exist? |
| Reachability | Untrusted input reaches vulnerable code? |
| Context | Sandboxed/privileged context limits impact? |
| API | Behavior mitigated by API guarantees? |
| Exploit | Preconditions realistic, impact accurate? |

## Common False Positive Sources

- Assuming `strcpy`-like behavior where bounds-checked APIs are used
- Assuming deserialization where schema-validated parsing occurs
- Assuming privilege escalation without actual boundary crossing
- Assuming missing context without explicit evidence