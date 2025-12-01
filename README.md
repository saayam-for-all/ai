
#  🔍 Saayam AI Assistant 🤖 

Saayam AI Assistant is a web-based application built with Flask that allows users to query various AI models (Meta AI, Gemini, ChatGPT, and Grok) for answers across multiple categories (e.g., Jobs, Education, Finance). The application uses zero-shot classification to predict relevant categories for user queries and provides detailed, formatted responses. Additionally, it collects performance metrics (latency, speed, temperature, token counts) to compare the efficiency of each AI model.

## 🧠 Features
- **Multi-Model Support**: Query Meta AI, Gemini, ChatGPT, or Grok via a command-line argument.
- **Category Prediction**: Uses zero-shot classification (`facebook/bart-large-mnli`) to predict relevant categories for user queries.
- **Formatted Responses**: Responses are structured with bullet points, bold headings, and clear sections for readability.
- **Performance Metrics**: Measures latency (TTFT/TTLT), speed (tokens/second), temperature, and token counts for each model.
- **Web Interface**: A user-friendly interface built with Flask, HTML, and JavaScript, with Markdown rendering for responses.

## 🔧 Setup Instructions

### 1. Create & Activate Conda Environment
Create a Conda environment with Python 3.10 and activate it:

```bash
conda create -n saayam-env python=3.10
conda activate saayam-env
```

### 2. Clone the Repository
Clone the project repository to your local machine:

```bash
git clone https://github.com/RobuRishabh/Saayam_ai.git
cd Saayam_ai
```

### 3. Install Requirements
Install the required Python packages listed in requirements.txt:

```bash
pip install -r requirements.txt
```

Note: Ensure you have the following packages in your requirements.txt:

```
flask
transformers
meta-ai-api
google-generativeai
openai
groq
python-dotenv
tiktoken
```

### 4. Set Up Environment Variables
Create a .env file in the project root directory and add your API keys for Gemini, ChatGPT, and Grok:

```
GEMINI_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key
GROQ_API_KEY=your_groq_api_key
```

Note: Meta AI doesn’t require an API key in this setup (uses meta-ai-api library).

### 5. Run the Application
Run the application with a specific AI model using the --model argument. The available models are meta_ai, gemini, openai, and grok.

Meta AI:
```bash
python app.py --model meta_ai
```

Gemini:
```bash
python app.py --model gemini
```

ChatGPT (OpenAI):
```bash
python app.py --model openai
```

Grok:
```bash
python app.py --model grok
```

After running the application, open your browser and navigate to http://127.0.0.1:5000 to access the Saayam AI Assistant interface.

## 📁 Project Structure

```
Saayam_ai/
├── app.py                 # Main application with multi-model support and metrics
├── MetaAIAPI_app.py       # Meta AI-only version (simpler implementation)
├── templates/
│   └── index.html         # Frontend HTML template
├── static/
│   ├── apple-touch-icon.png
│   ├── favicon-16x16.png
│   ├── favicon-32x32.png
│   ├── favicon.ico
│   └── site.webmanifest    # Web manifest for favicon and icons
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (API keys)
├── model_metrics.log       # Log file for performance metrics
└── .gitignore              # Git ignore file
```

## 📊 API Performance Evaluation
The application collects performance metrics for each AI model, including latency, speed, temperature, and token counts. The metrics were evaluated using the query "Suggest me good job searching websites for international students" in the "Jobs" category.

### Performance Metrics

**Meta AI**:
- Model: meta_ai
- Temperature: 0.7 (default)
- Time to First Token (TTFT): 15.185 seconds
- Total Response Time (TTLT): 15.185 seconds
- Speed: 20.81 tokens/second
- Input Tokens: 127
- Output Tokens: 316

**Gemini**:
- Model: gemini
- Temperature: 0.7
- Time to First Token (TTFT): 4.515 seconds
- Total Response Time (TTLT): 4.515 seconds
- Speed: 100.32 tokens/second
- Input Tokens: 127
- Output Tokens: 453

**ChatGPT (OpenAI)**:
- Model: openai
- Temperature: 0.7
- Time to First Token (TTFT): 4.619 seconds
- Total Response Time (TTLT): 4.619 seconds
- Speed: 81.83 tokens/second
- Input Tokens: 176
- Output Tokens: 378

**Grok**:
- Model: grok
- Temperature: 0.7
- Time to First Token (TTFT): 0.856 seconds
- Total Response Time (TTLT): 0.856 seconds
- Speed: 630.66 tokens/second
- Input Tokens: 127
- Output Tokens: 540

### Cost Analysis

- **Meta AI**: Free (unofficial API), but may have rate limits or reliability issues.
- **Gemini**: Free tier available, with paid plans for higher usage.
- **ChatGPT**: Pay-per-use ($0.002 per 1K tokens for gpt-3.5-turbo).
- **Grok**: Free tier available, with paid plans for higher usage.

### Limitations

- **Meta AI**: Slow, low speed, lacks temperature control.
- **Gemini**: Moderate performance, potential tokenization differences.
- **ChatGPT**: Reliable, slightly slower than Grok.
- **Grok**: Fastest, high output token count (verbosity).

## ⚖️ Comparison with Alternative Solutions

| Model     | Speed (tokens/s) | TTLT (s) | Cost         | Quality               |
|-----------|------------------|----------|--------------|------------------------|
| Meta AI   | 20.81            | 15.185   | Free         | Least consistent       |
| Gemini    | 100.32           | 4.515    | Free tier    | Moderate consistency   |
| ChatGPT   | 81.83            | 4.619    | Pay-per-use  | Highly consistent      |
| Grok      | 630.66           | 0.856    | Free tier    | Practical, fast        |

## 🛠️ Proof-of-Concept Implementation

### Overview
Flask-based web app to query 4 models, classify categories, format answers, and log metrics.

### Backend (`app.py`)
- Flask app, handles routes `/predict_categories` and `/generate_answer`
- Model passed using `--model` CLI argument
- Collects and logs metrics (TTFT, TTLT, token counts, temperature)

### Frontend (`index.html`)
- HTML + JavaScript interface
- Markdown rendering using marked.js
- Submits subject, description, category
- Displays response + metrics

### Example
```bash
python app.py --model grok
```
Visit [http://127.0.0.1:5000](http://127.0.0.1:5000)

## 📈 Analysis and Recommendations

- **Fastest**: Grok (0.856s TTLT, 630.66 tokens/s)
- **Most Consistent**: ChatGPT
- **Cost-Effective**: Gemini & Grok
- **Slowest**: Meta AI

### Recommendations

- Use **Grok** for real-time speed
- Use **ChatGPT** for reliability & consistency
- Use **Gemini** for cost-conscious performance
- Avoid **Meta AI** for production

## 🚀 Future Improvements

- Enable streaming for better TTFT
- Add cosine similarity for response sensitivity
- Load testing (e.g., locust)
- Caching frequent queries to save cost

## 🙌 Acknowledgments

Built with ❤️ using Flask, Transformers, and AI APIs.
Special thanks to the open-source contributors of meta-ai-api.
