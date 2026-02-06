#!/usr/bin/env python3
"""
Script to evaluate code for a given problem type and return feedback.

Usage:
    python scripts/evaluate_code.py --problem "Aircraft landing" --code "path/to/solution.py"
    python scripts/evaluate_code.py --problem "TSP" --code "solution.py"
"""

import argparse
import sys

from src.controller import get_new_data, TASK_LIST
from src.evaluate import Evaluator


def read_code_from_file(file_path: str) -> str:
    """Read code from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: Code file not found: {file_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading code file: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate code for a CO-Bench optimization problem"
    )

    parser.add_argument(
        "--problem",
        type=str,
        required=True,
        help="Name of the problem to evaluate (e.g., 'Aircraft landing', 'TSP')",
    )

    parser.add_argument(
        "--code",
        type=str,
        help="Path to file containing the solve function code",
    )

    args = parser.parse_args()

    # Validate that code is provided
    if not args.code:
        print("Error: --code is required", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    # Validate problem name
    if args.problem not in TASK_LIST:
        print(f"Error: Unknown problem type '{args.problem}'", file=sys.stderr)
        print("\nAvailable problem types:", file=sys.stderr)
        for task in TASK_LIST:
            print(f"  - {task}", file=sys.stderr)
        sys.exit(1)

    # Read code
    code = read_code_from_file(args.code)

    # Validate that code contains a solve function
    if "def solve(" not in code:
        print("Error: Code must contain a 'solve' function definition", file=sys.stderr)
        sys.exit(1)

    # Use default directories
    src_dir = "data/CO-Bench"
    data_dir = src_dir

    try:
        # Load problem data
        print(f"Loading problem data for '{args.problem}'...")
        data = get_new_data(
            task=args.problem,
            src_dir=src_dir,
            data_dir=data_dir,
        )

        # Create evaluator with default settings
        print("Creating evaluator...")
        evaluator = Evaluator(
            data=data,
            timeout=10,
            cpu_num=None,
            feedback_length=64,
        )

        # Run evaluation
        print(f"Evaluating code on {len(data.test_cases)} test cases...")
        feedback = evaluator.evaluate(code)

        # Display results
        print("\n" + "=" * 80)
        print("EVALUATION RESULTS")
        print("=" * 80)
        print(f"\nOverall Score: {feedback.score:.4f}")
        print(f"Dev Score: {feedback.dev_score:.4f}")
        print(f"Test Score: {feedback.test_score:.4f}")
        print("\nFeedback:")
        print(feedback.feedback)
        print("\n" + "=" * 80)

    except Exception as e:
        print(f"Error during evaluation: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
