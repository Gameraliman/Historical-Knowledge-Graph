"""Graph Node Similarity: شباهت ساختاری نودها بر اساس همسایه‌های مشترک (این الگوریتم Entity Resolution نیست)."""
from __future__ import annotations

import pandas as pd

from gds.algorithms import timed


def run_similarity(projection: str, top_k: int = 10, cutoff: float = 0.5, top_n: int = 200) -> pd.DataFrame:
    return timed(
        "Graph Node Similarity", projection,
        "CALL gds.nodeSimilarity.stream($g, {topK: $k, similarityCutoff: $c, topN: $n}) "
        "YIELD node1, node2, similarity "
        "WITH gds.util.asNode(node1) AS a, gds.util.asNode(node2) AS b, similarity "
        "RETURN elementId(a) AS id1, a.name AS node1, labels(a)[0] AS type1, "
        "elementId(b) AS id2, b.name AS node2, labels(b)[0] AS type2, similarity "
        "ORDER BY similarity DESC",
        {"g": projection, "k": top_k, "c": cutoff, "n": top_n})
