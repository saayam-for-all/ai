# Saayam Predict AI Service

A Flask-based AI service that provides intelligent conversational assistance and support across various categories including food assistance, housing support, healthcare, education, and elderly care. The service uses Groq's LLaMA model with automatic fallback to Google's Gemini API for natural language processing and category prediction with context-aware conversational capabilities.

## Features

- **Conversational Chatbot**: Multi-turn conversations with context maintenance (RAG-like functionality)
- **Category Prediction**: Automatically classifies user requests into predefined help categories
- **Intelligent Answer Generation**: Provides contextual, actionable solutions based on user input
- **Auto-Subject Generation**: Automatically generates concise subjects (max 70 chars) from descriptions when not provided
- **API Fallback Mechanism**: Automatic fallback from Groq to Gemini API if Groq fails or API key is missing
- **Emergency Phone Numbers**: Responses include relevant emergency contact numbers (911, 112, crisis hotlines, etc.)
- **Optimized Prompts**: Short, precise, and accurate answers (2-4 sentences, under 100 words)
- **Multi-category Support**: Covers 6 main categories with 50+ subcategories
- **Context-Aware**: Maintains conversation history across multiple turns
- **Location, Gender & Age Support**: Personalized responses based on user context
- **AWS Lambda Ready**: Deployable as serverless function
- **CORS Enabled**: Ready for web application integration

## Quick Start

### 1. Prerequisites

- **Python 3.14+** - Download from [python.org](https://www.python.org/downloads/)
- Verify installation: `python --version` (should show 3.14.x)

### 2. Installation

```bash
# Clone the repository
git clone <repository-url>
cd Saayam-Predict

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Setup

Create a `.env` file in the root directory:
```
GROQ_API_KEY=your_groq_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here  # Optional - used as fallback if Groq fails
```

**Note:** At least one API key is required. If `GROQ_API_KEY` is not provided or Groq API fails, the service will automatically fall back to Gemini API (if `GEMINI_API_KEY` is set).

### 4. Run the Service

```bash
python app.py
```

The service will start on `http://localhost:3001`

## API Endpoints

### 1. Health Check
```
GET /
```
Returns API status confirmation.

**Response:**
```json
{
  "message": "API is running"
}
```

### 2. Predict Categories
```
POST /predict_categories
```
Automatically predicts the category for a user request.

**Request Body:**
```json
{
  "subject": "string",
  "description": "string"
}
```

**Response:**
```json
"FOOD_ASSISTANCE"
```

### 3. Generate Subject
```
POST /generate_subject
```
Generates a concise subject (max 70 characters by default) from a description using AI.

**Request Body:**
```json
{
  "description": "string (required)",
  "max_length": "integer (optional, default: 70, max: 200)"
}
```

**Response:**
```json
{
  "subject": "Generated subject text",
  "max_length": 70,
  "description_length": 45
}
```

**Example:**
```bash
curl -X POST http://localhost:3001/generate_subject \
  -H "Content-Type: application/json" \
  -d '{
    "description": "I need help finding food banks and meal programs in my area",
    "max_length": 70
  }'
```

**Response:**
```json
{
  "subject": "Finding food banks and meal programs",
  "max_length": 70,
  "description_length": 58
}
```

### 4. Generate Answer (Conversational)
```
POST /generate_answer
```
Generates contextual answers with conversation history support.

**Request Body:**
```json
{
  "category": "string (category ID like '1.1' or constant like 'FOOD_ASSISTANCE')",
  "subject": "string (optional - auto-generated from description if not provided)",
  "description": "string (current user message)",
  "location": "string (optional)",
  "gender": "string (optional)",
  "age": "string (optional)",
  "conversation_history": [
    {
      "role": "user",
      "content": "Previous user message"
    },
    {
      "role": "assistant",
      "content": "Previous assistant response"
    }
  ]
}
```

**Response:**

If subject was auto-generated:
```json
{
  "answer": "Generated answer text with markdown formatting",
  "subject": "Auto-generated subject (max 70 characters)",
  "subject_generated": true
}
```

If subject was provided:
```json
"Generated answer text with markdown formatting"
```

**Note:** The API maintains backward compatibility. When a subject is provided, it returns just the answer string. When auto-generated, it returns a JSON object with the answer and generated subject.

### 5. Find Organizations (Gemini Web Search)
```
POST /find_organizations
```
Use Gemini's built-in google_search tool to surface reputable organizations tailored to the user's need.

**Request Body:**
```json
{
  "subject": "string (optional)",
  "description": "string (required)",
  "location": "string (optional)"
}
```

**Response:**
```json
{
  "organizations": [
    {
      "name": "string",
      "website": "string or null",
      "summary": "string",
      "phone": "string or null",
      "relevance": "string"
    }
  ]
}
```

**Notes:**
- Requires `GEMINI_API_KEY` in `.env`.
- Uses Gemini `google_search` and returns structured JSON validated against the `organizations` schema (name, website, summary, phone, relevance). Invalid model responses return HTTP 500.
- In the future, the results from this endpoint can be grounded with google search results for no hallucinations and thus obtaining factual and reliable information.

## Category Input Format

The API accepts categories in two formats:

### 1. Category ID (Recommended)
- Format: `"1.1"`, `"3.2"`, `"4.3"`, etc.
- These are the keys in `help_categories` dictionary
- Example: `"1.1"` → `"FOOD_ASSISTANCE"`

### 2. Category Constant
- Format: `"FOOD_ASSISTANCE"`, `"RENTING_SUPPORT"`, etc.
- These are the values in `help_categories` dictionary
- Can be used directly in API calls

### Special: General Category
- Use `"General"` or `"0.0.0.0.0"` for automatic category prediction
- The system will analyze the subject and description to determine the best category

## Supported Categories

### 1. Food & Essentials Support
- `"1"` or `"FOOD_AND_ESSENTIALS_SUPPORT"` - General food support
- `"1.1"` or `"FOOD_ASSISTANCE"` - Food assistance
- `"1.2"` or `"GROCERY_SHOPPING_AND_DELIVERY"` - Grocery shopping
- `"1.3"` or `"COOKING_HELP"` - Cooking assistance

### 2. Clothing Support
- `"2.1"` or `"DONATE_CLOTHES"` - Donate clothes
- `"2.2"` or `"BORROW_CLOTHES"` - Borrow clothes
- `"2.3"` or `"EMERGENCY_ASSISTANCE"` - Emergency assistance
- `"2.3.1"` or `"EMERGENCY_CLOTHING_ASSISTANCE"` - Emergency clothing
- `"2.4"` or `"SEASONAL_DRIVE_NOTIFICATION"` - Seasonal drives
- `"2.5"` or `"TAILORING"` - Tailoring services

### 3. Housing Support
- `"3"` or `"HOUSING_SUPPORT"` - General housing support
- `"3.1"` or `"FIND_A_ROOMMATE"` - Find a roommate
- `"3.2"` or `"RENTING_SUPPORT"` - Renting support
- `"3.3"` or `"HOUSEHOLD_ITEM_EXCHANGE"` - Item exchange
- `"3.4"` or `"MOVING_ASSISTANCE"` - Moving help
- `"3.5"` or `"CLEANING_HELP"` - Cleaning assistance
- `"3.6"` or `"HOME_REPAIR_SUPPORT"` - Home repairs
- `"3.7"` or `"UTILITIES_SETUP"` - Utilities setup

### 4. Education & Career Support
- `"4"` or `"EDUCATION_CAREER_SUPPORT"` - General education support
- `"4.1"` or `"COLLEGE_APPLICATION_HELP"` - College applications
- `"4.2"` or `"SOP_ESSAY_REVIEW"` - Essay/SOP review
- `"4.3"` or `"TUTORING"` - Tutoring services

### 5. Healthcare & Wellness Support
- `"5"` or `"HEALTHCARE_WELLNESS_SUPPORT"` - General healthcare
- `"5.1"` or `"MEDICAL_NAVIGATION"` - Medical navigation
- `"5.2"` or `"MEDICINE_DELIVERY"` - Medicine delivery
- `"5.3"` or `"MENTAL_WELLBEING_SUPPORT"` - Mental health
- `"5.4"` or `"MEDICATION_REMINDERS"` - Medication reminders
- `"5.5"` or `"HEALTH_EDUCATION_GUIDANCE"` - Health education

### 6. Elderly Support
- `"6"` or `"ELDERLY_SUPPORT"` - General elderly support
- `"6.1"` or `"SENIOR_LIVING_RELOCATION"` - Senior living
- `"6.2"` or `"DIGITAL_SUPPORT_FOR_SENIORS"` - Digital support
- `"6.3"` or `"MEDICAL_HELP"` - Medical help for seniors
- `"6.4"` or `"ERRANDS_TRANSPORTATION"` - Errands & transportation
- `"6.5"` or `"SOCIAL_CONNECTION"` - Social connection
- `"6.6"` or `"MEAL_SUPPORT"` - Meal support

## Usage Examples

### Example 1: First Request (No Conversation History)

```bash
curl -X POST http://localhost:3001/generate_answer \
  -H "Content-Type: application/json" \
  -d '{
    "category": "1.1",
    "subject": "Need food help",
    "description": "I need help finding food resources in my area",
    "location": "San Francisco, CA",
    "gender": "Female",
    "age": "35"
  }'
```

### Example 2: Follow-up Request (With Conversation History)

```bash
curl -X POST http://localhost:3001/generate_answer \
  -H "Content-Type: application/json" \
  -d '{
    "category": "1.1",
    "subject": "Need food help",
    "description": "What documents do I need to apply?",
    "location": "San Francisco, CA",
    "gender": "Female",
    "age": "35",
    "conversation_history": [
      {
        "role": "user",
        "content": "Subject: Need food help\nQuestion: I need help finding food resources in my area"
      },
      {
        "role": "assistant",
        "content": "Here are food resources in San Francisco..."
      }
      
    ]
  }'
```

### Example 3: Using Category Constant

```bash
curl -X POST http://localhost:3001/generate_answer \
  -H "Content-Type: application/json" \
  -d '{
    "category": "FOOD_ASSISTANCE",
    "subject": "Food help",
    "description": "Where can I get free meals?",
    "location": "Los Angeles, CA"
  }'
```

### Example 4: Auto-Category Detection (General)

```bash
curl -X POST http://localhost:3001/generate_answer \
  -H "Content-Type: application/json" \
  -d '{
    "category": "General",
    "subject": "Help needed",
    "description": "I need help with transportation"
  }'
```

### Example 5: Auto-Subject Generation

```bash
curl -X POST http://localhost:3001/generate_answer \
  -H "Content-Type: application/json" \
  -d '{
    "category": "1.1",
    "subject": "",
    "description": "I need help finding food banks and meal programs in my area",
    "location": "New York, NY"
  }'
```

**Response:**
```json
{
  "answer": "Here are food resources in New York...",
  "subject": "Finding food banks and meal programs",
  "subject_generated": true
}
```

## Project Structure

```
.
├── .gitignore                        # Git ignore file
├── app.py                            # Main Flask application
├── lambda_handler.py                 # AWS Lambda handler
├── requirements.txt                  # Python dependencies
├── README.md                         # This file
├── routes/
│   ├── __init__.py
│   ├── generate_answers.py          # Answer generation endpoint
│   ├── predict_categories.py        # Category prediction endpoint
│   └── generate_subject.py          # Subject generation endpoint
├── services/
│   ├── __init__.py
│   ├── classification_service.py    # Category prediction logic
│   └── generate_answer_service.py   # Answer generation logic
└── utils/
    ├── __init__.py
    ├── categories.py                 # Category mappings
    ├── categories_with_description.py # Category descriptions
    ├── client.py                     # API client with Groq/Gemini fallback
    ├── prompts.py                    # AI prompts for different categories
    └── subject_generator.py          # Auto-subject generation utility
```

## Dependencies

- **Flask**: Web framework
- **Groq**: AI model provider (LLaMA 3.1 8B Instant) - Primary provider
- **google-genai**: Google Gemini API client - Fallback provider
- **serverless-wsgi**: AWS Lambda deployment support
- **python-dotenv**: Environment variable management
- **pydantic**: Structured output validation for Gemini responses

## Conversational Features

The service supports multi-turn conversations with context maintenance:

- **Context Preservation**: Previous messages are maintained across turns
- **Follow-up Questions**: The AI understands references to previous answers
- **No Conversation IDs**: Context is passed in each request (stateless)
- **RAG-like Behavior**: Similar to Retrieval Augmented Generation, maintains conversation context

### How It Works

1. **First Request**: User sends category, subject, description, and optional context (location, gender, age)
2. **Response**: System returns an answer
3. **Follow-up Requests**: User includes `conversation_history` with previous messages
4. **Context-Aware Response**: System uses full conversation history to provide relevant answers

## AWS Lambda Deployment

The service is configured for AWS Lambda deployment. See deployment options:

### Option 1: AWS SAM (Recommended)

1. **Create `template.yaml`** (see deployment guide)
2. **Build and deploy**:
   ```bash
   sam build
   sam deploy --guided
   ```

### Option 2: Serverless Framework

1. **Install Serverless Framework**:
   ```bash
   npm install -g serverless
   ```

2. **Create `serverless.yml`** (see deployment guide)

3. **Deploy**:
   ```bash
   serverless deploy
   ```

### Option 3: Manual Deployment

1. **Create deployment package**:
   ```bash
   zip -r saayam-predict.zip . -x "*.git*" "*__pycache__*" "*.pyc"
   ```

2. **Upload to Lambda** via AWS Console or CLI

### Environment Variables for Lambda

- `GROQ_API_KEY`: Your Groq API key (required if using Groq)
- `GEMINI_API_KEY`: Your Google Gemini API key (optional - used as fallback)
- `SERVICE_PROVIDER`: Optional (defaults to "groq")

**Note:** The service will automatically use Gemini as a fallback if Groq API fails or if `GROQ_API_KEY` is not provided (as long as `GEMINI_API_KEY` is set).

## Error Handling

- **400 Bad Request**: Missing required fields or invalid category
  ```json
  {
    "error": "Category and description are required"
  }
  ```

- **500 Internal Server Error**: AI service errors or processing failures
  ```json
  {
    "error": "Error message",
    "traceback": "Detailed error traceback"
  }
  ```

## Features Details

- **Short, Precise Answers**: All answers are optimized to be 2-4 sentences (under 100 words)
- **Location-Aware**: Answers include location-specific resources and information
- **Context-Aware**: Utilizes subject, description, location, gender, and age for personalized responses
- **Auto-Category Detection**: General category automatically predicts the appropriate category
- **API Fallback**: Automatic fallback from Groq to Gemini ensures service reliability
- **100% Accurate**: Prompts emphasize verified, factual information only
- **Markdown Support**: Responses include markdown formatting (bold, italic, lists)
- **CORS Enabled**: Full CORS support for web applications

## API Provider Fallback

The service implements an intelligent fallback mechanism:

1. **Primary Provider**: Groq API (LLaMA 3.1 8B Instant)
   - Used when `GROQ_API_KEY` is available
   - Fast inference with low latency

2. **Fallback Provider**: Google Gemini API (Gemini 2.5 Flash)
   - Automatically used if Groq API fails or key is missing
   - Requires `GEMINI_API_KEY` to be set
   - Ensures service availability even if primary provider is unavailable

**How it works:**
- Service attempts to use Groq API first
- If Groq fails (API error, rate limit, missing key), automatically falls back to Gemini
- All services (classification, answer generation, subject generation) support fallback
- Transparent to API consumers - no code changes needed

## Development

The codebase follows a clean, modular structure:
- **Routes**: Handle HTTP requests and responses
- **Services**: Contain business logic and AI integration
- **Utils**: Shared utilities (categories, prompts, client)

### Key Components

- **Conversational Prompts**: `utils/prompts.py` contains category-specific prompts optimized for chat
- **Category Mapping**: `utils/categories.py` maps category IDs to constants
- **Service Layer**: Abstraction for easy provider switching
- **CORS Handling**: Global CORS support in `app.py`

## API Integration

The service includes full CORS support for web application integration. All endpoints return JSON responses with appropriate error handling and support for:

- Preflight OPTIONS requests
- Cross-origin requests
- Custom headers

## Testing

Test the API using curl commands or any HTTP client. See the Usage Examples section above for sample curl commands.

