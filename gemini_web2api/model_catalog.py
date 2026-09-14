"""Dynamic model catalog adapter for the maintained Gemini Web backend."""
from __future__ import annotations

from typing import Any


def available_models(models: list[Any]) -> list[Any]:
    return [model for model in models if getattr(model, "is_available", True)]


def model_name(model: Any) -> str:
    return str(
        getattr(model, "model_name", None)
        or getattr(model, "name", None)
        or getattr(model, "id", None)
        or model
    )


def model_description(model: Any) -> str:
    return str(
        getattr(model, "description", None)
        or getattr(model, "display_name", None)
        or "Account-discovered Gemini Web model"
    )


def openai_models(models: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": model_name(model),
            "object": "model",
            "owned_by": "google",
            "description": model_description(model),
        }
        for model in available_models(models)
    ]


def google_models(models: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": f"models/{model_name(model)}",
            "displayName": str(getattr(model, "display_name", None) or model_name(model)),
            "description": model_description(model),
            "supportedGenerationMethods": ["generateContent", "streamGenerateContent"],
        }
        for model in available_models(models)
    ]
