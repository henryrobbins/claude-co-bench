#!/usr/bin/env python3
"""
Agent for iteratively generating and improving optimization heuristics.

Usage:
    python agent.py --problem "Aircraft landing"
    python agent.py --problem "Bin packing - one-dimensional" --max-turns 20
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from dotenv import load_dotenv

from agent_prompts import SYSTEM_PROMPT
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


async def run_agent(
    problem: str,
    max_turns: int,
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
    logger.info(f"Max turns: {max_turns}")

    # Save run configuration
    config = {
        "problem": problem,
        "max_turns": max_turns,
        "start_time": datetime.now().isoformat(),
    }

    with open(run_dir / "run_config.json", "w") as f:
        json.dump(config, f, indent=2)

    # Configure Claude SDK options
    options = ClaudeAgentOptions(
        permission_mode="bypassPermissions",
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=["Bash", "Read", "Write"],
        model="claude-haiku-4-5",
        max_turns=max_turns,
    )

    # Initial prompt
    initial_prompt = f"""You are working on the optimization problem: "{problem}"

Your working directory is: {run_dir.absolute()}

This directory already contains:
- heuristics/ (empty, for you to save heuristics)
- evaluation/ (empty, where evaluation results will be saved)

Get started by:
1. Using get_problem.py to understand the problem
2. Creating a simple baseline heuristic
3. Iterating to improve it

Remember to use descriptive names for your heuristics (e.g., 01_greedy_baseline.py, 02_priority_scoring.py, etc.)."""

    try:
        # Run the agent
        logger.info("Starting agent conversation...")
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt=initial_prompt)

            # Collect all responses
            turn_count = 0
            async for msg in client.receive_response():
                if type(msg).__name__ == "AssistantMessage":
                    turn_count += 1
                    logger.info(f"Turn {turn_count} completed")
                    for block in msg.content:
                        if type(block).__name__ == "TextBlock":
                            # Log a snippet of the response
                            text = block.text[:200]
                            logger.info(f"Response preview: {text}...")

            logger.info(f"Agent completed after {turn_count} turns")

    except Exception as e:
        logger.error(f"Error during agent execution: {e}")
        import traceback

        logger.error(traceback.format_exc())
        sys.exit(1)

    # Save final summary
    summary = {
        "problem": problem,
        "max_turns": max_turns,
        "end_time": datetime.now().isoformat(),
    }

    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"\n{'='*80}")
    logger.info("AGENT COMPLETED")
    logger.info(f"{'='*80}")
    logger.info(f"Run directory: {run_dir}")
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
        "--max-turns",
        type=int,
        default=30,
        help="Maximum number of agent turns (default: 30)",
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
            max_turns=args.max_turns,
            api_key=args.api_key,
        )
    )


if __name__ == "__main__":
    main()
