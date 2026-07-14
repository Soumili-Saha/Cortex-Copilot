"""
src/insights.py
Quick time-series analysis for a chosen set of variables over a time range.

Public API:
  analyze_variables(tenant, variables, start, end) -> dict
  facts_to_text(result)                            -> str  (LLM-groundable facts)

Computes per variable: min, max, average, std (deviation), with timestamps,
plus time-based insights: highest/lowest-average day, busiest/lightest ISO week,
weekday vs weekend average, and peak / lowest hour-of-day.
"""
from __future__ import annotations

import pandas as pd

from src import analytics


def _pick_time_col(df: pd.DataFrame):
    for c in df.columns:
        if c.lower().replace("_", "") == "datetime":
            return c
    return analytics.detect_time_column(df)


def analyze_variables(tenant: str, variables: list[str] | None,
                      start=None, end=None) -> dict:
    df = analytics.load_tenant_df(tenant)
    tcol = _pick_time_col(df)
    if tcol:
        df[tcol] = pd.to_datetime(df[tcol], errors="coerce")
        if start is not None:
            df = df[df[tcol] >= pd.to_datetime(start)]
        if end is not None:
            end_ts = pd.to_datetime(end)
            # if end has no time-of-day (midnight), make it inclusive of the whole day
            if end_ts.hour == 0 and end_ts.minute == 0 and end_ts.second == 0:
                end_ts = end_ts + pd.Timedelta(hours=23, minutes=59, seconds=59)
            df = df[df[tcol] <= end_ts]
        df = df.dropna(subset=[tcol]).sort_values(tcol).reset_index(drop=True)

    if not variables:
        variables = analytics.numeric_variables(df)[:5]

    out = {"start": str(start), "end": str(end),
           "rows": int(len(df)), "variables": {}}

    for v in variables:
        if v not in df.columns:
            continue
        s = pd.to_numeric(df[v], errors="coerce")
        sd = s.dropna()
        if sd.empty:
            continue
        info = {"min": float(sd.min()), "max": float(sd.max()),
                "mean": float(sd.mean()), "std": float(sd.std(ddof=0))}

        if tcol:
            info["max_time"] = str(df.loc[sd.idxmax(), tcol])
            info["min_time"] = str(df.loc[sd.idxmin(), tcol])
            tmp = pd.DataFrame({"t": df[tcol], "v": s}).dropna()
            tmp["date"] = tmp["t"].dt.date
          
            def _week_label(ts):
                return f"week {((ts.day - 1) // 7) + 1} of {ts.strftime('%B %Y')}"
            tmp["wlabel"] = tmp["t"].apply(_week_label)
            tmp["dow"] = tmp["t"].dt.dayofweek
            tmp["hour"] = tmp["t"].dt.hour
            tmp["weekend"] = tmp["dow"] >= 5

            daily = tmp.groupby("date")["v"].mean()
            if len(daily):
                info["peak_day"] = str(daily.idxmax())
                info["peak_day_avg"] = float(daily.max())
                info["low_day"] = str(daily.idxmin())
                info["low_day_avg"] = float(daily.min())

            weekly = tmp.groupby("wlabel")["v"].mean()
            if len(weekly) > 1:
                info["busy_week"] = str(weekly.idxmax())
                info["busy_week_avg"] = float(weekly.max())
                info["light_week"] = str(weekly.idxmin())
                info["light_week_avg"] = float(weekly.min())

            wd = tmp[~tmp["weekend"]]["v"].mean()
            we = tmp[tmp["weekend"]]["v"].mean()
            if pd.notna(wd):
                info["weekday_avg"] = float(wd)
            if pd.notna(we):
                info["weekend_avg"] = float(we)

            hourly = tmp.groupby("hour")["v"].mean()
            if len(hourly):
                info["peak_hour"] = int(hourly.idxmax())
                info["peak_hour_avg"] = float(hourly.max())
                info["low_hour"] = int(hourly.idxmin())
                info["low_hour_avg"] = float(hourly.min())

        out["variables"][v] = info
    return out


def facts_to_text(result: dict) -> str:
    lines = [f"Time range analysed: {result['start']} to {result['end']}.",
             f"Rows in range: {result['rows']}."]
    if result["rows"] == 0:
        lines.append("No readings fall in this range.")
        return "\n".join(lines)

    for v, i in result["variables"].items():
        lines.append(f"\n[{v}]")
        lines.append(f"min={i['min']:.2f}, max={i['max']:.2f}, "
                     f"average={i['mean']:.2f}, std/deviation={i['std']:.2f}.")
        if "max_time" in i:
            lines.append(f"peak {i['max']:.2f} at {i['max_time']}; "
                         f"lowest {i['min']:.2f} at {i['min_time']}.")
        if "peak_day" in i:
            lines.append(f"highest-average day {i['peak_day']} (avg {i['peak_day_avg']:.2f}); "
                         f"lowest-average day {i['low_day']} (avg {i['low_day_avg']:.2f}).")
        if "busy_week" in i:
            lines.append(f"busiest week: {i['busy_week']} (avg {i['busy_week_avg']:.2f}); "
                         f"lightest week: {i['light_week']} (avg {i['light_week_avg']:.2f}).")
        if "weekday_avg" in i and "weekend_avg" in i:
            lines.append(f"weekday average {i['weekday_avg']:.2f} vs "
                         f"weekend average {i['weekend_avg']:.2f}.")
        if "peak_hour" in i:
            lines.append(f"peak hour ~{i['peak_hour']:02d}:00 (avg {i['peak_hour_avg']:.2f}); "
                         f"quietest hour ~{i['low_hour']:02d}:00 (avg {i['low_hour_avg']:.2f}).")
    return "\n".join(lines)
