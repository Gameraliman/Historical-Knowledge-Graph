from __future__ import annotations

import pandas as pd

from gds.algorithms import NODE_COLS, timed


def run_pagerank(projection: str, iterations: int = 20, damping: float = 0.85, top_k: int = 1000) -> pd.DataFrame:
    df = timed(
        "PageRank", projection,
        f"CALL gds.pageRank.stream($g, {{maxIterations: $it, dampingFactor: $d}}) YIELD nodeId, score "
        f"WITH gds.util.asNode(nodeId) AS n, score ORDER BY score DESC LIMIT $k "
        f"RETURN {NODE_COLS}, score",
        {"g": projection, "it": iterations, "d": damping, "k": top_k})
    if not df.empty:
        df.insert(0, "rank", range(1, len(df) + 1))
    return df
