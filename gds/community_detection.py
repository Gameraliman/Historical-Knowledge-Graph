from __future__ import annotations

import pandas as pd

from gds.algorithms import NODE_COLS, timed

ALGORITHMS = {"Louvain": "gds.louvain", "Leiden": "gds.leiden"}


def run_communities(projection: str, algorithm: str, limit: int = 200000) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(نودها همراه communityId، خلاصه‌ی اندازه‌ی جامعه‌ها). این الگوریتم‌ها به Projection بدون‌جهت نیاز دارند."""
    proc = ALGORITHMS[algorithm]
    nodes = timed(
        f"{algorithm} Community Detection", projection,
        f"CALL {proc}.stream($g) YIELD nodeId, communityId WITH gds.util.asNode(nodeId) AS n, communityId "
        f"RETURN {NODE_COLS}, communityId AS community LIMIT $limit",
        {"g": projection, "limit": limit})
    if nodes.empty:
        return nodes, pd.DataFrame(columns=["community", "nodes"])
    summary = (nodes.groupby("community").size().reset_index(name="nodes")
               .sort_values("nodes", ascending=False).reset_index(drop=True))
    return nodes, summary
