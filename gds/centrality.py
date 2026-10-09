from __future__ import annotations

import pandas as pd

from gds.algorithms import NODE_COLS, timed

ALGORITHMS = {"Degree": "gds.degree", "Betweenness": "gds.betweenness", "Closeness": "gds.closeness"}


def run_centrality(projection: str, algorithm: str, top_k: int = 20) -> pd.DataFrame:
    proc = ALGORITHMS[algorithm]  # فقط از لیست سفید؛ ورودی کاربر هرگز در Query قرار نمی‌گیرد
    df = timed(
        f"{algorithm} Centrality", projection,
        f"CALL {proc}.stream($g) YIELD nodeId, score WITH gds.util.asNode(nodeId) AS n, score "
        f"ORDER BY score DESC LIMIT $k RETURN {NODE_COLS}, score",
        {"g": projection, "k": top_k})
    if not df.empty:
        df.insert(0, "rank", range(1, len(df) + 1))
    return df
