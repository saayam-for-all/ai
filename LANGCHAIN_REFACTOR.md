# LangChain Refactor Notes

This document explains what changed in this branch, why we moved to LangChain,
and how the refactor improves maintainability and future scalability.

## Summary (before vs. now)

**Before**
- The generate-answer flow built prompts and messages manually in service code.
- Provider logic was tied directly to specific SDKs.
- Fallback handling was custom and embedded in the service layer.
- Adding a new model/provider required touching core logic and increasing coupling.

**Now**
- The generate-answer flow is built on LangChain primitives.
- Model selection and fallback are centralized in one place.
- Prompt + history composition is standardized and testable.
- The public API surface is preserved via a thin wrapper for backward compatibility.

## What changed in this branch

- Added a LangChain model layer in `utils/langchain_models.py`.
  - Groq is primary (`llama-3.1-8b-instant`).
  - Gemini is fallback (`gemini-2.5-flash`).
  - Fallback logic uses LangChain’s `with_fallbacks(...)`.
- Standardized message building using `ChatPromptTemplate` and `MessagesPlaceholder`.
- Kept `generate_ai_answer(...)` as a stable wrapper so callers did not change.
- Added tests for prompt/message structure and the LangChain-backed answer path.

## Why LangChain is better here

- **Clear abstraction:** Prompts and message assembly are declarative and consistent.
- **Provider portability:** Swapping providers is localized to one model layer.
- **Simpler fallback:** Built-in fallback behavior reduces custom error handling.
- **Better testability:** The chain can be mocked cleanly without API keys.
- **Lower SDK lock-in:** Core service code is no longer tied to a single SDK.

## How this helps scale and add features

- **Add providers quickly:** Introduce new providers without rewriting service logic.
- **Extend capabilities:** Tools, memory, routing, or structured outputs can be layered
  on top of the chain without a full refactor.
- **Consistent LLM interface:** Future LLM flows can reuse the same abstraction.

## One-line justification for the refactor

We moved the generate-answer flow to LangChain to reduce provider coupling,
standardize prompt construction, improve fallback reliability, and make future
LLM features easier to add without rewriting core logic.
