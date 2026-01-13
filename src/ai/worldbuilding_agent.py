"""Worldbuilding AI Agent for cost-effective assistance with world creation.

This agent provides recommendations and helps create worldbuilding elements
without writing the actual content. It uses a hybrid approach with local
SLMs for simple tasks and cloud LLMs for complex reasoning.
"""

from typing import Optional, Dict, List, Any, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient
    from src.models.project import WriterProject
    from src.models.worldbuilding_objects import (
        Character, Faction, EconomySystem, WorldMap, Place, Planet
    )


class TaskComplexity(Enum):
    """Task complexity levels for routing to appropriate model."""
    SIMPLE = "simple"  # Use local SLM
    MODERATE = "moderate"  # Use faster cloud model
    COMPLEX = "complex"  # Use best cloud model


@dataclass
class AgentResponse:
    """Response from the worldbuilding agent."""
    content: str
    suggestions: List[str]
    elements_to_create: List[Dict[str, Any]]
    cost_estimate: float  # In USD
    model_used: str


class WorldbuildingAgent:
    """AI agent for assisting with worldbuilding tasks."""

    # System prompts for different tasks
    RECOMMENDATION_PROMPT = """You are a worldbuilding expert assistant. Your role is to:
    1. Provide creative recommendations and suggestions
    2. Help identify gaps or inconsistencies in worldbuilding
    3. Offer ideas to enhance depth and richness
    4. Ask clarifying questions when needed

    CRITICAL: You should SUGGEST and RECOMMEND, not write content.
    Frame responses as "You could..." "Consider..." "What if..."

    Keep responses concise and cost-effective. Focus on the most impactful suggestions.
    """

    ELEMENT_CREATION_PROMPT = """You are helping a writer create worldbuilding elements.
    Based on their description, generate structured data for the element.

    Return data in a clear, structured format that can be used to populate fields.
    Be creative but respect any constraints or existing worldbuilding.

    Keep suggestions concise to minimize cost.
    """

    CONSISTENCY_CHECK_PROMPT = """You are a worldbuilding consistency checker.
    Review the provided worldbuilding elements and identify:
    1. Contradictions or inconsistencies
    2. Gaps in logic or worldbuilding
    3. Areas that need more detail

    Be brief and specific. Only highlight actual issues.
    """

    def __init__(
        self,
        primary_llm: 'LLMClient',
        local_llm: Optional['LLMClient'] = None,
        project: Optional['WriterProject'] = None
    ):
        """Initialize worldbuilding agent.

        Args:
            primary_llm: Primary cloud LLM for complex tasks
            local_llm: Optional local SLM for simple tasks (cost reduction)
            project: WriterProject for context
        """
        self.primary_llm = primary_llm
        self.local_llm = local_llm
        self.project = project

        # Cost tracking (approximate)
        self.total_cost = 0.0
        self.local_model_calls = 0
        self.cloud_model_calls = 0

    def _estimate_complexity(self, task: str, context_size: int) -> TaskComplexity:
        """Estimate task complexity to route to appropriate model.

        Args:
            task: Description of the task
            context_size: Amount of context needed (characters)

        Returns:
            TaskComplexity level
        """
        # Simple tasks: short queries, basic suggestions, single-item checks
        if context_size < 500 and any(keyword in task.lower() for keyword in [
            "suggest", "name", "quick", "simple", "basic", "idea"
        ]):
            return TaskComplexity.SIMPLE

        # Complex tasks: consistency checks, detailed analysis, multiple elements
        if context_size > 2000 or any(keyword in task.lower() for keyword in [
            "analyze", "review", "consistency", "detailed", "comprehensive"
        ]):
            return TaskComplexity.COMPLEX

        return TaskComplexity.MODERATE

    def _get_llm_for_task(self, complexity: TaskComplexity) -> 'LLMClient':
        """Get appropriate LLM based on task complexity.

        Args:
            complexity: Task complexity level

        Returns:
            LLMClient to use
        """
        if complexity == TaskComplexity.SIMPLE and self.local_llm:
            self.local_model_calls += 1
            return self.local_llm
        else:
            self.cloud_model_calls += 1
            return self.primary_llm

    def _estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model_name: str
    ) -> float:
        """Estimate cost of API call.

        Args:
            prompt_tokens: Number of input tokens
            completion_tokens: Number of output tokens
            model_name: Name of model used

        Returns:
            Estimated cost in USD
        """
        # Rough cost estimates (as of 2025)
        cost_per_1k = {
            "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gemini-2.0-flash": {"input": 0.0, "output": 0.0},  # Free tier
            "local": {"input": 0.0, "output": 0.0}  # Local = free
        }

        # Default costs
        default = {"input": 0.002, "output": 0.01}

        rates = cost_per_1k.get(model_name.split("-")[0], default)
        cost = (prompt_tokens / 1000) * rates["input"]
        cost += (completion_tokens / 1000) * rates["output"]

        self.total_cost += cost
        return cost

    def get_recommendations(
        self,
        category: str,
        context: str,
        question: str,
        existing_elements: Optional[List[str]] = None
    ) -> AgentResponse:
        """Get recommendations for worldbuilding category.

        Args:
            category: Category (characters, factions, places, etc.)
            context: Existing worldbuilding context
            question: User's specific question or request
            existing_elements: List of existing elements to avoid duplication

        Returns:
            AgentResponse with suggestions
        """
        # Build prompt
        existing_text = ""
        if existing_elements:
            existing_text = f"\n\nExisting {category}: {', '.join(existing_elements)}"

        prompt = f"""
Category: {category}

Existing Context:
{context[:1000]}  # Limit context for cost

{existing_text}

User Request:
{question}

Provide 3-5 concise, creative recommendations. Focus on the most impactful suggestions.
Format as a numbered list.
"""

        # Determine complexity and route
        complexity = self._estimate_complexity(question, len(context))
        llm = self._get_llm_for_task(complexity)

        # Generate response
        response = llm.generate_text(
            prompt,
            self.RECOMMENDATION_PROMPT,
            max_tokens=500,  # Keep short for cost
            temperature=0.8
        )

        # Estimate cost (rough)
        prompt_tokens = len(prompt.split()) * 1.3  # Rough estimate
        completion_tokens = len(response.split()) * 1.3
        cost = self._estimate_cost(
            int(prompt_tokens),
            int(completion_tokens),
            llm.model
        )

        # Parse suggestions
        suggestions = []
        for line in response.split('\n'):
            if line.strip() and (line.strip()[0].isdigit() or line.startswith('-')):
                suggestions.append(line.strip())

        return AgentResponse(
            content=response,
            suggestions=suggestions,
            elements_to_create=[],
            cost_estimate=cost,
            model_used=llm.model
        )

    def help_create_character(
        self,
        user_description: str,
        world_context: str
    ) -> Dict[str, Any]:
        """Help create character from description.

        Args:
            user_description: User's description of character
            world_context: Relevant world context

        Returns:
            Structured character data
        """
        prompt = f"""
World Context:
{world_context[:800]}

User Description:
{user_description}

Based on this description, suggest character details in this format:
- Name: [suggest name fitting the world]
- Type: [Protagonist/Antagonist/Supporting/etc.]
- Personality: [2-3 sentence personality summary]
- Key Traits: [3-5 bullet points]
- Backstory Ideas: [2-3 bullet points]
- Potential Arc: [1-2 sentences]

Keep suggestions brief and leave room for the writer to develop.
"""

        complexity = self._estimate_complexity(user_description, len(world_context))
        llm = self._get_llm_for_task(complexity)

        response = llm.generate_text(
            prompt,
            self.ELEMENT_CREATION_PROMPT,
            max_tokens=400,
            temperature=0.7
        )

        # Parse response into structured data
        character_data = {
            "name": "",
            "character_type": "Supporting",
            "personality": "",
            "key_traits": [],
            "backstory_ideas": [],
            "notes": response
        }

        # Simple parsing
        lines = response.split('\n')
        for line in lines:
            if line.startswith('- Name:'):
                character_data["name"] = line.replace('- Name:', '').strip()
            elif line.startswith('- Type:'):
                character_data["character_type"] = line.replace('- Type:', '').strip()
            elif line.startswith('- Personality:'):
                character_data["personality"] = line.replace('- Personality:', '').strip()

        return character_data

    def help_create_faction(
        self,
        user_description: str,
        world_context: str
    ) -> Dict[str, Any]:
        """Help create faction from description."""
        prompt = f"""
World Context:
{world_context[:800]}

User Description:
{user_description}

Suggest faction details:
- Name: [fitting name]
- Type: [Government/Military/Religious/Criminal/etc.]
- Goals: [primary objectives]
- Structure: [how organized]
- Values: [core beliefs]
- Conflicts: [potential conflicts with other factions]

Brief suggestions only.
"""

        complexity = self._estimate_complexity(user_description, len(world_context))
        llm = self._get_llm_for_task(complexity)

        response = llm.generate_text(
            prompt,
            self.ELEMENT_CREATION_PROMPT,
            max_tokens=350,
            temperature=0.7
        )

        return {
            "name": "",
            "faction_type": "Other",
            "description": response,
            "goals": "",
            "structure": "",
            "values": ""
        }

    def help_create_place(
        self,
        user_description: str,
        world_context: str,
        available_planets: List[str]
    ) -> Dict[str, Any]:
        """Help create place/location from description."""
        planets_text = f"Available planets: {', '.join(available_planets)}" if available_planets else ""

        prompt = f"""
World Context:
{world_context[:800]}

{planets_text}

User Description:
{user_description}

Suggest place details:
- Name: [evocative name]
- Type: [City/Village/Region/Landmark/etc.]
- Location: [planet/region]
- Description: [2-3 sentences]
- Key Features: [3-4 notable features]
- Atmosphere: [how it feels]
- Story Relevance: [why important]

Brief, evocative suggestions.
"""

        complexity = self._estimate_complexity(user_description, len(world_context))
        llm = self._get_llm_for_task(complexity)

        response = llm.generate_text(
            prompt,
            self.ELEMENT_CREATION_PROMPT,
            max_tokens=400,
            temperature=0.75
        )

        return {
            "name": "",
            "place_type": "City",
            "planet": available_planets[0] if available_planets else "",
            "description": "",
            "key_features": [],
            "atmosphere": "",
            "story_relevance": "",
            "notes": response
        }

    def check_consistency(
        self,
        element_type: str,
        element_data: str,
        world_context: str
    ) -> List[str]:
        """Check element for consistency issues.

        Args:
            element_type: Type of element (character, faction, place, etc.)
            element_data: Data for the element
            world_context: Relevant world context

        Returns:
            List of issues found
        """
        prompt = f"""
World Context:
{world_context[:1000]}

{element_type.title()} Data:
{element_data}

Check for:
1. Contradictions with world context
2. Logical inconsistencies
3. Missing crucial details

List only genuine issues. Be brief. If no issues, say "No issues found."
"""

        # Consistency checks are complex
        llm = self._get_llm_for_task(TaskComplexity.COMPLEX)

        response = llm.generate_text(
            prompt,
            self.CONSISTENCY_CHECK_PROMPT,
            max_tokens=300,
            temperature=0.3  # Lower temp for consistency
        )

        if "no issues found" in response.lower():
            return []

        # Parse issues
        issues = []
        for line in response.split('\n'):
            if line.strip() and (line.strip()[0].isdigit() or line.startswith('-')):
                issues.append(line.strip())

        return issues

    def suggest_map_elements(
        self,
        map_type: str,
        existing_places: List[str],
        theme: str
    ) -> List[Dict[str, str]]:
        """Suggest elements to add to a map.

        Args:
            map_type: Type of map (world, location)
            existing_places: Places already on map
            theme: Map theme/setting

        Returns:
            List of suggested map elements
        """
        existing_text = f"Existing places: {', '.join(existing_places)}" if existing_places else ""

        prompt = f"""
Map Type: {map_type}
Theme: {theme}
{existing_text}

Suggest 4-6 interesting places or features to add to this map.
For each, provide:
- Name: [place name]
- Type: [City/Village/Landmark/etc.]
- Brief Description: [1 sentence]

Keep it brief.
"""

        # Map suggestions can use local model
        llm = self._get_llm_for_task(TaskComplexity.SIMPLE)

        response = llm.generate_text(
            prompt,
            self.RECOMMENDATION_PROMPT,
            max_tokens=350,
            temperature=0.8
        )

        # Parse suggestions (simplified)
        suggestions = []
        lines = response.split('\n')
        current_suggestion = {}

        for line in lines:
            if '- Name:' in line:
                if current_suggestion:
                    suggestions.append(current_suggestion)
                current_suggestion = {"name": line.split(':')[1].strip()}
            elif '- Type:' in line and current_suggestion:
                current_suggestion["type"] = line.split(':')[1].strip()
            elif '- Brief Description:' in line and current_suggestion:
                current_suggestion["description"] = line.split(':')[1].strip()

        if current_suggestion:
            suggestions.append(current_suggestion)

        return suggestions

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics for cost tracking.

        Returns:
            Dict with usage stats
        """
        return {
            "total_cost_usd": round(self.total_cost, 4),
            "local_model_calls": self.local_model_calls,
            "cloud_model_calls": self.cloud_model_calls,
            "cost_savings_pct": round(
                (self.local_model_calls / max(1, self.local_model_calls + self.cloud_model_calls)) * 100,
                1
            )
        }

    def reset_usage_stats(self):
        """Reset usage statistics."""
        self.total_cost = 0.0
        self.local_model_calls = 0
        self.cloud_model_calls = 0
