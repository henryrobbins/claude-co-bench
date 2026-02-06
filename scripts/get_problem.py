#!/usr/bin/env python3
"""
Script to load a problem type by name and output its DESCRIPTION and solve function.

Usage:
    python scripts/get_problem.py "Aircraft landing"
    python scripts/get_problem.py "TSP" --src-dir "data/CO-Bench"
"""

import argparse
import sys

from src.controller import get_new_data, TASK_LIST


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--src-dir",
        type=str,
        default="data/CO-Bench",
        help="Source directory containing problem configs (default: data/CO-Bench)",
    )

    parser.add_argument(
        "--problem",
        type=str,
        help="Name of the problem to load (e.g., 'Aircraft landing', 'TSP')",
    )

    args = parser.parse_args()

    # Validate problem name
    if args.problem not in TASK_LIST:
        print(f"Error: Unknown problem type '{args.problem}'", file=sys.stderr)
        print("\nAvailable problem types:", file=sys.stderr)
        for task in TASK_LIST:
            print(f"  - {task}", file=sys.stderr)
        print("\nUse --list to see all available problems", file=sys.stderr)
        sys.exit(1)

    # Use src_dir for data_dir if not specified
    data_dir = args.src_dir

    try:
        # Load problem data
        data = get_new_data(
            task=args.problem,
            src_dir=args.src_dir,
            data_dir=data_dir,
        )

        # Output DESCRIPTION
        print("=" * 80)
        print("DESCRIPTION")
        print("=" * 80)
        print(data.problem)
        print()

        # Output solve function
        print("=" * 80)
        print("SOLVE FUNCTION")
        print("=" * 80)
        print(data.solve_template)

    except Exception as e:
        print(f"Error loading problem '{args.problem_name}': {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
