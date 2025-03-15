
# 🧠 Saayam AI Assistant

Saayam is an intelligent assistant built with Flask that combines:
- 🤖 GROQ’s LLaMA model for answer generation
- 🔍 Hugging Face's zero-shot classification to predict relevant categories

Users can:
- Enter a subject and description
- Let the system predict the best category
- Or manually choose a category
- Get instant AI-generated responses

---

## 🔧 Setup Instructions

### 1. Create & Activate Conda Environment
```bash
conda create -n saayam-env python=3.10
conda activate saayam-env
```

### 2. Install Requirements
```bash
pip install -r requirements.txt
```

### 3. Add Your GROQ API Key
Create a `.env` file in the root:
```
GROQ_API_KEY=your_groq_api_key_here
```

---

## ▶️ Run the App
```bash
python app.py
```

Visit: [http://localhost:5000](http://localhost:5000)

---

## ✅ Features
- Category prediction (if not selected)
- LLaMA-generated answers via GROQ
- Responsive UI with category tagging
- Favicon & mobile PWA support
- `.env`-based secure API key loading

---

## 🧪 Run Tests
```bash
pytest
```

Includes:
- Homepage test
- Category prediction test
- AI answer test for each category

---

## 📁 Project Structure
```
groq-flask-app/
├── app.py
├── test_app.py
├── templates/
│   └── index.html
├── static/
│   ├── favicon.ico, .png, .webmanifest...
├── requirements.txt
├── .env
└── .gitignore
```

---