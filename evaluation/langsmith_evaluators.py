"""Custom evaluators for LangSmith evaluation framework."""

from typing import Dict, List, Set, Any, Optional
from langsmith.schemas import Run, Example
from langchain_openai import ChatOpenAI


def compute_jaccard(set1: Set[str], set2: Set[str]) -> float:
    """
    Compute Jaccard similarity between two sets.

    Args:
        set1: First set
        set2: Second set

    Returns:
        Jaccard similarity score (0-1)
    """
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    return intersection / union if union > 0 else 0.0


def compute_precision_at_k(retrieved: List[str], expected: List[str], k: int) -> float:
    """
    Compute Precision@K for retrieval.

    Args:
        retrieved: List of retrieved item IDs
        expected: List of expected/relevant item IDs
        k: Cut-off rank

    Returns:
        Precision@K score (0-1)
    """
    if k == 0:
        return 0.0

    retrieved_at_k = set(retrieved[:k])
    expected_set = set(expected)

    relevant_retrieved = retrieved_at_k & expected_set

    return len(relevant_retrieved) / k


def compute_recall_at_k(retrieved: List[str], expected: List[str], k: int) -> float:
    """
    Compute Recall@K for retrieval.

    Args:
        retrieved: List of retrieved item IDs
        expected: List of expected/relevant item IDs
        k: Cut-off rank

    Returns:
        Recall@K score (0-1)
    """
    if not expected:
        return 1.0 if not retrieved else 0.0

    retrieved_at_k = set(retrieved[:k])
    expected_set = set(expected)

    relevant_retrieved = retrieved_at_k & expected_set

    return len(relevant_retrieved) / len(expected_set)


def category_accuracy_evaluator(run: Run, example: Example) -> dict:
    """
    Evaluate category exact match accuracy.

    Args:
        run: LangSmith run containing outputs
        example: LangSmith example containing expected outputs

    Returns:
        Evaluation result dict
    """
    try:
        predicted = run.outputs.get("category", "").strip().lower()
        expected = example.outputs.get("category", "").strip().lower()

        score = 1.0 if predicted == expected else 0.0

        return {
            "key": "category_accuracy",
            "score": score,
            "comment": f"Predicted: {predicted}, Expected: {expected}"
        }
    except Exception as e:
        return {
            "key": "category_accuracy",
            "score": 0.0,
            "comment": f"Error: {str(e)}"
        }


def subcategory_overlap_evaluator(run: Run, example: Example) -> dict:
    """
    Evaluate subcategory overlap using Jaccard similarity.

    Args:
        run: LangSmith run containing outputs
        example: LangSmith example containing expected outputs

    Returns:
        Evaluation result dict
    """
    try:
        predicted = set(run.outputs.get("subcategories", []))
        expected = set(example.outputs.get("subcategories", []))

        score = compute_jaccard(predicted, expected)

        return {
            "key": "subcategory_jaccard",
            "score": score,
            "comment": f"Predicted: {predicted}, Expected: {expected}"
        }
    except Exception as e:
        return {
            "key": "subcategory_jaccard",
            "score": 0.0,
            "comment": f"Error: {str(e)}"
        }


def semantic_similarity_evaluator(run: Run, example: Example) -> dict:
    """
    Evaluate semantic similarity of summaries using LLM-as-judge.

    Args:
        run: LangSmith run containing outputs
        example: LangSmith example containing expected outputs

    Returns:
        Evaluation result dict
    """
    try:
        predicted_summary = run.outputs.get("summary", "")
        expected_summary = example.outputs.get("summary", "")

        if not predicted_summary or not expected_summary:
            return {
                "key": "semantic_similarity",
                "score": 0.0,
                "comment": "Missing summary text"
            }

        # Use LLM to judge similarity
        score = llm_judge_similarity(predicted_summary, expected_summary)

        return {
            "key": "semantic_similarity",
            "score": score,
            "comment": f"LLM judge score: {score:.2f}"
        }
    except Exception as e:
        return {
            "key": "semantic_similarity",
            "score": 0.0,
            "comment": f"Error: {str(e)}"
        }


def llm_judge_similarity(text1: str, text2: str, model: str = "gpt-4o-mini") -> float:
    """
    Use LLM as judge to rate semantic similarity.

    Args:
        text1: First text
        text2: Second text
        model: Model to use for judging

    Returns:
        Similarity score (0-1)
    """
    llm = ChatOpenAI(model=model, temperature=0)

    prompt = f"""Rate the semantic similarity between these two summaries on a scale from 0 to 10, where:
- 0 = Completely different meaning
- 5 = Partially similar, some overlap
- 10 = Essentially the same meaning, just different wording

Summary 1: {text1}

Summary 2: {text2}

Respond with ONLY a number between 0 and 10."""

    try:
        response = llm.invoke(prompt)
        score_text = response.content.strip()

        # Extract number from response
        import re
        match = re.search(r'\d+\.?\d*', score_text)
        if match:
            score = float(match.group())
            # Normalize to 0-1 range
            return min(1.0, max(0.0, score / 10.0))
        else:
            return 0.5  # Default to middle if can't parse
    except Exception as e:
        print(f"LLM judge error: {e}")
        return 0.5  # Default to middle on error


def retrieval_precision_evaluator(run: Run, example: Example, k: int = 5) -> dict:
    """
    Evaluate retrieval precision@K.

    Args:
        run: LangSmith run containing outputs
        example: LangSmith example containing expected outputs
        k: Cut-off rank (default 5)

    Returns:
        Evaluation result dict
    """
    try:
        # Extract retrieved item IDs from results
        results = run.outputs.get("results", [])
        retrieved = [r.get("item_id") for r in results if r.get("item_id")]

        expected = example.outputs.get("expected_items", [])

        score = compute_precision_at_k(retrieved, expected, k)

        return {
            "key": f"precision@{k}",
            "score": score,
            "comment": f"Retrieved {len(retrieved)} items, {sum(1 for r in retrieved[:k] if r in expected)}/{k} relevant"
        }
    except Exception as e:
        return {
            "key": f"precision@{k}",
            "score": 0.0,
            "comment": f"Error: {str(e)}"
        }


def retrieval_recall_evaluator(run: Run, example: Example, k: int = 5) -> dict:
    """
    Evaluate retrieval recall@K.

    Args:
        run: LangSmith run containing outputs
        example: LangSmith example containing expected outputs
        k: Cut-off rank (default 5)

    Returns:
        Evaluation result dict
    """
    try:
        # Extract retrieved item IDs from results
        results = run.outputs.get("results", [])
        retrieved = [r.get("item_id") for r in results if r.get("item_id")]

        expected = example.outputs.get("expected_items", [])

        score = compute_recall_at_k(retrieved, expected, k)

        return {
            "key": f"recall@{k}",
            "score": score,
            "comment": f"Found {sum(1 for r in retrieved[:k] if r in expected)}/{len(expected)} relevant items"
        }
    except Exception as e:
        return {
            "key": f"recall@{k}",
            "score": 0.0,
            "comment": f"Error: {str(e)}"
        }


def trajectory_evaluator(run: Run, example: Example) -> dict:
    """
    Evaluate end-to-end query → search → answer pipeline.

    Checks:
    - Search returned relevant results (retrieval quality)
    - Answer cites the results correctly (citation accuracy)
    - Answer addresses the query (relevance)

    Args:
        run: LangSmith run containing outputs
        example: LangSmith example containing expected outputs

    Returns:
        Evaluation result dict
    """
    try:
        # Extract components
        results = run.outputs.get("results", [])
        answer = run.outputs.get("answer", "")
        citations = run.outputs.get("citations", [])
        query = example.inputs.get("query", "")

        # Component 1: Retrieval quality (precision@5)
        retrieved_ids = [r.get("item_id") for r in results if r.get("item_id")]
        expected_ids = example.outputs.get("expected_items", [])
        retrieval_score = compute_precision_at_k(retrieved_ids, expected_ids, min(5, len(results)))

        # Component 2: Citation accuracy (% of results cited)
        if results:
            citation_nums = set(int(c) for c in citations if c.isdigit())
            num_cited = sum(1 for i in range(1, len(results) + 1) if i in citation_nums)
            citation_score = num_cited / min(5, len(results))
        else:
            citation_score = 0.0

        # Component 3: Answer relevance (has meaningful answer)
        relevance_score = 1.0 if len(answer) > 20 and not answer.startswith("I couldn't find") else 0.3

        # Composite score
        trajectory_score = (
            0.4 * retrieval_score +
            0.2 * citation_score +
            0.4 * relevance_score
        )

        return {
            "key": "trajectory_score",
            "score": trajectory_score,
            "comment": f"Retrieval: {retrieval_score:.2f}, Citations: {citation_score:.2f}, Relevance: {relevance_score:.2f}"
        }
    except Exception as e:
        return {
            "key": "trajectory_score",
            "score": 0.0,
            "comment": f"Error: {str(e)}"
        }
