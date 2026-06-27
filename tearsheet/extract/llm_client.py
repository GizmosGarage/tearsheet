"""Thin wrapper around the LLM SDK with structured output."""

from __future__ import annotations

from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from tearsheet import config

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """OpenAI client configured for pydantic structured responses."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or config.OPENAI_API_KEY
        self._model = model or config.LLM_MODEL
        self._client = OpenAI(api_key=self._api_key) if self._api_key else None

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        """Return a validated pydantic model from the LLM."""
        raise NotImplementedError
