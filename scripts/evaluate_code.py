#!/usr/bin/env python3
"""
Script to evaluate code for a given problem type and return feedback.

Usage:
    python scripts/evaluate_code.py --problem "Aircraft landing" --code "path/to/solution.py"
    python scripts/evaluate_code.py --problem "TSP" --code "solution.py"
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from src.controller import get_new_data, TASK_LIST
from src.evaluate import Evaluator, Feedback


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


def save_feedback(feedback: Feedback, output_dir: Path, iteration: int) -> Path:
    """Save evaluation feedback to a text file."""
    filename = output_dir / f"eval_{iteration}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"Iteration {iteration}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Overall Score: {feedback.score:.6f}\n")
        f.write(f"Dev Score: {feedback.dev_score:.6f}\n")
        f.write(f"Test Score: {feedback.test_score:.6f}\n")
        f.write("\n" + "=" * 80 + "\n")
        f.write("DEV FEEDBACK:\n")
        f.write("=" * 80 + "\n")
        f.write(feedback.dev_feedback)
        f.write("\n\n" + "=" * 80 + "\n")
        f.write("TEST FEEDBACK:\n")
        f.write("=" * 80 + "\n")
        f.write(feedback.test_feedback)

    return filename


def save_detailed_results(feedback: Feedback, output_dir: Path, iteration: int) -> Path:
    """Save detailed results as JSON."""
    filename = output_dir / f"eval_{iteration}.json"

    # Convert results to serializable format
    results_data = {}
    for case, (scores, error_msg) in feedback.results.items():
        results_data[case] = {
            "scores": [float(s) if not isinstance(s, str) else s for s in scores],
            "error": error_msg,
        }

    data = {
        "iteration": iteration,
        "timestamp": datetime.now().isoformat(),
        # Maintain backward compatibility with agent.py expectations
        "overall_score": float(feedback.score),
        "dev_score": float(feedback.dev_score),
        "test_score": float(feedback.test_score),
        "feedback": feedback.dev_feedback,
        # New structured format
        "scores": {
            "overall": float(feedback.score),
            "dev": float(feedback.dev_score),
            "test": float(feedback.test_score),
        },
        "detailed_results": results_data,
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return filename


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

    parser.add_argument(
        "--output-dir",
        type=str,
        help="Directory to save evaluation feedback files (optional)",
    )

    parser.add_argument(
        "--iteration",
        type=int,
        default=0,
        help="Iteration number for file naming (default: 0)",
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

        # Save feedback files if output directory is specified
        if args.output_dir:
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            feedback_file = save_feedback(feedback, output_dir, args.iteration)
            json_file = save_detailed_results(feedback, output_dir, args.iteration)

            print(f"\nFeedback saved to: {feedback_file}")
            print(f"Detailed results saved to: {json_file}")

    except Exception as e:
        print(f"Error during evaluation: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
