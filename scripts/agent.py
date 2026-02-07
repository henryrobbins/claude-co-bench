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
from langfuse import get_client

from src.controller import TASK_LIST

# Load environment variables
load_dotenv()


def load_system_prompt() -> str:
    """Load the system prompt from the prompts directory."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
    return prompt_path.read_text()


def load_initial_prompt(problem: str, run_dir: Path) -> str:
    """Load and format the initial prompt from the prompts directory."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "initial_prompt.txt"
    template = prompt_path.read_text()
    return template.format(problem=problem, run_dir=run_dir.absolute())


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

    # Initialize langfuse
    langfuse = get_client()

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
        system_prompt=load_system_prompt(),
        allowed_tools=["Bash", "Read", "Write"],
        model="claude-haiku-4-5",
        max_turns=max_turns,
    )

    # Load initial prompt
    initial_prompt = load_initial_prompt(problem, run_dir)

    # Open transcript log file
    transcript_path = run_dir / "transcript.log"

    def write_to_transcript(content: str) -> None:
        """Write content to transcript file and display to console."""
        print(content)
        with open(transcript_path, "a", encoding="utf-8") as f:
            f.write(content + "\n")

    try:
        # Run the agent with langfuse tracing
        logger.info("Starting agent conversation...")

        # Create main span for the entire agent run
        with langfuse.start_as_current_observation(
            as_type="span",
            name="agent-run",
            input={"problem": problem, "max_turns": max_turns, "run_dir": str(run_dir)},
            metadata={"model": "claude-haiku-4-5"},
        ) as agent_span:
            # Log initial prompt
            write_to_transcript("\n" + "=" * 80)
            write_to_transcript("USER PROMPT")
            write_to_transcript("=" * 80)
            write_to_transcript(initial_prompt)
            write_to_transcript("")

            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt=initial_prompt)

                # Collect all responses
                turn_count = 0
                async for msg in client.receive_response():
                    if type(msg).__name__ == "AssistantMessage":
                        turn_count += 1
                        logger.info(f"Turn {turn_count} started")

                        # Create a nested generation span for each assistant turn
                        with langfuse.start_as_current_observation(
                            as_type="generation",
                            name=f"assistant-turn-{turn_count}",
                            model="claude-haiku-4-5",
                            metadata={"turn": turn_count},
                        ) as turn_generation:
                            write_to_transcript("\n" + "=" * 80)
                            write_to_transcript(f"ASSISTANT TURN {turn_count}")
                            write_to_transcript("=" * 80)

                            turn_output = []
                            for block in msg.content:
                                if type(block).__name__ == "TextBlock":
                                    # Display full text content
                                    write_to_transcript(block.text)
                                    turn_output.append(
                                        {"type": "text", "content": block.text}
                                    )
                                elif type(block).__name__ == "ToolUseBlock":
                                    # Log tool use
                                    tool_info = f"\n[Tool Use: {block.name}]"
                                    write_to_transcript(tool_info)
                                    write_to_transcript(
                                        f"Input: {json.dumps(block.input, indent=2)}"
                                    )
                                    turn_output.append(
                                        {
                                            "type": "tool_use",
                                            "tool": block.name,
                                            "input": block.input,
                                        }
                                    )

                            write_to_transcript("")
                            logger.info(f"Turn {turn_count} completed")

                            # Update generation with output
                            turn_generation.update(output=turn_output)

                    elif type(msg).__name__ == "ToolResultMessage":
                        # Log tool results with a span
                        with langfuse.start_as_current_observation(
                            as_type="span",
                            name="tool-results",
                            metadata={"turn": turn_count},
                        ) as tool_span:
                            write_to_transcript("\n" + "-" * 80)
                            write_to_transcript("TOOL RESULTS")
                            write_to_transcript("-" * 80)

                            tool_results = []
                            for block in msg.content:
                                if type(block).__name__ == "ToolResultBlock":
                                    write_to_transcript(
                                        f"\n[Tool: {block.tool_use_id}]"
                                    )
                                    if hasattr(block, "content"):
                                        if isinstance(block.content, str):
                                            write_to_transcript(block.content)
                                            tool_results.append(
                                                {
                                                    "tool_id": block.tool_use_id,
                                                    "content": block.content,
                                                }
                                            )
                                        else:
                                            write_to_transcript(
                                                json.dumps(block.content, indent=2)
                                            )
                                            tool_results.append(
                                                {
                                                    "tool_id": block.tool_use_id,
                                                    "content": block.content,
                                                }
                                            )
                            write_to_transcript("")

                            # Update tool span with results
                            tool_span.update(output=tool_results)

                logger.info(f"Agent completed after {turn_count} turns")

                # Update main span with final output
                agent_span.update(
                    output={"total_turns": turn_count, "status": "completed"}
                )

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
        "total_turns": turn_count,
    }

    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"\n{'='*80}")
    logger.info("AGENT COMPLETED")
    logger.info(f"{'='*80}")
    logger.info(f"Run directory: {run_dir}")
    logger.info(f"Transcript saved to {transcript_path}")
    logger.info(f"Summary saved to {run_dir / 'summary.json'}")

    # Flush langfuse events
    langfuse.flush()


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
