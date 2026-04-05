"""AI Test Harness — run scenarios with inputs and expected outputs.

Usage:
    python -m tests.ai_test_harness                    # Run all scenarios
    python -m tests.ai_test_harness --scenario 3       # Run scenario 3
    python -m tests.ai_test_harness --list              # List scenarios
    python -m tests.ai_test_harness --add               # Interactive add

Scenarios are stored in tests/ai_scenarios.json and can be edited directly.
Each scenario has:
    - name: descriptive name
    - mode: "general", "chapter_focus", or "writer"
    - user_message: what the user types
    - context: dict of context keys (project_name, characters, worldbuilding, etc.)
    - expected_contains: list of strings the response MUST contain (case-insensitive)
    - expected_not_contains: list of strings the response must NOT contain
    - expected_min_length: minimum response length
"""

import json
import sys
import time
from pathlib import Path
from typing import List, Optional


SCENARIOS_FILE = Path(__file__).parent / "ai_scenarios.json"

DEFAULT_SCENARIOS = [
    {
        "name": "Basic worldbuilding question",
        "mode": "general",
        "user_message": "What type of government would work for a desert nomadic culture?",
        "context": {
            "project_name": "Test Project",
            "worldbuilding": "Desert setting with nomadic tribes, limited water resources."
        },
        "expected_contains": ["tribe", "council"],
        "expected_not_contains": [],
        "expected_min_length": 100
    },
    {
        "name": "Character personality consistency",
        "mode": "chapter_focus",
        "user_message": "Is Marcus acting consistently with his personality in this chapter?",
        "context": {
            "project_name": "Test Project",
            "characters": "- Marcus (protagonist): Personality: stoic, disciplined, afraid of failure. Speaking style: short, clipped sentences.",
            "current_chapter_title": "The Trial",
            "current_chapter_content": "Marcus laughed loudly at the joke, slapping his knee. 'Oh that's wonderful!' he exclaimed, dancing around the room."
        },
        "expected_contains": ["inconsist"],
        "expected_not_contains": [],
        "expected_min_length": 50
    },
    {
        "name": "RAG context retrieval",
        "mode": "general",
        "user_message": "Tell me about the magic system in my world",
        "context": {
            "project_name": "Test Project",
            "rag_context": "[MAGIC_SYSTEM: Aetheric Bonds]\nMagic drawn from emotional connections between living things. Stronger bonds = stronger magic. Cost: emotional exhaustion.",
            "plot_summary": "A young bonded pair must save their village."
        },
        "expected_contains": ["aetheric", "bond", "emotion"],
        "expected_not_contains": [],
        "expected_min_length": 80
    },
    {
        "name": "Writer mode prose continuation",
        "mode": "writer",
        "user_message": "Continue the scene",
        "context": {
            "project_name": "Test Project",
            "current_chapter_title": "Chapter 1",
            "current_chapter_content": "The rain hammered against the windows of the old library. Elena pulled her coat tighter and stepped inside.",
            "preceding_text": "The rain hammered against the windows of the old library. Elena pulled her coat tighter and stepped inside.",
            "pov": "Third person limited",
            "character_pov": "Elena"
        },
        "expected_contains": ["elena"],
        "expected_not_contains": [],
        "expected_min_length": 100
    },
    {
        "name": "Worldbuilding encyclopedia reference",
        "mode": "general",
        "user_message": "I want to create a feudal system for my fantasy kingdom. What should I consider?",
        "context": {
            "project_name": "Test Project",
            "rag_context": "[ENCYCLOPEDIA: Feudalism]\nDecentralized system where lords grant land in exchange for loyalty and military service. Land (fiefs) flows downward from a monarch through vassals to serfs.",
            "worldbuilding": "Medieval fantasy setting with multiple kingdoms."
        },
        "expected_contains": ["vassal", "lord"],
        "expected_not_contains": [],
        "expected_min_length": 100
    }
]


def load_scenarios() -> list:
    """Load scenarios from JSON file, creating defaults if needed."""
    if SCENARIOS_FILE.exists():
        with open(SCENARIOS_FILE, 'r') as f:
            return json.load(f)
    # Create default scenarios file
    save_scenarios(DEFAULT_SCENARIOS)
    return DEFAULT_SCENARIOS


def save_scenarios(scenarios: list):
    """Save scenarios to JSON file."""
    with open(SCENARIOS_FILE, 'w') as f:
        json.dump(scenarios, f, indent=2)


def run_scenario(scenario: dict, llm_client=None, verbose: bool = True) -> dict:
    """Run a single test scenario and check expectations.

    Args:
        scenario: The scenario dict
        llm_client: LLMClient instance (if None, will try to create one)
        verbose: Print detailed output

    Returns:
        Dict with 'passed', 'response', 'errors', 'elapsed_ms'
    """
    if llm_client is None:
        llm_client = _create_llm_client()
        if not llm_client:
            return {
                "passed": False,
                "response": "",
                "errors": ["No LLM client available. Configure an API key or local model."],
                "elapsed_ms": 0
            }

    # Import here to avoid circular imports at module level
    sys.path.insert(0, str(Path(__file__).parent.parent))

    mode = scenario.get("mode", "general")
    context = scenario.get("context", {})
    message = scenario["user_message"]

    # Build system prompt (simplified version of ChatWorker logic)
    from src.ui.main_window import ChatWorker
    worker = ChatWorker.__new__(ChatWorker)
    worker.context = context
    worker.mode = mode
    worker.message = message
    worker.SYSTEM_PROMPTS = ChatWorker.SYSTEM_PROMPTS

    system_prompt = worker.SYSTEM_PROMPTS.get(mode, worker.SYSTEM_PROMPTS["general"])
    context_prompt = worker._build_context_prompt()
    if context_prompt:
        system_prompt += f"\n\nPROJECT CONTEXT:\n{context_prompt}"

    if verbose:
        print(f"\n  System prompt: {len(system_prompt)} chars")
        print(f"  Context keys: {list(context.keys())}")

    # Generate response
    start = time.time()
    try:
        response = llm_client.generate_text(
            prompt=message,
            system_prompt=system_prompt,
            max_tokens=1000,
            temperature=0.5
        )
    except Exception as e:
        return {
            "passed": False,
            "response": "",
            "errors": [f"LLM error: {e}"],
            "elapsed_ms": 0
        }
    elapsed = int((time.time() - start) * 1000)

    # Check expectations
    errors = []
    response_lower = response.lower()

    for term in scenario.get("expected_contains", []):
        if term.lower() not in response_lower:
            errors.append(f"Expected '{term}' in response but not found")

    for term in scenario.get("expected_not_contains", []):
        if term.lower() in response_lower:
            errors.append(f"Did NOT expect '{term}' in response but it was found")

    min_len = scenario.get("expected_min_length", 0)
    if len(response) < min_len:
        errors.append(f"Response too short: {len(response)} < {min_len}")

    passed = len(errors) == 0

    if verbose:
        print(f"  Response: {len(response)} chars, {elapsed}ms")
        if not passed:
            for err in errors:
                print(f"  FAIL: {err}")
        print(f"  Response preview: {response[:200]}...")

    return {
        "passed": passed,
        "response": response,
        "errors": errors,
        "elapsed_ms": elapsed
    }


def _create_llm_client():
    """Create an LLM client from config."""
    try:
        from src.config.ai_config import get_ai_config
        from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig

        config = get_ai_config()
        settings = config.get_settings()

        prefer_local = settings.get("prefer_local_model", False)
        enable_local = settings.get("enable_local_models", False)
        local_model_id = settings.get("local_model_id", "")

        if prefer_local and enable_local and local_model_id:
            is_mlx = "mlx" in local_model_id.lower()
            hf_config = HuggingFaceConfig(
                model_id=local_model_id, use_local=True,
                device=settings.get("local_model_device", "auto"),
                quantization=settings.get("local_model_quantization", "none")
                    if settings.get("local_model_quantization") != "none" else None,
                trust_remote_code=settings.get("local_model_trust_remote_code", False)
            )
            provider = LLMProvider.MLX_LOCAL if is_mlx else LLMProvider.HUGGINGFACE_LOCAL
            return LLMClient(provider=provider, hf_config=hf_config)

        provider_name = settings.get("default_llm", "claude").lower()
        api_key = config.get_api_key(provider_name)
        if api_key:
            provider_enum = {
                "claude": LLMProvider.CLAUDE, "chatgpt": LLMProvider.CHATGPT,
                "openai": LLMProvider.CHATGPT, "gemini": LLMProvider.GEMINI,
            }.get(provider_name, LLMProvider.CLAUDE)
            return LLMClient(
                provider=provider_enum, api_key=api_key,
                model=config.get_model(provider_name)
            )

        return None
    except Exception as e:
        print(f"Failed to create LLM client: {e}")
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI Test Harness")
    parser.add_argument("--scenario", type=int, help="Run a specific scenario by index")
    parser.add_argument("--list", action="store_true", help="List all scenarios")
    parser.add_argument("--add", action="store_true", help="Interactively add a scenario")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    args = parser.parse_args()

    scenarios = load_scenarios()

    if args.list:
        for i, s in enumerate(scenarios):
            print(f"  [{i}] {s['name']} (mode={s['mode']})")
        return

    if args.add:
        print("Add a new test scenario:")
        name = input("  Name: ").strip()
        mode = input("  Mode (general/chapter_focus/writer): ").strip() or "general"
        msg = input("  User message: ").strip()
        contains = input("  Expected contains (comma-sep): ").strip()
        not_contains = input("  Expected NOT contains (comma-sep): ").strip()
        min_len = int(input("  Min response length (0): ").strip() or "0")

        scenario = {
            "name": name,
            "mode": mode,
            "user_message": msg,
            "context": {"project_name": "Test Project"},
            "expected_contains": [t.strip() for t in contains.split(",") if t.strip()],
            "expected_not_contains": [t.strip() for t in not_contains.split(",") if t.strip()],
            "expected_min_length": min_len
        }
        scenarios.append(scenario)
        save_scenarios(scenarios)
        print(f"  Added scenario [{len(scenarios)-1}]: {name}")
        return

    # Run scenarios
    verbose = not args.quiet
    llm_client = _create_llm_client()
    if not llm_client:
        print("ERROR: No LLM client available. Configure an API key or local model in settings.")
        sys.exit(1)

    to_run = [args.scenario] if args.scenario is not None else range(len(scenarios))
    passed = 0
    failed = 0

    for i in to_run:
        if i >= len(scenarios):
            print(f"Scenario [{i}] does not exist")
            continue

        s = scenarios[i]
        print(f"\n{'='*60}")
        print(f"[{i}] {s['name']}  (mode={s['mode']})")
        print(f"{'='*60}")
        print(f"  Message: {s['user_message']}")

        result = run_scenario(s, llm_client=llm_client, verbose=verbose)

        if result["passed"]:
            print(f"  PASSED ({result['elapsed_ms']}ms)")
            passed += 1
        else:
            print(f"  FAILED ({result['elapsed_ms']}ms)")
            for err in result["errors"]:
                print(f"    - {err}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'='*60}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
