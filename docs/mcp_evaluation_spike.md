# MCP Evaluation Spike — Final Evaluation

*Current Conversation Context Architecture*

---

## Objective

The objective of this spike was to evaluate whether the Model Context Protocol (MCP) provides meaningful value for Saayam's conversation/session-context architecture, before introducing a session layer or adopting MCP in production.

The investigation first mapped the existing conversation-history flow, then compared an MCP-based tool path with an equivalent in-process tool-calling path.

No production code was modified as part of the spike.

## Current Conversation Flow

The More Information chat sends `conversation_history` in the request payload on every follow-up.

The AI service:

- Receives and validates `conversation_history`.
- Normalizes the provided messages.
- Keeps up to the latest 20 messages.
- Truncates each message to 4,000 characters.
- Identifies the latest user message as the current question when applicable.
- Combines the conversation with the system prompt and original request context.
- Sends the resulting messages to Groq, with Gemini as the fallback provider.

The current flow is therefore:

```
Client → Lambda → conversation history normalization → prompt/context assembly → Groq → Gemini fallback → response
```

## Current Context Management

The existing implementation already provides application-level conversation management.

| **Area** | **Current implementation** |
| --- | --- |
| Context source | Client-provided `conversation_history` |
| Persistence | None |
| Server-side session | None |
| Maximum messages | 20 |
| Maximum message size | 4,000 characters |
| Current question | Latest user message |
| Message representation | LangChain `HumanMessage` / `AIMessage` |
| Original request context | Included for follow-up requests |
| Prompt construction | Application code |
| LLM provider | Groq with Gemini fallback |
| Database/session storage | None |
| Service model | Stateless |

The frontend currently maintains the active conversation and sends the accumulated history with each follow-up. The AI service only processes that history for the duration of the request.

## Persistence

There is currently no server-side persistence of conversation history.

The service does not write conversations to a database or maintain a server-side session. Once a request is processed, the supplied conversation history is discarded.

Therefore, introducing a persistent session or conversation store would be new functionality, rather than replacing an existing session system.

Introducing persistence would also require separate consideration of privacy, retention, and handling of beneficiary conversation data.

## Findings Relevant to MCP

- Conversation context is already supported through an application-level mechanism.
- The current stateless approach does not currently require a server-side session store.
- The existing message limits provide explicit control over the amount of context sent to the model.
- MCP is therefore not a direct replacement for the current `conversation_history` mechanism.
- MCP is a protocol for exposing and accessing capabilities such as tools, resources, and prompts.
- MCP's potential value for Saayam must come from a concrete capability/use-case requirement rather than from the existence of conversation history alone.
- MCP does not itself provide the persistence layer required for server-side conversation sessions.
- There was no existing MCP implementation in the AI repository at the start of the spike.

## MCP Use-Case Investigation

The repository and team onboarding material were reviewed to identify a concrete use case for evaluating MCP.

The strongest existing reference was the Mission 4 tool-calling example in the agentic onboarding material. Mission 4 demonstrates an in-process tool-calling flow using a `lookup_emergency_number(country, service)` function backed by the existing emergency-number dataset.

The reference baseline is:

```
Model → application-defined tool schema → Python function → deterministic data lookup → tool result → model response
```

The onboarding material explicitly identifies MCP as a separate evaluation area: the question is what MCP provides over the in-process tool-calling approach and what additional cost it introduces.

| **Current approach** | **MCP approach** |
| --- | --- |
| Model → in-process application tool | Model → MCP client → MCP server → capability |

The Mission 4 implementation was used only as an architectural reference and was not imported into the MCP evaluation branch.

## POC Design

### POC Objective

The POC tested whether introducing MCP as a standardized boundary between the LLM client and an application capability provides meaningful value over the existing in-process tool-calling approach.

The POC was an architecture evaluation, not a production feature.

The emergency-number lookup was intentionally chosen because it is deterministic and already has an in-process tool-calling example in the team's onboarding material. This keeps the comparison focused on the MCP boundary rather than business logic.

### Why Emergency Lookup Was Chosen

Emergency-number lookup is not the proposed Saayam use case for MCP. It is a controlled test capability used to isolate and evaluate the MCP architectural boundary.

The capability was selected because it is deterministic, has an existing in-process tool-calling implementation in the team's Mission 4 material, and produces an easily verifiable result. This allows the baseline and MCP implementations to exercise essentially the same capability while changing only how the capability is exposed and invoked.

Therefore, the POC is evaluating MCP as a mechanism for exposing and consuming AI-facing capabilities, not evaluating emergency lookup as a product requirement.

The results should be interpreted as evidence about the MCP architecture and its trade-offs, rather than evidence that Saayam should introduce this particular tool.

### POC Capability

The POC exposed one capability:

**`lookup_emergency_number(country, service)`**

- Accepts a country and emergency service.
- Performs a deterministic lookup against the existing emergency-number data.
- Returns the matching number when available.
- Returns a not-found result for unsupported input.
- Never calls an LLM itself.

Example:

- **User:** "What do I dial for a fire emergency in Japan?"
- **Tool arguments:** `country = "JP"`, `service = "fire"`
- **Tool result:** `119`

The emergency lookup was used only as a test capability. The POC evaluated the MCP architecture rather than the emergency service itself.

## POC Implementation

The POC was isolated under `mcp_poc/` and used a separate experimental dependency file:

```
requirements-mcp.txt
mcp==2.2.0
```

The production `requirements.txt` was not modified.

The POC consisted of:

```
mcp_poc/
├── __init__.py
├── baseline.py
├── client.py
├── server.py
├── inspect_discovery.py
└── tools/
    ├── __init__.py
    └── emergency_lookup.py
```

The isolated client loaded `GROQ_API_KEY` from the local `.env`. The production `utils/client.py` remained unchanged and continued to use its existing SSM-based configuration.

The POC did not modify:

- `utils/client.py`;
- `lambda_function.py`;
- production authentication/configuration;
- the existing conversation-history flow;
- the frontend;
- database/session storage.

## MCP Server and Client

The MCP server exposed `emergency_lookup` using the MCP 2.2.0 SDK. The server exposed a machine-readable tool contract containing the tool name, description, input schema, and output schema.

The client connected to the server over stdio, initialized an MCP session, called `list_tools()`, converted the discovered tool definition into a Groq tool definition, and allowed Groq to request the tool.

The tool result was then returned to Groq for the final response.

The POC therefore demonstrated:

```
Groq → MCP client → MCP server → deterministic capability → MCP result → Groq
```

## Dynamic Tool Discovery

A separate `inspect_discovery.py` client was used to verify that tool discovery was not merely an artifact of the main POC client.

The separate client did not import the underlying Python implementation `lookup_emergency_number`. Instead, it connected to the MCP server, called `list_tools()`, discovered `emergency_lookup`, read its description/input/output schemas, and invoked the discovered tool through `call_tool()`.

Observed invocation result: `119`.

This provides concrete evidence that MCP can separate a capability provider from the client consuming that capability.

### Architectural value demonstrated

The baseline application defines its tool schema locally. With MCP, the client can discover the tool contract from the external MCP server.

Therefore MCP provides a real architectural capability: dynamic tool discovery and externalization of tool implementations behind a standardized client/server boundary.

This becomes more valuable when multiple independent clients, agents, or services need to consume the same capabilities. However, the current Saayam use case has not demonstrated that requirement.

## Baseline vs MCP Evaluation

The comparison used the same Groq model (`openai/gpt-oss-20b`), natural-language question, emergency-number capability, underlying dataset, deterministic lookup behavior, effective tool schema, two model calls, and local execution environment.

The primary architectural variable was whether the capability was accessed directly in application code or through MCP.

| **Dimension** | **In-process baseline** | **MCP POC** |
| --- | --- | --- |
| Model | Groq | Groq |
| Capability | Emergency-number lookup | Same capability |
| Data source | Emergency-number dataset | Same dataset |
| Tool location | Application process | MCP server |
| Tool access | Direct Python function | MCP protocol |
| Client/server boundary | None | MCP client → MCP server |
| Model calls | 2 | 2 |
| Dependencies | Existing application dependencies | Existing dependencies + MCP |
| Process complexity | Single application path | Client/server interaction |
| Error handling | Application-level | MCP + application-level |
| Reusability | Application-specific | Potentially reusable by independent clients |
| Session persistence | Not provided | Not provided by MCP itself |

## Functional Findings

### MCP path works

The MCP path:

- Started an isolated MCP server;
- Connected an MCP client;
- Discovered the exposed tool;
- Passed model-generated arguments;
- Executed the deterministic lookup;
- Returned the tool result;
- Provided the result back to the model;
- Produced a final answer.

The separate discovery client also successfully discovered and invoked the tool without importing the underlying implementation.

### Schema quality still matters

During the POC, a loose tool schema allowed the model to generate `country = "Japan"`. The deterministic tool could not find that key because the dataset uses ISO alpha-2 country codes. The schema was tightened to explicitly require the ISO alpha-2 convention, after which the model generated `country = "JP"`.

This demonstrated that MCP transports and exposes the tool contract, but correct tool behavior still depends on good schemas, argument validation, and application-level handling.

### MCP does not guarantee final-answer grounding

The POC also showed that making a deterministic tool available does not by itself guarantee that every statement in the model's final answer is supported by the tool result. This is consistent with the existing Mission 4 lesson: a grounded tool result does not automatically make the entire final response grounded.

MCP therefore does not remove the need for normal tool validation and response-grounding controls.

## Performance and Cost

The POC was intentionally small and was not intended to be a statistically rigorous benchmark. Five repeated runs were used to identify meaningful overhead.

### End-to-end latency

| **Metric** | **Baseline** | **MCP** |
| --- | --- | --- |
| Mean | 2.024 s | 4.996 s |
| Median | 1.944 s | 4.680 s |

The MCP path was approximately 2.47× the baseline mean in this specific POC.

This should not be interpreted as intrinsic MCP protocol overhead. The POC starts a Python MCP server process for each run and performs MCP initialization and tool discovery before the model call. The result therefore represents the cost of this cold-start stdio architecture, including process startup and initialization.

A persistent MCP server could reduce this startup component, but that was outside the scope of this spike.

### Token usage

| **Metric** | **Baseline** | **MCP** |
| --- | --- | --- |
| Mean total tokens/run | 568.6 | 560.2 |
| Median total tokens/run | 570 | 555 |
| First call prompt tokens | 211 | 207 |
| Second call prompt tokens | 243 | 244 |

The difference in mean total usage was approximately 1.5%, which is not meaningful evidence of a token-cost advantage.

Prompt tokens were especially stable. In this controlled workload, MCP did not materially reduce the amount of model context being processed.

The observed token variation was primarily in completion/reasoning tokens rather than in the MCP protocol itself.

A larger MCP tool ecosystem could introduce additional model-context cost if many tool schemas are dynamically exposed to the model, but that was not measured in this one-tool POC.

## Implementation and Operational Complexity

The MCP POC required:

- A separate experimental MCP dependency;
- An MCP server;
- An MCP client;
- Stdio transport and lifecycle handling;
- MCP session initialization;
- Dynamic tool discovery;
- Conversion of MCP tool definitions into Groq tool definitions;
- Additional client/server error boundaries.

The experimental source footprint was approximately 360 lines across the POC files. This is a measurement of the small evaluation implementation only and should not be treated as an estimate of production implementation effort.

Productionizing the architecture would additionally require decisions around:

- Server lifecycle;
- Deployment;
- Observability;
- Authentication/authorization;
- Network or transport security where applicable;
- Tool versioning;
- Failure handling;
- Availability;
- Compatibility between clients and tool servers.

## Architectural Value

1. **Dynamic tool discovery:** A client can discover available tools and their schemas through the MCP server rather than maintaining the tool contract locally.
2. **Separation of capability and AI client:** The underlying capability can live in a separate MCP server process rather than inside the AI application.
3. **Potential reuse:** The separate discovery/invocation client demonstrated that an independent client can consume the same capability. This could become useful if multiple AI clients, agents, or services need access to the same tool set.
4. **Standardized capability boundary:** MCP provides a standard protocol boundary for exposing capabilities rather than requiring every AI client to implement a bespoke integration.

**Current limitation:** none of these benefits currently corresponds to a demonstrated requirement in the Saayam AI service. For the current single-application, small-tool use case, the existing in-process approach is simpler.

## Session/Context Management Relationship

The spike does not support treating MCP as a replacement for the current conversation-history mechanism.

The current architecture is:

```
Client → conversation_history → Stateless AI service → normalize/limit/assemble prompt → LLM → response; history is discarded.
```

A future persistent session architecture would require a separate session/conversation store. That is a persistence and privacy decision, not something provided by MCP itself.

MCP could potentially expose context-related capabilities in a future architecture, but this spike provides no evidence that doing so would be preferable to a purpose-built session store.

## Risk Assessment

- **Additional technical boundary:** MCP introduces a client/server boundary where the baseline has a direct function call. This adds lifecycle, transport, initialization, and failure modes.
- **Schema and argument risk:** The POC showed that tool schema quality affects whether the model generates valid arguments. MCP makes the schema discoverable, but does not eliminate the need to validate model-generated arguments.
- **Latency risk:** The current cold-start stdio POC approximately doubled mean end-to-end latency relative to the in-process baseline. The exact production impact would depend on deployment and server lifecycle.
- **Operational risk:** A production MCP architecture would require additional ownership for deployment, monitoring, security, availability, and versioning of MCP server(s).
- **Privacy risk for sessions:** MCP does not solve the privacy implications of introducing conversation persistence. Any future session store would need an explicit decision about retention, access, and handling of beneficiary conversation data.

## Final Recommendation

**Decision: NOT NOW** — specifically for the current session/context-management use case.

The spike should not adopt MCP for the current Saayam session/context-management problem.

The evaluation confirms that MCP provides real architectural benefits for capability management: dynamic tool discovery, externalization of tool implementations, a standardized client/server capability boundary, and potential reuse by independent clients or services.

The POC successfully demonstrated those benefits with a deterministic emergency lookup capability.

However, the current Saayam architecture does not demonstrate a requirement for that separation. The existing in-process tool-calling approach can provide the same capability with less infrastructure and lower measured cold-start latency.

The measurements also showed 2.024 s vs 4.996 s mean latency and 568.6 vs 560.2 mean total tokens per run for baseline vs MCP, respectively. Therefore, the current POC provides no meaningful token-cost advantage while introducing additional process and integration complexity and measurable cold-start overhead.

Most importantly, MCP does not address the original session/context question. The current service is stateless, and introducing persistent conversation sessions would be a separate architecture involving storage and privacy/retention decisions.

### Recommended Direction

- Keep `conversation_history` as the existing application-level context mechanism.
- Keep tool calling in-process where the capability set remains small and application-specific.
- Do not introduce a session store as part of this MCP spike.
- Do not introduce MCP into production based on this evaluation alone.

Revisit MCP if future requirements include:

- Multiple independent AI clients or agents consuming the same tools;
- Tools owned or deployed independently of the AI application;
- A larger tool ecosystem where standardized discovery becomes valuable;
- Cross-service or cross-language capability sharing;
- A concrete requirement for standardized AI-facing resources, tools, or prompts.

In those cases, MCP's separation and interoperability benefits may justify the additional operational complexity.

## Spike Outcome

The spike is considered successful because it answered the evaluation question without requiring a production change.

The result is not that MCP has no value. Rather:

> *MCP has demonstrated architectural value for externally shared and discoverable capabilities, but there is not currently enough evidence that Saayam needs that capability boundary, and MCP does not solve the current stateless session/context-management problem.*

The current recommendation is therefore to retain the simpler in-process architecture and revisit MCP when a concrete interoperability or external-tool requirement emerges.

## Scope and Changes

The spike remained isolated from production.

- No changes were made to production conversation handling;
- No changes were made to `utils/client.py`;
- No changes were made to `lambda_function.py`;
- No changes were made to production authentication or AWS SSM configuration;
- No changes were made to the database;
- No changes were made to session management;
- No changes were made to frontend conversation flow.

The MCP experiment was contained within the dedicated POC area and its experimental dependency file.

The production test suite was not changed as part of the spike; the existing test baseline was 278 passed.

## Final Acceptance Criteria

| **Acceptance criterion** | **Result** |
| --- | --- |
| Identify what MCP buys vs current `conversation_history` | Completed — MCP is not a persistence/session replacement; demonstrated value is capability discovery/externalization. |
| Build minimal POC against one service/capability | Completed |
| Assess fit | Completed |
| Assess implementation effort/complexity | Completed |
| Assess risk | Completed |
| Assess cost/token impact | Completed |
| Assess latency impact | Completed |
| Provide written adopt/partially-adopt/not-now recommendation | Completed — Not now |
| Make clear go/no-go decision for evaluated use case | Completed — No production adoption at this time |
