"""استخراج سال از متن زمان (شمسی/قمری/میلادی) و رسم Timeline با Plotly."""
from __future__ import annotations

import hashlib
import re

import pandas as pd
import plotly.graph_objects as go

from utils.formatting import to_latin_digits

_PALETTE = ["#4C8EDA", "#F16667", "#57C7A5", "#F79767", "#C990C0", "#FFC454", "#8DCC93", "#DA7194"]


def parse_year(text: str) -> tuple[int | None, str]:
    """(سال میلادیِ تقریبی، تقویم تشخیص‌داده‌شده). اگر سالی پیدا نشود (None, '')."""
    t = to_latin_digits(text or "")
    nums = [int(x) for x in re.findall(r"(?<!\d)\d{3,4}(?!\d)", t)]
    nums = [n for n in nums if 100 <= n <= 2200]
    if not nums:
        return None, ""
    y = nums[0]
    if re.search(r"(قبل|پیش)\s*از\s*میلاد", t):
        return -y, "میلادی"
    if re.search(r"میلادی|\bAD\b", t) or (y >= 1500):
        return y, "میلادی"
    if re.search(r"قمری|هجری(?!\s*شمسی)|(?<!\S)ق\.|\sق$", t):
        return round(y * 0.970229 + 621.57), "قمری"
    return y + 621, "شمسی"


def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    out = []
    for r in rows:
        g, cal = parse_year(r["time_text"])
        if g is None:
            continue
        out.append({**r, "g_year": g, "calendar": cal, "j_year": g - 621})
    return pd.DataFrame(out)


def make_figure(df: pd.DataFrame, calendar: str = "شمسی") -> go.Figure:
    """هر نقطه یک (رویداد، زمان) است. محور Y برای جلوگیری از هم‌پوشانی به‌صورت پایدار پراکنده می‌شود."""
    xcol = "j_year" if calendar == "شمسی" else "g_year"
    d = df.copy()
    d["lane"] = d["id"].map(lambda i: int(hashlib.md5(i.encode()).hexdigest()[:4], 16) % 40)
    top = d["relation"].value_counts().index[:8].tolist()
    d["group"] = d["relation"].where(d["relation"].isin(top), "سایر")
    fig = go.Figure()
    for gi, (name, sub) in enumerate(d.groupby("group")):
        fig.add_trace(go.Scatter(
            x=sub[xcol], y=sub["lane"], mode="markers", name=str(name),
            marker=dict(size=10, color=_PALETTE[gi % len(_PALETTE)], line=dict(width=1, color="#fff")),
            customdata=sub[["id", "name", "time_text"]].values,
            hovertemplate="<b>%{customdata[1]}</b><br>زمان: %{customdata[2]}<br>سال: %{x}<extra>" + str(name) + "</extra>"))
    fig.update_layout(
        font=dict(family="Vazirmatn, Tahoma, sans-serif", size=13), height=520, hovermode="closest",
        margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="#ffffff", legend=dict(title="نوع رابطه‌ی زمانی"),
        xaxis=dict(title=f"سال ({calendar})", gridcolor="#eef2f6", rangeslider=dict(visible=True)),
        yaxis=dict(visible=False))
    return fig
