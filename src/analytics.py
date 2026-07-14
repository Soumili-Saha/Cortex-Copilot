"""
src/analytics.py
Tenant-scoped analytics: loading, time-column detection, filtering, variable
extraction, univariate statistics, and multivariate Isolation-Forest anomaly
detection. Every entrypoint resolves paths ONLY through config.TENANT_PATHS.
"""
from __future__ import annotations
import datetime as _dt
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("analytics")


def load_tenant_df(tenant_display: str) -> pd.DataFrame:
    """Load a tenant's raw readings. TENANT-ISOLATED via config.get_tenant."""
    t = config.get_tenant(tenant_display)
    raw_path: Path = t["raw"]
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw data missing for {tenant_display}: {raw_path}")
    df = pd.read_excel(raw_path)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _classify_time_like(series: pd.Series):
    """Identify whether a column is a full timestamp, a date-only value, or a
    time-only value -- handling BOTH string values and native python
    date/time objects (Excel/pandas commonly reads a "Time"-of-day column as
    raw datetime.time objects, and pd.to_datetime() returns ALL-NaT for those
    if passed naively, which silently made the column invisible before).
    Returns (kind, parsed_or_raw) where kind in {"datetime","date","time",None}.
    """
    sample = series.dropna()
    if sample.empty:
        return None, series
    first = sample.iloc[0]
    if isinstance(first, _dt.datetime):
        return "datetime", pd.to_datetime(series, errors="coerce")
    if isinstance(first, _dt.time):
        return "time", series  # keep raw -- pd.to_datetime can't parse these directly
    if isinstance(first, _dt.date):
        return "date", pd.to_datetime(series, errors="coerce")
    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.notna().mean() > 0.8:
        return "datetime", parsed
    return None, series


def detect_time_column(df: pd.DataFrame) -> str | None:
    """Pick the SINGLE column that best represents the reading timestamp, for
    display/exclusion purposes (e.g. which column to leave out of the numeric
    variable list). A file can have several columns that all match
    TIME_COLUMN_HINTS (e.g. a date-only 'Date' column AND a full
    'DateTime'/'Timestamp' column). Picking the first match by column order
    silently drops the real timestamp, so when there's more than one
    candidate, score each by (a) whether it spans more than one real calendar
    day, then (b) how many distinct times-of-day it contains.

    NOTE: for FILTERING/BOUNDS by an exact date+time window, use
    get_full_timestamp() instead -- this function only ever returns one
    column name, which can't represent a combined Date+Time pair.
    """
    candidates = [col for col in df.columns
                  if str(col).strip().lower() in config.TIME_COLUMN_HINTS]

    if not candidates:
        for col in df.columns:
            try:
                parsed = pd.to_datetime(df[col], errors="coerce")
                if parsed.notna().mean() > 0.8:
                    candidates.append(col)
            except Exception:  # noqa: BLE001
                continue

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    best, best_key = candidates[0], (-1, -1)
    for col in candidates:
        parsed = pd.to_datetime(df[col], errors="coerce").dropna()
        if parsed.empty:
            continue
        n_dates = parsed.dt.date.nunique()
        n_times = parsed.dt.time.nunique()
        key = (n_dates > 1, n_times)
        if key > best_key:
            best, best_key = col, key
    return best


def _time_of_day_series(series: pd.Series) -> pd.Series:
    """Extract just the time-of-day, trustworthy regardless of whether the
    column holds native datetime.time objects (pd.to_datetime can't parse
    these -- returns all-NaT) or plain time strings (pd.to_datetime parses
    them fine, but silently attaches TODAY's real date, which must be
    discarded, never trusted as a real reading date)."""
    def conv(v):
        if isinstance(v, _dt.time):
            return v
        if isinstance(v, _dt.datetime):
            return v.time()
        if pd.isna(v):
            return None
        tt = pd.to_datetime(str(v), errors="coerce")
        return tt.time() if not pd.isna(tt) else None
    return series.map(conv)


def get_full_timestamp(df: pd.DataFrame):
    """Return (label, series) for the most complete real timestamp available --
    combining a separate date-only column with a separate time-only column
    into one true datetime when the file doesn't already have a single column
    with both.

    Columns are classified by MEASURED richness, not by python type, because
    type-checking alone is unreliable: a time-of-day column stored as plain
    strings parses "successfully" via pd.to_datetime but pandas silently
    attaches today's real-world date to every row (a false full-timestamp),
    while the same column stored as native datetime.time objects parses to
    all-NaT instead. Both must be recognised as "time-only, no real date" --
    which measuring actual distinct-dates/distinct-times catches either way,
    regardless of storage type. A date-only column symmetrically only ever
    shows one distinct time-of-day (always midnight).
    """
    hint_cols = [c for c in df.columns
                 if str(c).strip().lower() in config.TIME_COLUMN_HINTS]
    if not hint_cols:
        hint_cols = list(df.columns)

    scored = []
    for c in hint_cols:
        raw = df[c]
        sample = raw.dropna()
        if sample.empty:
            continue
        first = sample.iloc[0]
        if isinstance(first, _dt.time):
            date_parsed = pd.Series(pd.NaT, index=raw.index)  # no real date info here
        else:
            date_parsed = pd.to_datetime(raw, errors="coerce")
        time_of_day = _time_of_day_series(raw)

        valid_dates = date_parsed.dropna()
        n_dates = valid_dates.dt.date.nunique() if not valid_dates.empty else 0
        valid_times = time_of_day.dropna()
        n_times = valid_times.nunique() if not valid_times.empty else 0

        scored.append({
            "col": c, "date_parsed": date_parsed, "time_of_day": time_of_day,
            "n_dates": n_dates, "n_times": n_times,
        })

    if not scored:
        tcol = detect_time_column(df)
        if tcol:
            return tcol, pd.to_datetime(df[tcol], errors="coerce")
        return None, None

    full = [s for s in scored if s["n_dates"] > 1 and s["n_times"] > 1]
    if full:
        best = max(full, key=lambda s: (s["n_dates"], s["n_times"]))
        return best["col"], best["date_parsed"]

    date_like = [s for s in scored if s["n_dates"] > 1]
    time_like = [s for s in scored if s["n_times"] > 1 and s["n_dates"] <= 1]

    if date_like and time_like:
        d = max(date_like, key=lambda s: s["n_dates"])
        t = max(time_like, key=lambda s: s["n_times"])
        if d["col"] != t["col"]:
            dser, tser = d["date_parsed"], t["time_of_day"]

            def _combine(dv, tv):
                if pd.isna(dv) or tv is None:
                    return pd.NaT
                return _dt.datetime.combine(dv.date(), tv)

            combined = pd.Series(
                [_combine(dv, tv) for dv, tv in zip(dser, tser)], index=df.index)
            return f"{d['col']}+{t['col']}", pd.to_datetime(combined)

    if date_like:
        best = max(date_like, key=lambda s: s["n_dates"])
        return best["col"], best["date_parsed"]
    if scored:
        best = max(scored, key=lambda s: (s["n_dates"], s["n_times"]))
        return best["col"], best["date_parsed"]

    tcol = detect_time_column(df)
    if tcol:
        return tcol, pd.to_datetime(df[tcol], errors="coerce")
    return None, None


def numeric_variables(df: pd.DataFrame) -> list[str]:
    """Column headers excluding time/date/timestamp columns."""
    tcol = detect_time_column(df)
    cols = [c for c in df.columns if c != tcol]
    numeric = df[cols].select_dtypes("number").columns.tolist()
    return numeric if numeric else cols


def tenant_time_bounds(tenant_display: str):
    df = load_tenant_df(tenant_display)
    tcol, ts = get_full_timestamp(df)
    if not tcol or ts is None:
        return None, None, None
    return tcol, ts.min(), ts.max()


def resolve_window(tenant_display: str, start, end):
    """SINGLE source of truth for turning a raw (start, end) pick into a
    validated window, used by /api/retrieve, /api/anomaly-report and
    /api/analyze-charts alike so all three see identical results for
    identical input. Previously each endpoint re-implemented this slightly
    differently (retrieve added +1 day, analyze-charts added +23:59:59 and
    then silently RETRIED with a different time-column detector if the
    window came back empty, anomaly-report did neither) which is exactly
    why anomaly-report could 400 or silently drop a day that retrieve
    handled fine. There is no retry/fallback path here: given valid input,
    the window is deterministic.

    Rules:
      - If `end` has no time-of-day component (a date-only pick, i.e. sits
        exactly at midnight), it is treated as inclusive of that whole
        calendar day (end -> 23:59:59 on that date).
      - The resolved (start, end) is then clipped to the tenant's REAL data
        bounds (never past what actually exists) -- this is deterministic
        clamping, not a fallback: the frontend already restricts the date
        pickers to these bounds, so clipping only ever trims an inclusive
        day-extension that would otherwise overshoot the last real reading.
      - Anything actually outside the real bounds (e.g. start before the
        earliest reading) raises ValueError with the real available range.

    Returns (start_ts, end_ts, tmin, tmax).
    """
    _, tmin, tmax = tenant_time_bounds(tenant_display)
    if tmin is None or tmax is None:
        raise ValueError(f"No time-series data available for {tenant_display}.")

    start_ts = pd.to_datetime(start)
    end_ts = pd.to_datetime(end)

    if end_ts.hour == 0 and end_ts.minute == 0 and end_ts.second == 0:
        end_ts = end_ts + pd.Timedelta(hours=23, minutes=59, seconds=59)

    # Clamp (never reject) at the boundaries. The <input type="datetime-local">
    # pickers are MINUTE precision (no seconds field), while real data bounds
    # commonly land mid-minute (e.g. 16:35:19) -- so a user picking exactly the
    # start/end shown to them sends e.g. 16:35:00, which is a few seconds
    # BEFORE the true minimum. Rejecting that as "outside range" is wrong: the
    # frontend already visually restricts the pickers to this window, so
    # anything landing just outside it is a precision artifact, not a real
    # out-of-range request. Clamping is deterministic (not a retry/fallback).
    if start_ts < tmin:
        start_ts = tmin
    if end_ts > tmax:
        end_ts = tmax

    if start_ts > end_ts:
        raise ValueError("Start must be before end.")
    if start_ts > tmax or end_ts < tmin:
        raise ValueError(
            f"Selected range has no overlap with the available data ({tmin} to {tmax}).")

    return start_ts, end_ts, tmin, tmax



def filter_by_range(df: pd.DataFrame, start, end,
                    variables: list[str] | None = None) -> pd.DataFrame:
    tcol, ts = get_full_timestamp(df)
    out = df.copy()
    if tcol and ts is not None:
        ts = ts.reindex(out.index)
        if start is not None:
            out = out[ts >= pd.to_datetime(start)]
            ts = ts.reindex(out.index)
        if end is not None:
            out = out[ts <= pd.to_datetime(end)]
    if variables:
        base_cols = [c for c in tcol.split("+") if c in out.columns] if tcol else []
        keep = base_cols + [v for v in variables if v in out.columns]
        out = out[keep]
    return out.reset_index(drop=True)



def univariate_stats(df: pd.DataFrame) -> dict[str, dict]:
    """Per-column stats + flagged anomalies.

    Anomaly flagging uses a MEDIAN/MAD-based robust z-score, not a
    mean/std z-score. Mean and std are computed from the raw (unfiltered)
    column, so large spikes inflate std -- which raises the effective
    3-sigma bar and can make genuine anomalies fail the test (classic
    masking, where outliers hide each other). The median and MAD (median
    absolute deviation) are resistant to that: a handful of extreme points
    barely move either one, so the threshold stays anchored to the bulk of
    normal readings regardless of how extreme -- or how numerous -- the
    outliers are.

    `robust_std = 1.4826 * MAD` is the standard scale factor that makes MAD
    comparable to a normal distribution's std, so the same ">3" threshold
    used before still means "3 robust standard deviations," just computed
    off a center/spread pair that outliers can't drag around.
    """
    stats = {}
    for col in df.select_dtypes("number").columns:
        s = df[col].dropna()
        if s.empty:
            continue
        mean, std = s.mean(), s.std(ddof=0)

        median = s.median()
        mad = (s - median).abs().median()
        robust_std = 1.4826 * mad
        if robust_std and robust_std > 0:
            z = (s - median) / robust_std
        else:
            # MAD == 0 (e.g. >50% of readings share one value): fall back
            # to the mean/std z-score rather than dividing by zero.
            z = (s - mean) / std if std and std > 0 else pd.Series(0, index=s.index)

        anomaly_mask = z.abs() > 3

        # Calculate the most anomalous data point
        max_z_idx = z.abs().idxmax() if not z.empty else None

        stats[col] = {
            "count": int(s.count()),
            "min": float(s.min()),
            "max": float(s.max()),
            "mean": float(mean),
            "std": float(std),
            "median": float(median),
            "mad": float(mad),
            "robust_std": float(robust_std),
            "n_anomalies": int(anomaly_mask.sum()),
            "anomaly_present": bool(anomaly_mask.sum() > 0),
            "importance": float(z.abs().max()) if len(z) else 0.0,
            "anomaly_index": s.index[anomaly_mask].tolist(),
            "max_anomaly_idx": max_z_idx,
            "max_anomaly_val": float(s.loc[max_z_idx]) if max_z_idx is not None else None,
            "max_anomaly_z": float(z.loc[max_z_idx]) if max_z_idx is not None else None,
        }
    return stats


# Multivariate anomaly detection (Isolation Forest)

def isolation_forest_anomalies(df: pd.DataFrame, contamination: float = 0.03):
    """
    Returns (labels, scores, feature_cols):
      labels: 1 = normal, -1 = anomaly
      scores: anomaly score (higher = more normal)
    """
    from sklearn.ensemble import IsolationForest

    feats = df.select_dtypes("number").dropna(axis=1, how="all")
    feats = feats.fillna(feats.mean(numeric_only=True))
    if feats.shape[0] < 5 or feats.shape[1] == 0:
        return (np.ones(len(df)), np.zeros(len(df)), list(feats.columns))

    model = IsolationForest(
        n_estimators=200, contamination=contamination, random_state=42
    )
    labels = model.fit_predict(feats.values)
    scores = model.decision_function(feats.values)
    return labels, scores, list(feats.columns)


def build_anomaly_table(stats: dict[str, dict]) -> list[dict]:
    """Rows for the report: [Column Name, Anomaly Present (Yes/No), Fact]."""
    rows = []
    for col, s in stats.items():
        present = "Yes" if s["anomaly_present"] else "No"
        if s["anomaly_present"]:
            fact = (f"{s['n_anomalies']} reading(s) exceeded a robust z-score of 3 "
                    f"(median/MAD-based; max deviation {s['importance']:.2f}); "
                    f"range {s['min']:.2f}-{s['max']:.2f}, mean {s['mean']:.2f}.")
        else:
            fact = (f"No robust z-score outliers (median/MAD-based, threshold 3); "
                    f"range {s['min']:.2f}-{s['max']:.2f}, mean {s['mean']:.2f}.")
        rows.append({"column": col, "anomaly_present": present, "fact": fact})
    return rows


def top_univariate_columns(stats: dict[str, dict], n: int = 5) -> list[str]:
    ordered = sorted(stats.items(), key=lambda kv: kv[1]["importance"], reverse=True)
    return [c for c, _ in ordered[:n]]
