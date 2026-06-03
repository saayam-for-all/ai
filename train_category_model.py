import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

# Load dataset
df = pd.read_csv("full_category_training_dataset.csv")

# Combine subject + description
df["text"] = df["subject"].fillna("") + " " + df["description"].fillna("")

# Features and labels
X = df["text"]
y = df["category"]

# Train-test split
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y
)

# Pipeline
model = Pipeline([
    ("tfidf", TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 3),
        max_features=10000,
        sublinear_tf=True
    )),
    ("classifier", LogisticRegression(max_iter=1000))
])

# Train
model.fit(X_train, y_train)

# Predict
y_pred = model.predict(X_test)

# Accuracy
accuracy = accuracy_score(y_test, y_pred)

print("Accuracy:", round(accuracy * 100, 2), "%")

print("\nClassification Report:")
print(classification_report(y_test, y_pred))

print("\nConfusion Matrix:")
print(confusion_matrix(y_test, y_pred))

# Save model
joblib.dump(model, "category_model.pkl")

print("\nModel saved as category_model.pkl")

# Manual real-world tests
tests = [
    "I want stylish hoodies",
    "Need software engineering internship",
    "My knee hurts while running",
    "Looking for cheap hotels",
    "Need help opening bank account",
    "Best basketball shoes",
    "I need a therapist for depression"
]

print("\nManual Predictions:")
for t in tests:
    pred = model.predict([t])[0]
    print(f"{t} --> {pred}")