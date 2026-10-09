"""نمودارهای Plotly (فونت فارسی، رنگ‌ها از config)."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import settings

_FONT = dict(family="Vazirmatn, Tahoma, sans-serif", size=13)


def _style(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(font=_FONT, height=height, margin=dict(l=10, r=10, t=50, b=10),
                      plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", title_x=0.5)
    fig.update_xaxes(gridcolor="#eef2f6")
    fig.update_yaxes(gridcolor="#eef2f6")
    return fig


def bar_by_type(df: pd.DataFrame, title: str) -> go.Figure:
    df = df.copy()
    df["color"] = df["type"].map(settings.color_of)
    fig = go.Figure(go.Bar(x=df["type"].map(lambda t: settings.NODE_TYPE_FA.get(t, t)), y=df["count"],
                           marker_color=df["color"], text=df["count"], textposition="outside"))
    fig.update_layout(title=title)
    return _style(fig)


def hbar(df: pd.DataFrame, label_col: str, value_col: str, title: str, color: str = "#018bff",
         height: int | None = None) -> go.Figure:
    d = df.iloc[::-1]
    fig = go.Figure(go.Bar(x=d[value_col], y=d[label_col], orientation="h", marker_color=color,
                           text=d[value_col].map(lambda v: f"{v:.4g}" if isinstance(v, float) else f"{v:,}"),
                           textposition="outside"))
    fig.update_layout(title=title, yaxis=dict(automargin=True))
    return _style(fig, height or max(320, 26 * len(d) + 110))


def hbar_typed(df: pd.DataFrame, label_col: str, value_col: str, type_col: str, title: str) -> go.Figure:
    d = df.iloc[::-1]
    fig = go.Figure(go.Bar(x=d[value_col], y=d[label_col], orientation="h",
                           marker_color=d[type_col].map(settings.color_of),
                           text=d[value_col].map(lambda v: f"{v:.4g}" if isinstance(v, float) else f"{v:,}"),
                           textposition="outside"))
    fig.update_layout(title=title, yaxis=dict(automargin=True))
    return _style(fig, max(320, 26 * len(d) + 110))


def community_sizes(df: pd.DataFrame, title: str = "اندازه‌ی جامعه‌ها (۲۰ جامعه‌ی بزرگ)") -> go.Figure:
    d = df.head(20).copy()
    d["community"] = d["community"].astype(str)
    fig = px.bar(d, x="community", y="nodes", color="community", color_discrete_sequence=settings.COMMUNITY_PALETTE,
                 title=title, labels={"community": "جامعه", "nodes": "تعداد نود"})
    fig.update_layout(showlegend=False)
    return _style(fig)
