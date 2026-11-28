import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent

scripts = [
    "eval/a3_embedding.py",
    "eval/a3_suite.py",
    "eval/a3_faithfulness.py"
]

for script in scripts:
    print("\nRUNNING:", script, flush=True)
    subprocess.run(
        [sys.executable, script],
        cwd=root,
        check=True
    )

print("\nALL THREE EVALUATION LEVELS COMPLETED")
