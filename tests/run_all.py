#!/usr/bin/env python
"""
Run every test script and exit non-zero if any of them fails.

The tests are plain assertion scripts rather than a pytest suite, so each one is
run as its own process — that keeps them individually runnable and stops one
module's import from affecting another's.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

scripts = sorted(p for p in HERE.glob("test_*.py"))
failed = []

for script in scripts:
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    tail = (result.stdout.strip().splitlines() or ["(no output)"])[-1]
    print(f"{'ok  ' if result.returncode == 0 else 'FAIL'} {script.name}: {tail}")
    if result.returncode != 0:
        failed.append(script.name)
        print(result.stdout.rstrip() or result.stderr.rstrip())

print(f"\n{len(scripts) - len(failed)}/{len(scripts)} test scripts passed")
sys.exit(1 if failed else 0)
