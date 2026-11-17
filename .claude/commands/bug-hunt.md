---
description: Run the adversarial bug hunt (bugfinder → opponent → judge) as N independent parallel runs and compile a consolidated report
argument-hint: "[runs=3] [scope=app/]"
---

# Bug Hunt – Adversarial Pipeline Orchestrator

Arguments: `$ARGUMENTS`

Parse them as `[runs] [scope]`: a leading integer is the number of runs (default **3**, max 10); the rest is the scope to scan (default `app/`).

You orchestrate the pipeline. You do **not** find bugs, disprove bugs, or rule on disputes, and you have no opinion on code quality. You manage the flow and compile the report.

## Agents

| Stage | Subagent | Model |
|---|---|---|
| Find | `bugfinder` | haiku |
| Rebut | `opponent` | haiku |
| Rule | `judge` | opus |

## Runs

A run is one pass of `bugfinder → opponent → judge`. Runs are independent: nothing from run *i* may reach any agent in run *j*. Execute each stage for all runs at once by sending all its Agent calls in a single message.

Intermediate results (findings, rebuttals, verdicts) are handed over to you as subagent return values and stay in this conversation. Do not write them to files; only the two final files under Consolidation are written.

### Stage 1 – Find (N parallel calls)

Invoke `bugfinder` N times with an identical prompt: the scope, nothing else. Each returns its findings to you.

### Stage 2 – Rebut (N parallel calls)

For each run, invoke `opponent` with that run's findings verbatim. Each returns its rebuttals to you.

If a run's rebuttals do not cover every BUG, re-invoke `opponent` once for the missing ones; if still missing, treat them as `uncontested`.

### Stage 3 – Rule (one call per finding, all parallel)

For every finding in every run, invoke `judge` with exactly that BUG block and its REBUTTAL block, using the id `R{k}-{n}`. Never pass a judge more than one case, and never tell it how other runs or judges ruled.

If there are more than ~20 cases, send them in batches of 20 parallel calls.

## Information Flow

| From → To | What to pass |
|---|---|
| bugfinder → opponent | The run's findings, verbatim |
| opponent → judge | One BUG block + its REBUTTAL block, verbatim |
| judge → you | The VERDICT block |

Pass agent output on unedited. Do not summarize, reorder, correct, or annotate it.

## Consolidation

After all verdicts are in, group findings from different runs that describe the same defect (same file, overlapping lines, same incorrect behavior). When unsure whether two findings are the same defect, keep them separate. Assign each group a stable id `BUG-{n}`, ordered by severity, then by number of runs that confirmed it.

Write two files to `docs/issues/bug-hunt/{YYYYMMDD-HHMM}/`.

### `results.json` – machine-readable, one entry per group

```json
{
  "scope": "app/",
  "runs": 3,
  "bugs": [
    {
      "id": "BUG-1",
      "title": "...",
      "file": "app/...",
      "lines": "10-14",
      "severity": "high",
      "category": "logic",
      "claim": "...",
      "occurrences": [
        {"run": 1, "finding": "R1-4", "rebuttal": "contested", "ruling": "confirmed"}
      ]
    }
  ],
  "per_run": [
    {"run": 1, "findings": 0, "contested": 0, "confirmed": 0, "rejected": 0, "inconclusive": 0}
  ]
}
```

### `report.md` – human-readable

Include only groups with at least one `confirmed` ruling.

```markdown
## BUG-{n}: {short title}

**File:** {file path}
**Line(s):** {line range}
**Severity:** {severity}
**Category:** {category}
**Found in:** {a}/{N} runs · **Confirmed in:** {b}/{a} · **Sources:** R1-4, R3-2

{Description of the confirmed bug — the BugFinder's claim as validated by the Judge}

---
```

If the same defect was confirmed in one run and rejected in another, say so under the bug and quote both rationales — do not resolve the conflict yourself.

End with:

```markdown
## Summary

- **Scanned:** {scope}
- **Runs:** {N}
- **Distinct defects reported:** {groups} · **Confirmed:** {groups with ≥1 confirmed}
- **Confirmed in all runs:** {count} · **in one run only:** {count}
- **Conflicting rulings:** {count}

| Run | Findings | Contested | Confirmed | Rejected | Inconclusive |
|---|---|---|---|---|---|
```

Finish by telling the user the output directory and the summary numbers.
