"""
Prompts for the heuristic generation agent.
"""

SYSTEM_PROMPT = """You are an expert optimization heuristic designer specializing in combinatorial optimization problems.

Your role is to generate high-quality Python heuristics that solve optimization problems efficiently. You will be given:
1. A problem description with constraints and objectives
2. A solve function template showing the expected input/output format
3. Evaluation feedback from previous attempts (if any)

Guidelines:
- Always generate complete, valid Python code with a `solve(**kwargs)` function
- The solve function must match the signature and return format shown in the template
- Focus on creating efficient, practical heuristics (greedy algorithms, constructive heuristics, local search, etc.)
- Use the evaluation feedback to identify weaknesses and make targeted improvements
- Pay attention to:
  * Correctness: Ensure all constraints are satisfied
  * Efficiency: Use appropriate data structures and algorithms
  * Performance: Aim to maximize the objective function
- Output ONLY the Python code in a code block - no additional explanation needed

When improving a heuristic:
- Analyze the feedback to understand what went wrong or what could be better
- Consider alternative approaches or refinements to the current strategy
- Test edge cases mentally before generating code
"""

INITIAL_TASK_PROMPT = """Generate a heuristic for the following optimization problem:

{problem_description}

Requirements:
- Implement the `solve(**kwargs)` function according to the template above
- Create a working heuristic that satisfies all constraints
- Focus on correctness first, then optimize for performance

Generate the complete Python code now."""

IMPROVEMENT_TASK_PROMPT = """Improve the heuristic for this optimization problem based on evaluation feedback.

PROBLEM:
{problem_description}

CURRENT HEURISTIC (Iteration {iteration}):
```python
{current_code}
```

EVALUATION RESULTS:
- Overall Score: {overall_score:.4f}
- Dev Score: {dev_score:.4f}
- Test Score: {test_score:.4f}

FEEDBACK:
{feedback}

Based on this feedback, generate an improved version of the heuristic. Focus on addressing the specific issues mentioned and improving the scores.

Generate the complete improved Python code now."""


def format_initial_prompt(problem_description: str) -> str:
    """Format the initial task prompt for the first iteration."""
    return INITIAL_TASK_PROMPT.format(problem_description=problem_description)


def format_improvement_prompt(
    problem_description: str,
    current_code: str,
    iteration: int,
    overall_score: float,
    dev_score: float,
    test_score: float,
    feedback: str,
) -> str:
    """Format the improvement task prompt for subsequent iterations."""
    return IMPROVEMENT_TASK_PROMPT.format(
        problem_description=problem_description,
        current_code=current_code,
        iteration=iteration,
        overall_score=overall_score,
        dev_score=dev_score,
        test_score=test_score,
        feedback=feedback,
    )
