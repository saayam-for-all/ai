from sklearn.feature_extraction.text import TfidfVectorizer

def prepare_tfidf(vol_texts, req_text):
    vectorizer = TfidfVectorizer(stop_words="english")
    docs = vol_texts + [req_text]

    tfidf_matrix = vectorizer.fit_transform(docs)
    return tfidf_matrix[:-1], tfidf_matrix[-1]
