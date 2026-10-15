"""Fail if a GitHub workflow interpolates untrusted or secret expressions directly into a shell script.

`${{ inputs.* }}`, `${{ github.event.* }}` and `${{ secrets.* }}` inside a `run:` block are expanded
into the script text before the shell sees it, so a crafted value becomes code (and a secret becomes
part of the command). They must be passed through `env:` and used as quoted variables instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

BAD = re.compile(r"\$\{\{\s*(inputs\.|github\.event\.|secrets\.|github\.head_ref)")


def check(path: Path) -> list[str]:
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    errs = []
    triggers = wf.get(True, wf.get("on")) or {}
    if isinstance(triggers, dict) and "workflow_dispatch" in triggers and (triggers["workflow_dispatch"] or {}).get("inputs"):
        if "permissions" not in wf:
            errs.append(f"{path.name}: workflow with inputs must declare least-privilege `permissions:`")
    for job_name, job in (wf.get("jobs") or {}).items():
        for i, step in enumerate(job.get("steps") or []):
            run = step.get("run")
            if isinstance(run, str) and BAD.search(run):
                errs.append(f"{path.name}: job {job_name} step {i + 1} ({step.get('name', 'unnamed')}): "
                            "untrusted/secret expression inside run:, pass it via env:")
    return errs


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".github/workflows")
    errs = [e for p in sorted(root.glob("*.y*ml")) for e in check(p)]
    for e in errs:
        print("ERROR:", e)
    if errs:
        return 1
    print(f"OK: {len(list(root.glob('*.y*ml')))} workflows, no untrusted expressions in run: blocks")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
