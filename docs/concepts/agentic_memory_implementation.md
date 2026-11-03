# Agentic Memory — Stack 1 Implementation

**Project:** Saayam for All — AI  
**Issue:** #197  
**Stack:** Agentic Memory  
**Implementation branch:** `shivk07/issue-197/agentic-memory`  
**Status:** Local functional implementation, tested with real Groq calls

## 1. Overview

Agentic Memory allows Saayam's AI assistant to retain important information from earlier parts of an ongoing conversation.

Previously, the answer-generation service used a limited recent conversation window of 20 messages. In longer conversations, important facts from earlier messages could fall outside that window.

This implementation introduces session-scoped rolling summarization. Older conversation messages are condensed into a reusable memory summary, which is supplied alongside recent context when generating subsequent AI answers.

The current implementation focuses on **per-chat-session memory**. A new chat starts with separate memory. Long-term memory shared across independent chat sessions is outside the current scope.

## 2. Problem Being Solved

Consider a user requesting transportation assistance.

Early in the conversation, they state:

- Transportation is required every Friday.
- They must arrive before 8 AM.
- A wheelchair-accessible vehicle is required.

After 20 additional conversation turns, those requirements may no longer be available to the AI through recent chat history.

Without memory, Saayam may need to ask the user to repeat the information.

Agentic Memory preserves these details in a short summary so the assistant can continue providing context-aware responses.

## 3. Architecture

The implementation integrates with Saayam's existing Python answer-generation pipeline.

```text
User conversation
       |
       v
Lambda request handler
       |
       v
Session memory coordinator
       |
       +---- Validate conversation history
       |
       +---- Apply initial privacy filtering
       |
       +---- Identify newly expired messages
       |
       +---- Summarize expired messages
       |           |
       |           v
       |      Groq / Gemini model chain
       |
       +---- Persist summary in SQLite
       |
       v
Answer-generation service
       |
       +---- Existing system instructions
       +---- Stored memory summary
       +---- Latest conversation messages
       |
       v
Groq / Gemini answer generation
       |
       v
Response to user
```

SQLite is used as a local demonstration database. It is not intended to serve as the final distributed persistence layer for production Lambda deployments.

### Major components

| Component | Purpose |
|---|---|
| `services/session_memory.py` | Coordinates session-scoped rolling memory updates |
| `services/sqlite_memory_store.py` | Persists session summaries and deletion state |
| `services/memory_summarizer.py` | Generates summaries through the configured model chain |
| `services/memory_privacy.py` | Applies initial sensitive-data filtering |
| `services/memory_validation.py` | Validates conversation input |
| `services/memory_store.py` | Defines the version-conflict error shared by the store and its callers |
| `utils/generate_answer_service.py` | Forwards optional memory context |
| `utils/__init__.py` | Includes memory context in model requests |
| `lambda_function.py` | Provides feature-flagged local integration |

## 4. Memory Lifecycle

### 4.1 Session creation

Each chat session has its own identifier and independent memory.

A new session does not inherit the summary from another session.

### 4.2 Conversation processing

The system accepts conversation history, validates the messages, and identifies older messages that have moved beyond the recent context window.

Expired messages are processed in batches for summarization. Each request summarizes at most three batches and saves after each one, so a long backlog catches up over several requests instead of delaying one answer.

If the transcript no longer begins with the messages already summarized (the client trimmed it or restarted it under the same session), the stored summary is discarded and summarization starts again from the transcript received. Memory problems never block the answer: the request is answered without memory instead.

### 4.3 Summary persistence

The generated summary is saved in SQLite, along with bookkeeping information needed to track already-processed history and support version checks.

The session storage design avoids persisting full raw conversation transcripts in the SQLite memory record.

### 4.4 Answer generation

The existing answer-generation service receives the recent conversation history and an optional memory summary.

The model can therefore reference earlier requirements without receiving the complete original conversation.

### 4.5 Memory correction

When a user corrects earlier information, the latest messages can override the older summary during answer generation.

After the correction becomes eligible for rolling summarization, the persisted summary can also be updated.

### 4.6 Memory deletion

The local implementation supports viewing and deleting session memory.

Deletion removes the saved session summary and records an invalidated session identifier to prevent the same transcript from recreating that session's memory.

A new session identifier is required after deletion.

The current View/Delete handler is restricted to local demonstration use. It is not an authenticated public API.

## 5. Local Development Setup

### Requirements

- Python with the project's dependencies installed
- Access to a supported Groq model
- A local `.env` file containing the development API key
- `python-dotenv` for loading local credentials
- SQLite, available through Python's standard library

Example local `.env` configuration:

```dotenv
GROQ_API_KEY=replace_with_your_local_key
SAAYAM_LOCAL_MODEL_KEYS=1
```

The `.env` file must remain outside version control.

The local credential fallback is explicitly enabled for development and does not replace the existing AWS Parameter Store configuration used by Saayam.

### Run offline tests

```powershell
pytest -q
```

The memory tests are offline: the summarizer and the answer model are mocked, and SQLite runs against a temporary file.

### Live demonstration and evaluation

The live Groq demonstration and the evaluations in section 6 were run locally with synthetic data and real model API calls. Those scripts are not part of this change.

## 6. Experimental Evaluation

### 6.1 Baseline vs. Agentic Memory

Three synthetic Saayam assistance scenarios were evaluated:

1. Transportation assistance
2. Food assistance
3. Housing assistance

Each scenario consisted of 25 messages. Three important facts were introduced within the first five messages and were absent from the final 20-message context.

Each scenario was repeated three times using real Groq model calls.

| Scenario | Baseline recall | Agentic Memory recall |
|---|---:|---:|
| Transportation | 0/9 | 9/9 |
| Food assistance | 0/9 | 9/9 |
| Housing | 0/9 | 9/9 |
| **Total** | **0/27 (0%)** | **27/27 (100%)** |

The automated evaluator checked whether predefined facts appeared in the generated answers. The resulting responses were also reviewed for obvious factual inconsistencies.

**Finding:** In these synthetic conversations, the memory-enabled implementation successfully preserved older requirements that were unavailable to the baseline model.

These results demonstrate the tested behavior but do not establish general production accuracy.

### 6.2 Latency

Observed average end-to-end execution times:

| Scenario | Baseline | Agentic Memory |
|---|---:|---:|
| Transportation | 0.61 s | 2.58 s |
| Food assistance | 2.59 s | 5.60 s |
| Housing | 5.99 s | 9.88 s |
| **Overall** | **3.06 s** | **6.02 s** |

Memory summarization introduces additional model calls and processing time.

The evaluation did not establish production latency guarantees. Further optimization and testing are required.

### 6.3 Memory correction experiment

A separate real-model experiment evaluated changing user requirements.

The original requirement was transportation every Friday before 8 AM, with wheelchair accessibility.

The user subsequently corrected the schedule to Monday before 10 AM.

Three phases were tested:

| Phase | Result |
|---|---|
| Original schedule summarized | Correct |
| Recent correction overrides older information in the answer | Correct |
| Expired correction incorporated into persistent memory | Correct |

The final SQLite summary and generated answer reflected Monday before 10 AM.

This demonstrates that the rolling summary can incorporate updated requirements in the tested example.

## 7. Privacy and Deletion Tests

Offline regression tests verified:

- Initial filtering of a synthetic password.
- Initial filtering of a synthetic payment-card number.
- Absence of a synthetic raw-transcript marker in the SQLite database file.
- Deleted session identifiers cannot recreate their previous memory.
- Newly created session identifiers can maintain independent memory.

These tests verify the specified cases, not comprehensive protection against all sensitive-data formats.

## 8. Known Limitations

### Local-only persistence

SQLite is used for functional demonstration. Production deployment requires an approved shared, durable storage solution.

### Authentication and authorization

The local memory-control handler is not suitable for public exposure. Production endpoints must verify that an authenticated user is authorized to access or delete the associated session.

### Temporarily stale summaries

A recent user correction may be honored by answer generation before it is incorporated into the persisted summary.

The future View My Memory interface must account for that possibility.

### Privacy filtering

Current redaction rules are initial safeguards. Further coverage, data minimization, provider-data handling review, and logging review are required.

The current tests do not prove that arbitrary sensitive information is excluded from all model requests or system logs.

### Deletion scope

Deleting the local SQLite summary does not automatically delete copies of conversation history held by other components, provider-side records, logs, or backups.

Production deletion behavior must be defined across the full system.

### Model behavior

The experiment uses a limited set of synthetic conversations. Additional evaluations are needed for ambiguous instructions, contradictory information, multilingual conversations, unsupported claims, and complex assistance requests.

### Performance and cost

Rolling summarization adds model calls. Batching, summary reuse, and cost optimization require further evaluation under realistic traffic.

## 9. Future Integration

Recommended next steps include:

1. Agree on production session storage and retention requirements with the Data Team.
2. Implement authenticated, session-scoped memory access and deletion.
3. Coordinate a user-facing View My Memory interface with the frontend team.
4. Expand privacy and adversarial testing.
5. Measure memory quality, model cost, and latency under representative usage.
6. Add monitoring and operational safeguards for production deployment.

## 10. Conclusion

Stack 1 provides a functional local implementation of session-based Agentic Memory integrated with Saayam's answer-generation pipeline.

The solution uses rolling summaries to preserve relevant context beyond the existing 20-message window and stores session summaries in SQLite.

Offline testing and live Groq evaluations demonstrate successful context retention, session isolation, correction handling, and local deletion behavior in the tested cases.

The implementation provides a working foundation for production integration, subject to authentication, privacy, persistence, and operational review.