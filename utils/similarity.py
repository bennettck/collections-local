"""
Similarity algorithms for comparing analysis values.

Provides:
- Levenshtein distance for extracted_text comparison
- TF-IDF cosine similarity for headline/summary comparison
"""

from typing import List, Dict, Any
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate Levenshtein distance between two strings using dynamic programming.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Minimum number of single-character edits (insertions, deletions, substitutions)
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)

    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def levenshtein_similarity(s1: str, s2: str) -> float:
    """
    Calculate normalized Levenshtein similarity (0.0 to 1.0).

    Args:
        s1: First string
        s2: Second string

    Returns:
        Similarity score where 1.0 = identical, 0.0 = completely different
    """
    if not s1 and not s2:
        return 1.0

    if not s1 or not s2:
        return 0.0

    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))

    return 1.0 - (distance / max_len)


def compare_text_arrays(arrays: List[List[str]]) -> Dict[str, Any]:
    """
    Compare multiple extracted_text arrays using Levenshtein similarity.

    Args:
        arrays: List of text arrays from different analyses

    Returns:
        Dictionary with:
        - similarity_matrix: 2D list of pairwise similarities
        - highest_agreement: Dict with index and average similarity of best match
    """
    if not arrays:
        return {
            "similarity_matrix": [],
            "highest_agreement": {"index": 0, "avg_similarity": 0.0}
        }

    if len(arrays) == 1:
        return {
            "similarity_matrix": [[1.0]],
            "highest_agreement": {"index": 0, "avg_similarity": 1.0}
        }

    # Flatten arrays to strings for comparison
    flattened = [" ".join(arr) if arr else "" for arr in arrays]

    # Calculate pairwise similarities
    n = len(flattened)
    matrix = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 1.0
            else:
                matrix[i][j] = levenshtein_similarity(flattened[i], flattened[j])

    # Find text with highest average similarity to others
    avg_similarities = []
    for i in range(n):
        avg_sim = sum(matrix[i]) / n
        avg_similarities.append(avg_sim)

    best_index = avg_similarities.index(max(avg_similarities))

    return {
        "similarity_matrix": matrix,
        "highest_agreement": {
            "index": best_index,
            "avg_similarity": avg_similarities[best_index]
        }
    }


def tfidf_similarity(texts: List[str]) -> Dict[str, Any]:
    """
    Compare semantic similarity using TF-IDF + cosine similarity.

    Args:
        texts: List of text strings from different analyses

    Returns:
        Dictionary with:
        - similarity_matrix: 2D list of pairwise cosine similarities
        - highest_agreement: Dict with index and average similarity of best match
    """
    if not texts:
        return {
            "similarity_matrix": [],
            "highest_agreement": {"index": 0, "avg_similarity": 0.0}
        }

    if len(texts) == 1:
        return {
            "similarity_matrix": [[1.0]],
            "highest_agreement": {"index": 0, "avg_similarity": 1.0}
        }

    # Handle empty texts
    processed_texts = [text if text else " " for text in texts]

    # Create TF-IDF vectorizer
    vectorizer = TfidfVectorizer(lowercase=True, stop_words='english')

    try:
        # Fit and transform texts
        tfidf_matrix = vectorizer.fit_transform(processed_texts)

        # Calculate pairwise cosine similarities
        similarity_matrix = cosine_similarity(tfidf_matrix)

        # Convert to list format
        matrix_list = similarity_matrix.tolist()

        # Find text with highest average similarity (closest to centroid)
        n = len(texts)
        avg_similarities = [sum(matrix_list[i]) / n for i in range(n)]
        best_index = avg_similarities.index(max(avg_similarities))

        return {
            "similarity_matrix": matrix_list,
            "highest_agreement": {
                "index": best_index,
                "avg_similarity": avg_similarities[best_index]
            }
        }

    except ValueError:
        # If TF-IDF fails (e.g., all texts are identical or empty), fall back to simple comparison
        n = len(texts)
        matrix = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

        return {
            "similarity_matrix": matrix,
            "highest_agreement": {"index": 0, "avg_similarity": 1.0}
        }
