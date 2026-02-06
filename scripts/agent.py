#!/usr/bin/env python3
"""
Agent for iteratively generating and improving optimization heuristics.

Usage:
    python agent.py --problem "Aircraft landing"
    python agent.py --problem "Bin packing - one-dimensional" --max-iterations 15
"""

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, HookMatcher
from dotenv import load_dotenv

from agent_prompts import (
    SYSTEM_PROMPT,
    format_improvement_prompt,
    format_initial_prompt,
)
from src.controller import TASK_LIST

# Load environment variables
load_dotenv()


def setup_logging(run_dir: Path) -> logging.Logger:
    """Setup logging to both file and console."""
    logger = logging.getLogger("heuristic_agent")
    logger.setLevel(logging.INFO)

    # File handler
    file_handler = logging.FileHandler(run_dir / "agent.log")
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def create_run_directory() -> Path:
    """Create a timestamped run directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("runs") / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (run_dir / "heuristics").mkdir(exist_ok=True)
    (run_dir / "evaluation").mkdir(exist_ok=True)

    return run_dir


def get_problem_description(problem: str) -> str:
    """Get problem description using get_problem.py script."""
    cmd = ["python", "scripts/get_problem.py", "--problem", problem]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def extract_python_code(text: str) -> Optional[str]:
    """Extract Python code from Claude's response."""
    # Try to find code blocks with python language marker
    pattern = r"```python\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)

    if matches:
        return matches[-1].strip()  # Return the last code block

    # Try to find any code blocks
    pattern = r"```\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)

    if matches:
        code = matches[-1].strip()
        # Verify it looks like Python code with a solve function
        if "def solve(" in code:
            return code

    return None


def validate_code(code: str) -> bool:
    """Validate that code contains a solve function."""
    return "def solve(" in code


def save_heuristic(code: str, run_dir: Path, iteration: int, metadata: dict) -> Path:
    """Save heuristic code to file with metadata as comments."""
    filepath = run_dir / "heuristics" / f"heuristic_{iteration}.py"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Heuristic from iteration {iteration}\n")
        if "dev_score" in metadata and "test_score" in metadata:
            f.write(f"# Dev Score: {metadata['dev_score']:.6f}\n")
            f.write(f"# Test Score: {metadata['test_score']:.6f}\n")
        f.write("\n\n")
        f.write(code)

    return filepath


def evaluate_heuristic(problem: str, heuristic_path: Path) -> dict:
    """Evaluate heuristic using evaluate_code.py script."""
    cmd = [
        "python",
        "scripts/evaluate_code.py",
        "--problem",
        problem,
        "--code",
        str(heuristic_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    # Parse the output
    output = result.stdout

    # Extract scores
    overall_score = None
    dev_score = None
    test_score = None
    feedback = ""

    # Look for score patterns
    overall_match = re.search(r"Overall Score:\s*([0-9.]+)", output)
    dev_match = re.search(r"Dev Score:\s*([0-9.]+)", output)
    test_match = re.search(r"Test Score:\s*([0-9.]+)", output)

    if overall_match:
        overall_score = float(overall_match.group(1))
    if dev_match:
        dev_score = float(dev_match.group(1))
    if test_match:
        test_score = float(test_match.group(1))

    # Extract feedback (text after "Feedback:" line)
    feedback_match = re.search(r"Feedback:\s*\n(.*?)(?:\n={80}|$)", output, re.DOTALL)
    if feedback_match:
        feedback = feedback_match.group(1).strip()

    return {
        "overall_score": overall_score,
        "dev_score": dev_score,
        "test_score": test_score,
        "feedback": feedback,
        "raw_output": output,
    }


def save_evaluation(evaluation: dict, run_dir: Path, iteration: int) -> Path:
    """Save evaluation results to JSON file."""
    filepath = run_dir / "evaluation" / f"eval_{iteration}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(evaluation, f, indent=2)

    return filepath


def check_stopping_criteria(
    iteration: int,
    max_iterations: int,
    current_score: Optional[float],
    score_threshold: float,
    score_history: list[float],
    improvement_threshold: float,
    patience: int,
) -> tuple[bool, str]:
    """
    Check if any stopping criteria are met.

    Returns:
        (should_stop, reason)
    """
    # Check max iterations
    if iteration >= max_iterations:
        return True, f"Reached maximum iterations ({max_iterations})"

    # Check score threshold
    if current_score is not None and current_score >= score_threshold:
        return (
            True,
            f"Reached score threshold ({current_score:.4f} >= {score_threshold})",
        )

    # Check diminishing returns
    if len(score_history) >= patience:
        recent_scores = score_history[-patience:]
        improvements = [
            recent_scores[i] - recent_scores[i - 1]
            for i in range(1, len(recent_scores))
        ]
        avg_improvement = sum(improvements) / len(improvements)

        if avg_improvement < improvement_threshold:
            return (
                True,
                f"Diminishing returns (avg improvement {avg_improvement:.6f} < {improvement_threshold})",
            )

    return False, ""


async def run_agent(
    problem: str,
    max_iterations: int,
    score_threshold: float,
    improvement_threshold: float,
    patience: int,
    api_key: Optional[str] = None,
) -> None:
    """Main agent loop."""
    # Validate problem
    if problem not in TASK_LIST:
        print(f"Error: Unknown problem type '{problem}'", file=sys.stderr)
        print("\nAvailable problem types:", file=sys.stderr)
        for task in TASK_LIST:
            print(f"  - {task}", file=sys.stderr)
        sys.exit(1)

    # Check API key
    if not api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nError: ANTHROPIC_API_KEY not found.", file=sys.stderr)
        print("Set it in a .env file or export it in your shell.", file=sys.stderr)
        print(
            "Get your key at: https://console.anthropic.com/settings/keys\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # Setup
    run_dir = create_run_directory()
    logger = setup_logging(run_dir)

    logger.info(f"Starting agent for problem: {problem}")
    logger.info(f"Run directory: {run_dir}")

    # Save run configuration
    config = {
        "problem": problem,
        "max_iterations": max_iterations,
        "score_threshold": score_threshold,
        "improvement_threshold": improvement_threshold,
        "patience": patience,
        "start_time": datetime.now().isoformat(),
    }

    with open(run_dir / "run_config.json", "w") as f:
        json.dump(config, f, indent=2)

    # Get problem description
    logger.info("Getting problem description...")
    try:
        problem_description = get_problem_description(problem)
        logger.info("Problem description loaded successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get problem description: {e}")
        logger.error(f"stdout: {e.stdout}")
        logger.error(f"stderr: {e.stderr}")
        sys.exit(1)

    # Initialize tracking variables
    score_history = []
    best_score = 0.0
    best_iteration = 0
    current_code = None

    # Configure Claude SDK options
    options = ClaudeAgentOptions(
        permission_mode="bypassPermissions",
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=["Bash", "Read", "Write"],
        model="claude-haiku-4-5",
    )

    # Main iteration loop
    async with ClaudeSDKClient(options=options) as client:
        for iteration in range(max_iterations):
            logger.info(f"\n{'='*80}")
            logger.info(f"ITERATION {iteration}")
            logger.info(f"{'='*80}")

            try:
                # Prepare prompt
                if iteration == 0:
                    user_prompt = format_initial_prompt(problem_description)
                else:
                    # Get feedback from previous iteration
                    prev_eval_path = run_dir / "evaluation" / f"eval_{iteration-1}.json"
                    with open(prev_eval_path, "r") as f:
                        prev_eval = json.load(f)

                    user_prompt = format_improvement_prompt(
                        problem_description=problem_description,
                        current_code=current_code,
                        iteration=iteration - 1,
                        overall_score=prev_eval.get("overall_score", 0.0),
                        dev_score=prev_eval.get("dev_score", 0.0),
                        test_score=prev_eval.get("test_score", 0.0),
                        feedback=prev_eval.get("feedback", ""),
                    )

                # Send query to Claude
                logger.info("Generating heuristic...")
                await client.query(prompt=user_prompt)

                # Collect response
                assistant_message = ""
                async for msg in client.receive_response():
                    if type(msg).__name__ == "AssistantMessage":
                        for block in msg.content:
                            if type(block).__name__ == "TextBlock":
                                assistant_message += block.text

                # Extract code
                logger.info("Extracting code from response...")
                code = extract_python_code(assistant_message)

                if not code:
                    logger.error("Failed to extract Python code from response")
                    logger.error(f"Response: {assistant_message[:500]}...")
                    continue

                if not validate_code(code):
                    logger.error("Extracted code does not contain a solve function")
                    logger.error(f"Code: {code[:500]}...")
                    continue

                current_code = code
                logger.info("Code extracted and validated successfully")

                # Save heuristic (without evaluation metadata for now)
                heuristic_path = save_heuristic(code, run_dir, iteration, {})
                logger.info(f"Heuristic saved to {heuristic_path}")

                # Evaluate heuristic
                logger.info("Evaluating heuristic...")
                evaluation = evaluate_heuristic(problem, heuristic_path)

                # Update heuristic file with evaluation metadata
                heuristic_path = save_heuristic(code, run_dir, iteration, evaluation)

                # Save evaluation
                eval_path = save_evaluation(evaluation, run_dir, iteration)
                logger.info(f"Evaluation saved to {eval_path}")

                # Log results
                overall_score = evaluation.get("overall_score", 0.0)
                dev_score = evaluation.get("dev_score", 0.0)
                test_score = evaluation.get("test_score", 0.0)

                logger.info(f"Overall Score: {overall_score:.4f}")
                logger.info(f"Dev Score: {dev_score:.4f}")
                logger.info(f"Test Score: {test_score:.4f}")

                # Track best score
                if overall_score > best_score:
                    best_score = overall_score
                    best_iteration = iteration
                    logger.info(f"New best score: {best_score:.4f}")

                score_history.append(overall_score)

                # Check stopping criteria
                should_stop, reason = check_stopping_criteria(
                    iteration=iteration + 1,
                    max_iterations=max_iterations,
                    current_score=overall_score,
                    score_threshold=score_threshold,
                    score_history=score_history,
                    improvement_threshold=improvement_threshold,
                    patience=patience,
                )

                if should_stop:
                    logger.info(f"\nStopping: {reason}")
                    break

            except subprocess.CalledProcessError as e:
                logger.error(f"Script execution failed: {e}")
                logger.error(f"stdout: {e.stdout}")
                logger.error(f"stderr: {e.stderr}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error in iteration {iteration}: {e}")
                import traceback

                logger.error(traceback.format_exc())
                continue

    # Final summary
    logger.info(f"\n{'='*80}")
    logger.info("FINAL SUMMARY")
    logger.info(f"{'='*80}")
    logger.info(f"Total iterations: {len(score_history)}")
    logger.info(f"Best score: {best_score:.4f} (iteration {best_iteration})")
    logger.info(
        f"Final score: {score_history[-1]:.4f}"
        if score_history
        else "No scores recorded"
    )
    logger.info(f"Run directory: {run_dir}")

    # Save final summary
    summary = {
        "problem": problem,
        "total_iterations": len(score_history),
        "best_score": best_score,
        "best_iteration": best_iteration,
        "final_score": score_history[-1] if score_history else None,
        "score_history": score_history,
        "end_time": datetime.now().isoformat(),
    }

    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Summary saved to {run_dir / 'summary.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent for iteratively generating and improving optimization heuristics"
    )

    parser.add_argument(
        "--problem",
        type=str,
        required=True,
        help="Name of the problem to solve (e.g., 'Aircraft landing', 'Bin packing - one-dimensional')",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum number of iterations (default: 10)",
    )

    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.99,
        help="Stop if score reaches this threshold (default: 0.99)",
    )

    parser.add_argument(
        "--improvement-threshold",
        type=float,
        default=0.001,
        help="Minimum average improvement to continue (default: 0.001)",
    )

    parser.add_argument(
        "--patience",
        type=int,
        default=3,
        help="Number of iterations to check for diminishing returns (default: 3)",
    )

    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Anthropic API key (defaults to ANTHROPIC_API_KEY env var)",
    )

    args = parser.parse_args()

    asyncio.run(
        run_agent(
            problem=args.problem,
            max_iterations=args.max_iterations,
            score_threshold=args.score_threshold,
            improvement_threshold=args.improvement_threshold,
            patience=args.patience,
            api_key=args.api_key,
        )
    )


if __name__ == "__main__":
    main()
