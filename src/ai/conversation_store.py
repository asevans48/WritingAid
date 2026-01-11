"""Conversation storage for saving rated LLM interactions for fine-tuning.

This module provides storage for conversations that users rate as high-quality,
enabling collection of training data for fine-tuning small language models
tailored to individual authors' creative processes.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class ConversationRating(str, Enum):
    """Rating levels for conversations."""
    EXCELLENT = "excellent"  # 5 stars - perfect for training
    GOOD = "good"           # 4 stars - useful but minor issues
    NEUTRAL = "neutral"     # 3 stars - mediocre, probably skip
    POOR = "poor"           # 2 stars - problematic
    BAD = "bad"             # 1 star - should not be used


class MessageRole(str, Enum):
    """Role of message sender."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ConversationMessage(BaseModel):
    """A single message in a conversation."""
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)

    # Optional metadata for context
    token_count: Optional[int] = None


class ConversationMetadata(BaseModel):
    """Metadata about the conversation context."""
    # Project context
    project_name: Optional[str] = None
    project_genre: Optional[str] = None

    # Task context
    task_type: str = "general"  # general, character_dev, worldbuilding, plot, critique, etc.

    # Model info
    provider: str = ""  # claude, chatgpt, gemini, huggingface
    model_name: str = ""

    # Generation parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    # Additional context tags
    tags: List[str] = Field(default_factory=list)


class RatedConversation(BaseModel):
    """A complete conversation with rating and metadata for fine-tuning."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # The actual conversation
    messages: List[ConversationMessage] = Field(default_factory=list)

    # Rating and feedback
    rating: ConversationRating = ConversationRating.NEUTRAL
    rating_notes: str = ""  # User explanation of why this rating

    # What made this conversation good/bad
    positive_aspects: List[str] = Field(default_factory=list)  # e.g., "good voice", "creative ideas"
    negative_aspects: List[str] = Field(default_factory=list)  # e.g., "too verbose", "broke character"

    # Metadata
    metadata: ConversationMetadata = Field(default_factory=ConversationMetadata)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    rated_at: Optional[datetime] = None

    # Export format helpers
    def to_training_format(self, format_type: str = "openai") -> Dict[str, Any]:
        """Convert to common fine-tuning formats.

        Args:
            format_type: One of 'openai', 'alpaca', 'sharegpt', 'chatml'

        Returns:
            Dict formatted for the specified training format
        """
        if format_type == "openai":
            # OpenAI fine-tuning format
            return {
                "messages": [
                    {"role": msg.role.value, "content": msg.content}
                    for msg in self.messages
                ]
            }
        elif format_type == "alpaca":
            # Alpaca format (instruction, input, output)
            # Find first user message as instruction, assistant response as output
            instruction = ""
            input_text = ""
            output = ""

            for i, msg in enumerate(self.messages):
                if msg.role == MessageRole.SYSTEM:
                    instruction = msg.content
                elif msg.role == MessageRole.USER and not input_text:
                    input_text = msg.content
                elif msg.role == MessageRole.ASSISTANT and not output:
                    output = msg.content
                    break

            return {
                "instruction": instruction or "You are a helpful writing assistant.",
                "input": input_text,
                "output": output
            }
        elif format_type == "sharegpt":
            # ShareGPT format
            conversations = []
            for msg in self.messages:
                role_map = {
                    MessageRole.SYSTEM: "system",
                    MessageRole.USER: "human",
                    MessageRole.ASSISTANT: "gpt"
                }
                conversations.append({
                    "from": role_map.get(msg.role, "human"),
                    "value": msg.content
                })
            return {"conversations": conversations}
        elif format_type == "chatml":
            # ChatML format
            formatted = ""
            for msg in self.messages:
                formatted += f"<|im_start|>{msg.role.value}\n{msg.content}<|im_end|>\n"
            return {"text": formatted}
        else:
            raise ValueError(f"Unknown format type: {format_type}")


class ConversationStore:
    """Storage manager for rated conversations."""

    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize conversation store.

        Args:
            storage_path: Path to store conversations. If None, uses default location.
        """
        if storage_path is None:
            # Default to user's app data directory
            storage_path = Path.home() / ".writer_platform" / "training_data"

        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self._conversations: Dict[str, RatedConversation] = {}
        self._load_conversations()

    def _get_conversations_file(self) -> Path:
        """Get path to conversations JSON file."""
        return self.storage_path / "rated_conversations.json"

    def _load_conversations(self) -> None:
        """Load conversations from disk."""
        file_path = self._get_conversations_file()
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                for conv_data in data.get("conversations", []):
                    conv = RatedConversation.model_validate(conv_data)
                    self._conversations[conv.id] = conv
            except Exception as e:
                print(f"Error loading conversations: {e}")

    def _save_conversations(self) -> None:
        """Save conversations to disk."""
        file_path = self._get_conversations_file()
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "conversations": [
                conv.model_dump(mode='json')
                for conv in self._conversations.values()
            ]
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)

    def add_conversation(self, conversation: RatedConversation) -> str:
        """Add a new conversation to the store.

        Args:
            conversation: The conversation to add

        Returns:
            The conversation ID
        """
        self._conversations[conversation.id] = conversation
        self._save_conversations()
        return conversation.id

    def rate_conversation(
        self,
        conversation_id: str,
        rating: ConversationRating,
        notes: str = "",
        positive_aspects: List[str] = None,
        negative_aspects: List[str] = None
    ) -> bool:
        """Rate an existing conversation.

        Args:
            conversation_id: ID of conversation to rate
            rating: The rating to assign
            notes: Optional notes explaining the rating
            positive_aspects: List of positive aspects
            negative_aspects: List of negative aspects

        Returns:
            True if successful, False if conversation not found
        """
        if conversation_id not in self._conversations:
            return False

        conv = self._conversations[conversation_id]
        conv.rating = rating
        conv.rating_notes = notes
        conv.rated_at = datetime.now()

        if positive_aspects:
            conv.positive_aspects = positive_aspects
        if negative_aspects:
            conv.negative_aspects = negative_aspects

        self._save_conversations()
        return True

    def get_conversation(self, conversation_id: str) -> Optional[RatedConversation]:
        """Get a conversation by ID."""
        return self._conversations.get(conversation_id)

    def get_all_conversations(self) -> List[RatedConversation]:
        """Get all stored conversations."""
        return list(self._conversations.values())

    def get_high_quality_conversations(
        self,
        min_rating: ConversationRating = ConversationRating.GOOD
    ) -> List[RatedConversation]:
        """Get conversations rated at or above a threshold.

        Args:
            min_rating: Minimum rating to include

        Returns:
            List of conversations meeting the threshold
        """
        rating_order = [
            ConversationRating.BAD,
            ConversationRating.POOR,
            ConversationRating.NEUTRAL,
            ConversationRating.GOOD,
            ConversationRating.EXCELLENT
        ]
        min_index = rating_order.index(min_rating)

        return [
            conv for conv in self._conversations.values()
            if rating_order.index(conv.rating) >= min_index
        ]

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation from the store."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            self._save_conversations()
            return True
        return False

    def export_for_training(
        self,
        output_path: Path,
        format_type: str = "openai",
        min_rating: ConversationRating = ConversationRating.GOOD,
        task_types: Optional[List[str]] = None
    ) -> int:
        """Export high-quality conversations for fine-tuning.

        Args:
            output_path: Path to write the training file
            format_type: Format to export (openai, alpaca, sharegpt, chatml)
            min_rating: Minimum rating to include
            task_types: Optional filter by task type

        Returns:
            Number of conversations exported
        """
        conversations = self.get_high_quality_conversations(min_rating)

        if task_types:
            conversations = [
                c for c in conversations
                if c.metadata.task_type in task_types
            ]

        training_data = []
        for conv in conversations:
            try:
                training_data.append(conv.to_training_format(format_type))
            except Exception as e:
                print(f"Error converting conversation {conv.id}: {e}")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            if format_type in ["openai", "alpaca", "sharegpt"]:
                # JSONL format for these
                for item in training_data:
                    f.write(json.dumps(item) + "\n")
            else:
                # Single JSON for others
                json.dump(training_data, f, indent=2)

        return len(training_data)

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about stored conversations."""
        total = len(self._conversations)

        rating_counts = {}
        for rating in ConversationRating:
            rating_counts[rating.value] = sum(
                1 for c in self._conversations.values()
                if c.rating == rating
            )

        task_counts = {}
        for conv in self._conversations.values():
            task = conv.metadata.task_type
            task_counts[task] = task_counts.get(task, 0) + 1

        provider_counts = {}
        for conv in self._conversations.values():
            provider = conv.metadata.provider or "unknown"
            provider_counts[provider] = provider_counts.get(provider, 0) + 1

        return {
            "total_conversations": total,
            "rating_distribution": rating_counts,
            "task_type_distribution": task_counts,
            "provider_distribution": provider_counts,
            "high_quality_count": len(self.get_high_quality_conversations())
        }


def create_conversation_from_messages(
    messages: List[Dict[str, str]],
    metadata: Optional[ConversationMetadata] = None
) -> RatedConversation:
    """Helper to create a RatedConversation from raw message dicts.

    Args:
        messages: List of {"role": "...", "content": "..."} dicts
        metadata: Optional metadata about the conversation

    Returns:
        A new RatedConversation ready for rating
    """
    conv_messages = []
    for msg in messages:
        role = MessageRole(msg.get("role", "user"))
        conv_messages.append(ConversationMessage(
            role=role,
            content=msg.get("content", "")
        ))

    return RatedConversation(
        messages=conv_messages,
        metadata=metadata or ConversationMetadata()
    )
