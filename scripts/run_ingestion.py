import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import run_pipeline

if __name__ == "__main__":
    _, code = run_pipeline()
    raise SystemExit(code)
