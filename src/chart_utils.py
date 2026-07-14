"""
src/chart_utils.py
Shared matplotlib helpers.

style_time_axis(ax) fixes the overlapping-date-label problem in the anomaly
report and auto-adjusts tick spacing/format to whatever time span is plotted
(hours -> days -> months) instead of a fixed guess -- a 2-hour window and a
6-month window each get sensibly-spaced, non-overlapping labels.

phase_group_chart / tod_bar_chart render the "Analyze" side-panel charts and
return a data: URL PNG so the frontend can drop them straight into an <img>.
"""
from __future__ import annotations
import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

PHASE_COLORS = ["#c0392b", "#d4a017", "#1f6f8b"]   # R, Y, B
GREEN_DARK = "#0b5943"
GREEN = "#0f6b52"
GRID_COLOR = "#e6e6e2"
AXIS_COLOR = "#9aa19c"
TEXT_MUTED = "#6b7570"


def _style_axes(ax, y_grid=True):
    """Clean, card-style axes shared by every chart: no top/right border,
    soft dashed gridlines, muted tick labels -- readable at a glance instead
    of default matplotlib chrome."""
    ax.set_facecolor("#ffffff")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(AXIS_COLOR)
    ax.spines["bottom"].set_color(AXIS_COLOR)
    ax.tick_params(colors=TEXT_MUTED, labelsize=9)
    if y_grid:
        ax.grid(axis="y", color=GRID_COLOR, linewidth=0.9, linestyle="--", alpha=0.9)
    ax.set_axisbelow(True)


def _annotate_peak(ax, x, y, color, unit=""):
    """Mark the single highest point on a series with a small dot + value
    label, so the reader doesn't have to eyeball the peak off the axis."""
    yv = pd.Series(list(y))
    if yv.dropna().empty:
        return
    idx = yv.idxmax()
    xv = list(x)[idx]
    peak = yv.iloc[idx]
    ax.scatter([xv], [peak], color=color, s=26, zorder=5, edgecolor="white", linewidth=0.8)
    ax.annotate(f"{peak:,.1f}{unit}", (xv, peak), textcoords="offset points",
               xytext=(0, 8), ha="center", fontsize=8, color=color, fontweight="bold")


def _pick_resample_rule(span: pd.Timedelta, n_points: int) -> str | None:
    """Choose a pandas resample rule from the ACTUAL selected span (and how
    many raw readings sit in it), not a hardcoded guess. Short windows plot
    every raw reading (rule=None); as the window grows, each x-axis tick
    represents the MEAN of a widening bucket, so a 2-hour pick still shows
    every reading while a 6-month pick shows sensible per-day/week averages
    instead of an unreadable smear of points. Also densifies (widens the
    bucket) when there are simply too many raw points to render legibly,
    even within a short span (very high sampling-rate data)."""
    days = span.total_seconds() / 86400
    if days <= 1 and n_points <= 400:
        return None
    if days <= 2:
        return "5min"
    if days <= 7:
        return "30min"
    if days <= 21:
        return "2h"
    if days <= 60:
        return "6h"
    if days <= 180:
        return "1D"
    if days <= 730:
        return "1W"
    return "1MS"


def resample_for_plot(x, series: dict[str, pd.Series]) -> tuple[object, dict[str, pd.Series]]:
    """Auto-adjust x-axis granularity: aggregate (mean) each series into
    buckets sized to the actual selected time span, so long ranges render
    fast and legible instead of a solid smear, while short ranges are left
    untouched at full resolution. Returns (x, series) unchanged if resampling
    isn't applicable (no usable datetime x-axis, or too few points)."""
    try:
        x_ts = pd.to_datetime(pd.Series(list(x)))
    except Exception:  # noqa: BLE001
        return x, series
    valid = x_ts.dropna()
    if valid.empty:
        return x, series
    span = valid.max() - valid.min()
    rule = _pick_resample_rule(span, len(valid))
    if rule is None:
        return x, series

    frame = pd.DataFrame({"__t": x_ts.values})
    for name, s in series.items():
        frame[name] = pd.Series(list(s)).values
    frame = frame.dropna(subset=["__t"]).set_index("__t")
    resampled = frame.resample(rule).mean().dropna(how="all")
    new_x = resampled.index
    new_series = {name: resampled[name] for name in series}
    return new_x, new_series


def style_time_axis(ax):
    """Auto-pick tick spacing + a compact label format based on the actual
    plotted time span, and rotate labels so they never overlap -- replaces
    manually-guessed/fixed tick logic that broke on both very short and very
    long selected ranges."""
    locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    for label in ax.get_xticklabels():
        label.set_rotation(30)
        label.set_ha("right")


def _fig_to_data_url(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def phase_group_chart(x, series: dict[str, pd.Series], title: str, ylabel: str) -> str:
    """One chart, up to 3 lines (R/Y/B phases of the same quantity), styled
    as a readable dashboard card: soft fill under each line, the peak of
    each series called out with a dot + value, a stats subtitle (avg per
    series), and an auto time axis. x-axis granularity auto-adapts to the
    selected span: short windows plot every raw reading, long windows plot
    bucket AVERAGES (mean) so the chart stays fast and legible instead of a
    solid smear of points."""
    plot_x, plot_series = resample_for_plot(x, series)
    fig, ax = plt.subplots(figsize=(8.4, 4.0))

    subtitle_parts = []
    for (label, s), color in zip(plot_series.items(), PHASE_COLORS):
        yv = pd.Series(list(s))
        ax.plot(plot_x, yv, linewidth=1.8, label=label, color=color, solid_capstyle="round")
        ax.fill_between(plot_x, yv, color=color, alpha=0.07)
        _annotate_peak(ax, plot_x, yv, color)
        if yv.dropna().size:
            subtitle_parts.append(f"{label} avg {yv.mean():,.1f}")

    ax.set_title(title, fontsize=13, color=GREEN_DARK, fontweight="bold", pad=22)
    if subtitle_parts:
        ax.text(0, 1.03, "  •  ".join(subtitle_parts), transform=ax.transAxes,
               fontsize=9, color=TEXT_MUTED, va="bottom")
    ax.set_ylabel(ylabel, fontsize=10, color=TEXT_MUTED)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=max(1, len(plot_series)),
              fontsize=9, frameon=False)
    _style_axes(ax)
    style_time_axis(ax)
    fig.tight_layout()
    return _fig_to_data_url(fig)


def tod_bar_chart(peak: float, normal: float, offpeak: float, title: str) -> str:
    """Peak / Normal / Off-peak energy (kVAh) for the selected window,
    styled as a readable dashboard card."""
    fig, ax = plt.subplots(figsize=(8.4, 4.0))
    labels = ["Peak", "Normal", "Off-peak"]
    vals = [peak, normal, offpeak]
    colors = ["#c0392b", GREEN, "#1f6f8b"]
    bars = ax.bar(labels, vals, color=colors, width=0.45, zorder=3)
    for rect, v in zip(bars, vals):
        ax.text(rect.get_x() + rect.get_width() / 2, v, f"{v:,.1f}",
               ha="center", va="bottom", fontsize=10, fontweight="bold", color=GREEN_DARK)
    ax.set_ylabel("kVAh", fontsize=10, color=TEXT_MUTED)
    ax.set_title(title, fontsize=13, color=GREEN_DARK, fontweight="bold", pad=16)
    total = sum(vals) or 1
    subtitle = "  •  ".join(f"{l} {v/total*100:.0f}%" for l, v in zip(labels, vals))
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=TEXT_MUTED, va="bottom")
    _style_axes(ax)
    fig.tight_layout()
    return _fig_to_data_url(fig)
