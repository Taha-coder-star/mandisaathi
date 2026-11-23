"""Batch role: one run of ingest -> QC -> features -> F1/F3 scoring -> coverage (C13). Runs once and exits."""
import sys


def main() -> int:
    print("batch ok", flush=True)  # pipeline steps land here from task 3.x on
    return 0


if __name__ == "__main__":
    sys.exit(main())
