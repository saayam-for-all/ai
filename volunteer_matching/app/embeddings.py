from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def get_embedding(text):
    if not text:
        return np.zeros(384)
    return model.encode(text, convert_to_numpy=True)

def cosine_similarity(a, b):
    if np.linalg.norm(a)==0 or np.linalg.norm(b)==0:
        return 0
    return np.dot(a, b)/(np.linalg.norm(a)*np.linalg.norm(b))
