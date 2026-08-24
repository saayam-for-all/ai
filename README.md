1. Overview
This module automatically generates a concise subject/title from a user-provided description using LLMs.

Key Features:
- 
- 
- 
- 
- 
- 
- 
- 
- Uses Groq as the primary model
- Uses Gemini as fallback
- Strictly enforces maximum character length
- Applies intelligent word-boundary truncation
- Serverless deployment on AWS lambda
- API exposure through AWS API gateway
- Automated deployment via Github actions(CI/CD)
- Guarantees a return value even if all models fail

2. Dependencies
The module imports pre-initialized models from:

```python
from utils.client import groq_
llm, gemini
_
llm, _
use
_groq, _
use
_gemini
```

These models are:
- ChatGroq (llama-3.1-8b-instant)
- ChatGoogleGenerativeAI (gemini-2.5-flash)

The flags `_use_groq` and `_use_gemini` determine availability.

3. Supporting Function
`_truncate_with_word_boundary(text, max_length)`

This function ensures clean truncation.

Logic:
1. Truncate text to `max_length`.
2. Find the last space within truncated text.
3. If that space occurs after 70% of `max_length`, truncate at that space.
4. Otherwise, hard truncate.

This prevents breaking words mid-way when possible.

4. Main Function
`generate_subject_from_description(description, max_length=70)`

Parameters
- `description` `str` User’s description
- `max_length` `int` Maximum subject length (default: 70)

5. Execution Flow
Step 1 – Empty Input Handling
If:
- `description` is `None`
- `description` is empty
- `description` contains only whitespace

The function returns:
`General Inquiry`
(truncated to `max_length` if needed)

Step 2 – Prompt Construction
The system constructs this strict instruction:
`Generate a concise subject/title (maximum X characters)... Return ONLY the subject...`

The prompt explicitly enforces:
- Maximum length
- No explanation
- No extra text

6. Two Processing Paths
CASE 1 – Description Length ≤ `max_length`
If:
`len(description) <= max_length`

Flow:
1. Set `truncated = description[:max_length]`
2. Try Groq:
   - If successful:
     - Extract `ai_message.content`
     - Strip quotes and whitespace
     - If length ≤ `max_length` → return
     - Else → apply `_truncate_with_word_boundary`
3. If Groq fails → try Gemini
4. If Gemini fails → return `truncated`

Even short descriptions attempt LLM improvement.

CASE 2 – Description Length > `max_length`

Flow:
1. Try Groq
2. If Groq fails → try Gemini
3. If Gemini fails → return `_truncate_with_word_boundary(description, max_length)`

7. LLM Invocation Logic
Primary Model:
`groq_llm.invoke(prompt)`
Only used if:
- `_use_groq` and `groq_llm`

Fallback Model:
`gemini_llm.invoke(prompt)`
Only used if:
- `_use_gemini` and `gemini_llm`

8. Strict Output Enforcement
After model output:
`generated_subject = str(content).strip().strip("\"").strip("'")`

If output is empty → default to:
`General Inquiry`

If output length exceeds `max_length`:
return `_truncate_with_word_boundary(generated_subject, max_length)`

This guarantees hard length enforcement.

9. Final Fallback Guarantee
If:
- Groq fails
- Gemini fails
- No model available
- Any exception occurs

The function returns:
`_truncate_with_word_boundary(description, max_length)`

This ensures:
- No crash
- Always returns string
- Deterministic behavior

Example API Request(Postman)
Headers:
- `Content-Type: application/json`
- `Authorization: Bearer <ID_TOKEN>`

Request Body:
```json
{
  "description": "I need help finding food banks and meal programs in my area"
}
```

Response Body:
```json
{
  "statusCode": 200,
  "headers": {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*"
  },
  "body": {
    "subject": "Locating Local Food Banks and Meal Programs",
    "max_length": 70,
    "description_length": 59
  }
}
```

Example Scenarios

Example 1 – Short Description

Input:
```json
{
  "description": "Need help finding rental assistance in Chicago"
}
```

Output (Possible):
```json
{
  "subject": "Rental Assistance in Chicago"
}
```

Example 2 – Long Description

Input:
```json
{
  "description": "I recently lost my job and I am struggling financially. I need emergency rental
assistance programs in Chicago as soon as possible.
"
}
```

Possible LLM Output (Before Enforcement):
`Emergency Rental Assistance Programs in Chicago for Unemployed Individuals Facing Financial Hardship`

Final Output (After Enforcement):
```json
{
  "subject": "Emergency Rental Assistance Programs in Chicago"
}
```
(≤ 70 characters)

Example 3 – LLM Failure
If both models fail:

Input:
```json
{
  "description": "Affordable childcare support in Seattle"
}
```

Output:
```json
{
  "subject": "Affordable childcare support in Seattle"
}
```
(Truncated if necessary)

Example 4 – Empty Description

Input:
```json
{
  "description": ""
}
```

Output:
```json
{
  "subject": "General Inquiry"
}
```

Reliability Guarantees
This implementation guarantees:
- Subject always returned
- Length never exceeds `max_length`
- Word-safe truncation
- Multi-model fallback
- No unhandled exceptions
- Production-safe behavior

Execution Diagram
Description
↓
Validate input
↓
Build prompt
↓
Try Groq
↓ (if fails)
Try Gemini
↓ (if fails)
Safe truncation
↓
Return subject