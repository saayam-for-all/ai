## Predict Category API Endpoints

## `POST /predict_categories`

Predicts the top 3 relevant categories for a user query using zero-shot classification. This runs **locally** using the `facebook/bart-large-mnli` HuggingFace model — no API key or internet connection required.

---

### Request Headers

| Header | Value |
|--------|-------|
| Content-Type | application/json |

---

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | string | ✅ | Short title of the query |
| `description` | string | ✅ | Detailed description of the query |

---

### Example Request

```bash
curl -X POST http://127.0.0.1:5000/predict_categories \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "Job search for international students",
    "description": "I am an international student looking for software engineering jobs in the US that sponsor H1B visa"
  }'
```

---

### Example Response

```json
{
  "predicted_categories": ["Employment", "Jobs", "School"]
}
```

> The top 3 categories are returned in order of confidence score (highest first).

---

### Error Responses

| Status Code | Reason | Response |
|-------------|--------|----------|
| `400` | Missing subject or description | `{"error": "Subject and description required"}` |
| `500` | Classification model failed | `{"error": "error message here"}` |

---

### How It Works Internally

1. Combines `subject` and `description` into one string:
   `"Job search for international students. I am an international student looking for software engineering jobs in the US that sponsor H1B visa"`
2. Passes the combined string through `facebook/bart-large-mnli` zero-shot classifier
3. Compares against all 37 predefined categories
4. Returns the **top 3** most relevant categories ranked by confidence

---

### 🔄 Workflow Example

This is how `/predict_categories` fits into the full app flow:

```
Step 1: User enters subject + description on the UI
            ↓
Step 2: Frontend automatically calls POST /predict_categories
            ↓
Step 3: HuggingFace model runs locally and returns top 3 categories
            ↓
Step 4: Top 3 categories appear as clickable buttons on the UI
            ↓
Step 5: User selects a category and clicks Ask
            ↓
Step 6: Frontend calls POST /generate_answer with selected category
            ↓
Step 7: AI response + performance metrics are displayed
```



### 📋 Valid Categories

The model classifies against these **37 categories**:

| Domain | Categories |
|--------|------------|
| Education | `Elementary Education`, `Middle School Education`, `High School Education`, `University Education`, `College Admissions`, `School`, `Books` |
| Medical | `Brain Medical`, `Depression Medical`, `Eye Medical`, `Hand Medical`, `Head Medical`, `Leg Medical` |
| Finance | `Banking`, `Finance`, `Investing`, `Stocks` |
| Sports | `Baseball Sports`, `Basketball Sports`, `Cricket Sports`, `Handball Sports`, `Jogging Sports`, `Hockey Sports`, `Running Sports`, `Tennis Sports` |
| Housing | `Housing`, `Homelessness`, `Rental` |
| Lifestyle | `Clothes`, `Cooking`, `Food`, `Gardening`, `Shopping`, `Travel`, `Tourism` |
| Work | `Jobs`, `Employment` |
| Other | `Matrimonial` |

---

### 📊 Performance

| Factor | Details |
|--------|---------|
| Model | `facebook/bart-large-mnli` |
| Runs | Locally on your machine |
| First Run | Slow (~1–2 min, downloads ~1.6GB model) |
| Subsequent Runs | Fast (model cached locally) |
| Internet Required |No |


---



### ⚠️ Important Notes

> This endpoint runs **fully locally** using HuggingFace. No internet or API key needed.

> **First run** will download the `facebook/bart-large-mnli` model (~1.6GB). This may take a few minutes. Subsequent runs will be fast as the model is cached.

> `torch` is missing from `requirements.txt`. Install it manually before running the app:
> ```bash
> pip install torch
> ```

---

### 🛠️ Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `No module named torch` | `torch` not in `requirements.txt` | Run `pip install torch` |
| `No module named meta_ai_api` | Wrong conda environment active | Run `conda activate saayam-env` |
| Slow first response | Downloading HuggingFace model | Wait for the download to complete |
| `400 Bad Request` | Missing `subject` or `description` | Include both fields in the request body |
| `NameError: name 'torch' is not defined` | `torch` not installed | Run `pip install torch` |