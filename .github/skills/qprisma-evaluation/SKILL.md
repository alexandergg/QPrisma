---
name: qprisma-evaluation
description: Run QPrisma benchmark and evaluation workflows for agent quality measurement, including custom benchmark and ablation runs.
---

# QPrisma Evaluation Skill

Use this skill for benchmark execution and evaluation reporting.

## Prerequisite check

Verify local dependencies and services before evaluation:

```bash
cd backend && .venv/Scripts/python.exe .claude/skills/run-eval/scripts/check_infra.py
```

## Common runs

### Quick custom benchmark

```bash
cd backend && .venv/Scripts/python.exe -m evaluation.scripts.run_first_eval
```

### Expanded benchmark

```bash
cd backend && .venv/Scripts/python.exe -m evaluation.scripts.run_first_eval --expanded
```

### Ablation study

```bash
cd backend && .venv/Scripts/python.exe -m evaluation.run_evaluation --config evaluation/configs/ablation_study.json
```

## Reporting

- Summarize accuracy, latency, and comparative outcomes by method.
- Highlight failure patterns and recommended follow-up experiments.
