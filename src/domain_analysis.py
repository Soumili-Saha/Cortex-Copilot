"""
src/domain_analysis.py
Dedicated, deterministic analyzers for the question categories.
The LLM only narrates these computed facts -- it never produces the numbers.

Public functions:
  analyze_thd(tenant, start, end)          -> THD values vs IEEE-519 limits
  analyze_pf(tenant, start, end)           -> power-factor trend / drop analysis
  consumption_advice(tenant, start, end)   -> load-profile-tied saving levers
  compute_bill(tenant, start, end)         -> tariff-based bill + component split
  bill_delta(tenant, start, end)           -> this-period bill vs previous equal period

Generic over columns: uses name-matching so it works on any similar schema.
Tariff is read from knowledge_base/tariff.md (parsed once); no hardcoded rates
beyond what that file states.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src import analytics, config

# IEEE-519 style limits 
THD_V_LIMIT = 5.0    
THD_I_LIMIT = 8.0    



def _pick_time_col(df):
    for c in df.columns:
        if c.lower().replace("_", "") == "datetime":
            return c
    return analytics.detect_time_column(df)


def _load_range(tenant, start, end):
    df = analytics.load_tenant_df(tenant)
    tcol = _pick_time_col(df)
    if tcol:
        df[tcol] = pd.to_datetime(df[tcol], errors="coerce")
        if start is not None:
            df = df[df[tcol] >= pd.to_datetime(start)]
        if end is not None:
            end_ts = pd.to_datetime(end)
            if end_ts.hour == 0 and end_ts.minute == 0 and end_ts.second == 0:
                end_ts = end_ts + pd.Timedelta(hours=23, minutes=59, seconds=59)
            df = df[df[tcol] <= end_ts]
        df = df.dropna(subset=[tcol]).sort_values(tcol).reset_index(drop=True)
    return df, tcol


def _cols_like(df, *needles):
    out = []
    for c in df.columns:
        cl = c.lower()
        if any(n in cl for n in needles):
            out.append(c)
    return out



def analyze_thd(tenant, start, end) -> dict:
    df, tcol = _load_range(tenant, start, end)
    v_cols = [c for c in _cols_like(df, "thd") if "v_" in c.lower() or "_v_" in c.lower()
              or c.lower().startswith("v")]
    i_cols = [c for c in _cols_like(df, "thd") if "i_" in c.lower() or c.lower().startswith("i")]

    all_thd = _cols_like(df, "thd")
    if not v_cols and not i_cols:
        v_cols = [c for c in all_thd if "v" in c.lower()]
        i_cols = [c for c in all_thd if "i" in c.lower()]

    def _summ(cols, limit):
        rows = []
        for c in cols:
            s = pd.to_numeric(df[c], errors="coerce").dropna()
            s = s[s >= 0]  
            if s.empty:
                continue
            over = (s > limit).mean() * 100
            rows.append({"col": c, "avg": float(s.mean()), "max": float(s.max()),
                         "pct_over": float(over), "limit": limit})
        return rows

    v = _summ(v_cols, THD_V_LIMIT)
    i = _summ(i_cols, THD_I_LIMIT)
    return {"rows": len(df), "voltage_thd": v, "current_thd": i,
            "v_limit": THD_V_LIMIT, "i_limit": THD_I_LIMIT}


def thd_text(res) -> str:
    lines = [f"Rows analysed: {res['rows']}.",
             f"IEEE-519 style limits: voltage THD {res['v_limit']}%, current THD {res['i_limit']}%."]
    for r in res["voltage_thd"]:
        lines.append(f"Voltage THD [{r['col']}]: average {r['avg']:.2f}%, max {r['max']:.2f}%, "
                     f"exceeded {r['limit']}% limit in {r['pct_over']:.1f}% of readings.")
    for r in res["current_thd"]:
        lines.append(f"Current THD [{r['col']}]: average {r['avg']:.2f}%, max {r['max']:.2f}%, "
                     f"exceeded {r['limit']}% limit in {r['pct_over']:.1f}% of readings.")
    if not res["voltage_thd"] and not res["current_thd"]:
        lines.append("No THD columns found in the data for this range.")
    return "\n".join(lines)


def analyze_pf(tenant, start, end) -> dict:
    """Power factor per spec:
       - instantaneous PF = Watts_Total / VA_Total  (exclude rows where I_Total < 1 A)
       - weighted period PF = (dWh) / (dVAh)  from cumulative registers
    """
    df, tcol = _load_range(tenant, start, end)
    out = {"rows": len(df), "pf": []}

    w = next((c for c in df.columns if c.lower() == "watts_total"), None)
    va = next((c for c in df.columns if c.lower() == "va_total"), None)
    itot = next((c for c in df.columns if c.lower() == "i_total"), None)
    wh = next((c for c in df.columns if c.lower() == "wh_received"), None)
    vah = next((c for c in df.columns if c.lower() == "vah_received"), None)

    info = {"col": "PF (spec)"}
    # instantaneous PF series with noise filter I_Total < 1 A
    if w and va:
        wv = pd.to_numeric(df[w], errors="coerce")
        vv = pd.to_numeric(df[va], errors="coerce")
        inst = (wv / vv).replace([float("inf"), float("-inf")], pd.NA)
        if itot:
            iv = pd.to_numeric(df[itot], errors="coerce")
            inst = inst[iv >= 1.0]
        inst = inst.dropna()
        inst = inst[(inst > -1.5) & (inst < 1.5)]  # guard against sensor spikes
        if not inst.empty:
            mag = inst.abs()
            info["avg"] = float(inst.mean())
            info["avg_mag"] = float(mag.mean())
            info["min"] = float(inst.min())
            info["pct_below_090"] = float((mag < 0.90).mean() * 100)
            info["negative_share"] = float((inst < 0).mean() * 100)
            if tcol and len(inst) > 5:
                idx = inst.index
                tmp = pd.DataFrame({"t": df.loc[idx, tcol], "v": mag}).dropna()
                daily = tmp.groupby(tmp["t"].dt.date)["v"].mean()
                if len(daily) > 1:
                    info["worst_day"] = str(daily.idxmin()); info["worst_day_avg"] = float(daily.min())
                    info["best_day"] = str(daily.idxmax()); info["best_day_avg"] = float(daily.max())
                info["lowest_at"] = str(df.loc[mag.idxmin(), tcol])

    # weighted period PF from cumulative registers
    if wh and vah:
        whs = pd.to_numeric(df[wh], errors="coerce").dropna()
        vahs = pd.to_numeric(df[vah], errors="coerce").dropna()
        if len(whs) > 1 and len(vahs) > 1:
            d_wh = whs.iloc[-1] - whs.iloc[0]
            d_vah = vahs.iloc[-1] - vahs.iloc[0]
            if d_vah:
                info["weighted_pf"] = float(d_wh / d_vah)

    if any(k in info for k in ("avg", "weighted_pf")):
        out["pf"].append(info)
    return out


def pf_text(res) -> str:
    lines = [f"Rows analysed: {res['rows']}."]
    for p in res["pf"]:
        if "weighted_pf" in p:
            lines.append(f"Weighted average power factor over the period "
                         f"(dWh/dVAh) = {p['weighted_pf']:.3f}.")
        if "avg_mag" in p:
            lines.append(f"Instantaneous PF (Watts_Total/VA_Total, I<1A excluded): "
                         f"average magnitude {p['avg_mag']:.3f} (signed mean {p['avg']:.3f}); "
                         f"{p['pct_below_090']:.1f}% of readings below 0.90; lowest {p['min']:.3f}"
                         + (f" at {p['lowest_at']}." if 'lowest_at' in p else "."))
        if p.get("negative_share", 0) > 5:
            lines.append(f"Note: {p['negative_share']:.0f}% of instantaneous PF readings were "
                         "negative (possible reverse-connected CT / reverse power flow).")
        if "worst_day" in p:
            lines.append(f"Lowest-average PF day: {p['worst_day']} (avg {p['worst_day_avg']:.3f}); "
                         f"best day: {p['best_day']} (avg {p['best_day_avg']:.3f}).")
    if not res["pf"]:
        lines.append("Power-factor inputs (Watts_Total/VA_Total or Wh/VAh) not available.")
    return "\n".join(lines)



def consumption_advice(tenant, start, end) -> dict:
    df, tcol = _load_range(tenant, start, end)
    power = next((c for c in df.columns if c.lower() == "watts_total"), None) \
        or next((c for c in _cols_like(df, "watts_total", "watts")), None)
    out = {"rows": len(df), "power_col": power}
    if power and tcol:
        s = pd.to_numeric(df[power], errors="coerce")
        tmp = pd.DataFrame({"t": df[tcol], "v": s}).dropna()
        tmp["hour"] = tmp["t"].dt.hour
        tmp["weekend"] = tmp["t"].dt.dayofweek >= 5
        hourly = tmp.groupby("hour")["v"].mean()
        out["peak_hour"] = int(hourly.idxmax()); out["peak_hour_avg"] = float(hourly.max())
        out["low_hour"] = int(hourly.idxmin()); out["low_hour_avg"] = float(hourly.min())
        out["avg_power"] = float(tmp["v"].mean()); out["max_power"] = float(tmp["v"].max())
        out["load_factor_pct"] = float(100 * tmp["v"].mean() / tmp["v"].max()) if tmp["v"].max() else 0.0
        out["weekday_avg"] = float(tmp[~tmp["weekend"]]["v"].mean())
        out["weekend_avg"] = float(tmp[tmp["weekend"]]["v"].mean())
    pf = analyze_pf(tenant, start, end)
    if pf["pf"]:
        out["pf_avg_mag"] = pf["pf"][0]["avg_mag"]
        out["pf_below_090_pct"] = pf["pf"][0]["pct_below_090"]
    return out


def advice_text(res) -> str:
    lines = [f"Rows analysed: {res['rows']}."]
    if res.get("power_col"):
        lines.append(f"Average power {res['avg_power']:.0f} W, peak {res['max_power']:.0f} W, "
                     f"load factor {res['load_factor_pct']:.1f}% "
                     "(low load factor = sharp peaks that raise demand charges).")
        lines.append(f"Highest-usage hour ~{res['peak_hour']:02d}:00 "
                     f"(avg {res['peak_hour_avg']:.0f} W); lowest ~{res['low_hour']:02d}:00 "
                     f"(avg {res['low_hour_avg']:.0f} W).")
        lines.append(f"Weekday average {res['weekday_avg']:.0f} W vs weekend "
                     f"{res['weekend_avg']:.0f} W.")
    if "pf_avg_mag" in res:
        lines.append(f"Average power-factor magnitude {res['pf_avg_mag']:.3f}; "
                     f"{res['pf_below_090_pct']:.1f}% of readings below 0.90.")
    return "\n".join(lines)



_TARIFF = None


def _parse_tariff() -> dict:
    """Parse knowledge_base/tariff.md into structured numbers (once)."""
    global _TARIFF
    if _TARIFF is not None:
        return _TARIFF
    text = ""
    p = config.KNOWLEDGE_BASE_DIR / "tariff.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")

    def _num(pattern, default=None):
        m = re.search(pattern, text, re.I)
        return float(m.group(1).replace(",", "")) if m else default

    _TARIFF = {
        "peak_rate":     _num(r"Peak[^₹]*₹\s*([\d.]+)", 8.65),
        "normal_rate":   _num(r"Normal[^₹]*₹\s*([\d.]+)", 7.15),
        "offpeak_rate":  _num(r"Off-?Peak[^₹]*₹\s*([\d.]+)", 6.65),
        "contract_demand": _num(r"Contract Demand[^\d]*([\d,]+)\s*kVA", 1501),
        "min_demand":    _num(r"Minimum chargeable demand[^\d]*([\d,]+)\s*kVA", 1201),
        "demand_normal": _num(r"Demand charge\s*[—-]\s*Normal[^₹]*₹\s*([\d,]+)", 500),
        "demand_penal":  _num(r"Demand charge\s*[—-]\s*Penal[^₹]*₹\s*([\d,]+)", 1000),
        "duty_per_kvah": (_num(r"([\d.]+)\s*paise", 6.0) or 6.0) / 100.0,
        "customer_charge": _num(r"Customer charges[^₹]*₹\s*([\d,]+)", 3500),
        # ToD windows (hours)
        "peak_hours":   set(list(range(6, 10)) + list(range(18, 22))),
        "normal_hours": set(range(10, 18)),
        "offpeak_hours": set(list(range(22, 24)) + list(range(0, 6))),
    }
    return _TARIFF


def _energy_col(df):
    for name in ("VAh_Received", "vah_received"):
        for c in df.columns:
            if c.lower() == name.lower():
                return c
    return next((c for c in df.columns if "vah" in c.lower() and "received" in c.lower()), None)




def _demand_col(df):
    
    for name in ("va_max",):
        for c in df.columns:
            if c.lower() == name:
                return c
    for name in ("va_total",):
        for c in df.columns:
            if c.lower() == name:
                return c
    return None


def compute_bill(tenant, start, end) -> dict:
    """Deterministic bill from tariff.md applied to the tenant's real readings."""
    tf = _parse_tariff()
    df, tcol = _load_range(tenant, start, end)
    ecol = _energy_col(df)
    dcol = _demand_col(df)

    res = {"rows": len(df), "energy_col": ecol, "demand_col": dcol,
           "tariff": tf, "components": {}, "total": 0.0}
    if df.empty or not ecol or not tcol:
        res["error"] = "Insufficient data (need timestamp + VAh_Received) for billing."
        return res

    
    e_raw = pd.to_numeric(df[ecol], errors="coerce")
    glitch_mask = (e_raw == 0)
    n_glitches = int(glitch_mask.sum())
    if n_glitches:
        df = df.loc[~glitch_mask].reset_index(drop=True)
    res["rows"] = len(df)
    res["glitch_rows_dropped"] = n_glitches

    if df.empty:
        res["error"] = "No valid VAh_Received readings after removing glitch rows."
        return res

    e = pd.to_numeric(df[ecol], errors="coerce")
    hours = df[tcol].dt.hour

    
    delta = e.diff()
    delta.iloc[0] = 0.0            
    delta = delta.clip(lower=0)    # guard against any other stray bad reads

    def _band_of(h):
        if h in tf["peak_hours"]:
            return "peak"
        if h in tf["normal_hours"]:
            return "normal"
        return "offpeak"

    band = hours.map(_band_of)
    # VAh -> kVAh conversion (register is in raw VAh)
    kvah_by_band = (delta / 1000.0).groupby(band).sum()
    kvah_peak = float(kvah_by_band.get("peak", 0.0))
    kvah_normal = float(kvah_by_band.get("normal", 0.0))
    kvah_off = float(kvah_by_band.get("offpeak", 0.0))
    kvah_total = kvah_peak + kvah_normal + kvah_off

    # --- FIX 3: demand from VA_Max (validated substitute), VA_Total fallback
    md = pd.to_numeric(df[dcol], errors="coerce").max() if dcol else 0.0
    md = float(md or 0.0) / 1000.0  # raw VA -> kVA

    
    cd = tf["contract_demand"]
    if md > 2 * cd:
        rate_mult = 1.20
    elif md > 1.2 * cd:
        rate_mult = 1.15
    else:
        rate_mult = 1.0

    energy_charge = (kvah_peak * tf["peak_rate"]
                     + kvah_normal * tf["normal_rate"]
                     + kvah_off * tf["offpeak_rate"]) * rate_mult

    billable_demand = max(md, tf["min_demand"])
    demand_charge = min(billable_demand, tf["contract_demand"]) * tf["demand_normal"]
    excess = max(0.0, md - tf["contract_demand"])
    penal_charge = excess * tf["demand_penal"]

    duty = kvah_total * tf["duty_per_kvah"]
    customer = tf["customer_charge"]

    comp = {
        "energy_charge": round(energy_charge, 2),
        "demand_charge": round(demand_charge, 2),
        "demand_penalty": round(penal_charge, 2),
        "electricity_duty": round(duty, 2),
        "customer_charge": round(customer, 2),
    }
    res["components"] = comp
    res["kvah"] = {"peak": round(kvah_peak, 2), "normal": round(kvah_normal, 2),
                   "offpeak": round(kvah_off, 2), "total": round(kvah_total, 2)}
    res["max_demand_kva"] = round(md, 2)
    res["rate_multiplier"] = rate_mult
    res["billable_demand_kva"] = round(billable_demand, 2)
    res["total"] = round(sum(comp.values()), 2)
    return res


def bill_text(res) -> str:
    if res.get("error"):
        return res["error"]
    c = res["components"]; k = res["kvah"]
    tf = res.get("tariff", {})
    cd = tf.get("contract_demand", 1501)
    md = res["max_demand_kva"]
    # state the demand-vs-contract relationship explicitly so it is never guessed
    if md > cd:
        dem_status = (f"Maximum demand {md} kVA EXCEEDS the contract demand {cd} kVA "
                      f"(penalty applies on the excess).")
    else:
        dem_status = (f"Maximum demand {md} kVA is WITHIN the contract demand {cd} kVA "
                      f"(no penalty).")
    lines = [
        f"Consumption (kVAh): peak {k['peak']}, normal {k['normal']}, off-peak {k['offpeak']}, total {k['total']}.",
        f"Maximum demand: {md} kVA (billable {res['billable_demand_kva']} kVA). {dem_status}",
        f"Energy charge: ₹{c['energy_charge']:.2f}",
        f"Rate penalty multiplier applied to energy: x{res.get('rate_multiplier',1.0)} "
        f"(x1.0 if MD<=1801 kVA, x1.15 if 1801<MD<=3002, x1.20 if MD>3002).",
        f"Demand charge: ₹{c['demand_charge']:.2f}",
        f"Demand penalty (excess over contract): ₹{c['demand_penalty']:.2f}",
        f"Electricity duty: ₹{c['electricity_duty']:.2f}",
        f"Customer charge: ₹{c['customer_charge']:.2f}",
        f"ESTIMATED TOTAL: ₹{res['total']:.2f}",
    ]
    return "\n".join(lines)


_MIN_PREV_COVERAGE = 0.5


def bill_delta(tenant, start, end) -> dict:
    
    s = pd.to_datetime(start); e = pd.to_datetime(end)
    span = e - s
    prev_e = s
    prev_s = s - span

    cur = compute_bill(tenant, start, end)

    _, tmin, tmax = analytics.tenant_time_bounds(tenant)
    tmin = pd.to_datetime(tmin) if tmin is not None else None

    full_prev_available = tmin is not None and prev_s >= tmin
    prev = compute_bill(tenant, prev_s, prev_e) if full_prev_available else None

    comparable = bool(full_prev_available and prev is not None
                      and not prev.get("error") and not cur.get("error")
                      and prev.get("rows", 0) > 0)

    delta = {}
    if comparable:
        for comp in cur["components"]:
            delta[comp] = round(cur["components"][comp] - prev["components"].get(comp, 0), 2)
        delta["total"] = round(cur["total"] - prev["total"], 2)

    return {"current": cur, "previous": prev, "comparable": comparable,
            "prev_rows": prev.get("rows", 0) if prev else 0,
            "cur_rows": cur.get("rows", 0),
            "prev_start": str(prev_s), "prev_end": str(prev_e),
            "data_min": str(tmin) if tmin is not None else None,
            "delta": delta}

def bill_delta_text(res) -> str:
    
    cur, prev, d = res["current"], res["previous"], res["delta"]
    if cur.get("error"):
        return ""

    prev_end = res["prev_end"][:10]
    if not res.get("comparable"):
        data_min = res.get("data_min")
        if data_min and pd.to_datetime(data_min) < pd.to_datetime(res["prev_end"]):
            return (f"Only data from {data_min[:10]} to {prev_end} is available prior to "
                    "the selected period -- that is not a full equal-length prior period, "
                    "so no comparison is made.")
        return "No data is available prior to the selected period, so no comparison is made."

    lines = [f"Previous period total: ₹{prev['total']:.2f} "
             f"(covering {res['prev_start'][:10]} to {prev_end}).",
             f"Change: ₹{d['total']:+.2f}.",
             "Attribution of the change by component:"]
    label = {"energy_charge": "energy", "demand_charge": "demand",
             "demand_penalty": "demand penalty", "electricity_duty": "duty",
             "customer_charge": "customer charge"}
    for k, v in d.items():
        if k == "total":
            continue
        lines.append(f"- {label.get(k, k)}: ₹{v:+.2f}")
    return "\n".join(lines)

def bill_reason_facts(tenant, start, end) -> dict:
    delta_res = bill_delta(tenant, start, end)
    cur, prev = delta_res["current"], delta_res["previous"]
    out = {"comparable": delta_res["comparable"], "cur": cur, "prev": prev,
           "prev_start": delta_res["prev_start"], "prev_end": delta_res["prev_end"],
           "data_min": delta_res.get("data_min")}
    if cur.get("error") or not delta_res["comparable"]:
        return out

    cur_kvah = cur["kvah"]["total"]; prev_kvah = prev["kvah"]["total"]
    out["kvah_cur"] = cur_kvah
    out["kvah_prev"] = prev_kvah
    out["kvah_pct_change"] = ((cur_kvah - prev_kvah) / prev_kvah * 100) if prev_kvah else None

    tf = cur["tariff"]; cd = tf["contract_demand"]
    out["md_cur"] = cur["max_demand_kva"]
    out["md_prev"] = prev["max_demand_kva"]
    out["contract_demand"] = cd
    out["md_cur_exceeds"] = cur["max_demand_kva"] > cd
    out["md_prev_exceeds"] = prev["max_demand_kva"] > cd
    out["demand_penalty_cur"] = cur["components"]["demand_penalty"]
    out["demand_penalty_prev"] = prev["components"]["demand_penalty"]

    pf_cur = analyze_pf(tenant, start, end)
    pf_prev = analyze_pf(tenant, delta_res["prev_start"], delta_res["prev_end"])
    if pf_cur["pf"]:
        out["pf_cur"] = pf_cur["pf"][0].get("avg_mag")
    if pf_prev["pf"]:
        out["pf_prev"] = pf_prev["pf"][0].get("avg_mag")

    out["energy_delta"] = delta_res["delta"].get("energy_charge")
    out["demand_delta"] = delta_res["delta"].get("demand_charge")
    out["penalty_delta"] = delta_res["delta"].get("demand_penalty")
    out["duty_delta"] = delta_res["delta"].get("electricity_duty")
    out["total_delta"] = delta_res["delta"].get("total")
    return out


def bill_reason_text(res) -> str:
    if res["cur"].get("error"):
        return bill_text(res["cur"])
    if not res["comparable"]:
        data_min = res.get("data_min")
        note = (f"Only data from {data_min[:10]} to {res['prev_end'][:10]} is available prior "
                "to the selected period -- not a full equal-length prior period, so no "
                "comparison can be made."
                if data_min else
                "No data is available prior to the selected period, so no comparison can be made.")
        return bill_text(res["cur"]) + "\n\n" + note

    lines = [f"This period total: \u20b9{res['cur']['total']:.2f}; previous period "
             f"({res['prev_start'][:10]} to {res['prev_end'][:10]}) total: "
             f"\u20b9{res['prev']['total']:.2f}; change \u20b9{res['total_delta']:+.2f}."]
    if res.get("kvah_pct_change") is not None:
        lines.append(f"Total consumption: {res['kvah_cur']:.1f} kVAh this period vs "
                     f"{res['kvah_prev']:.1f} kVAh previous period "
                     f"({res['kvah_pct_change']:+.1f}%).")
    lines.append(f"Maximum demand: {res['md_cur']:.1f} kVA this period vs "
                f"{res['md_prev']:.1f} kVA previous period (contract demand "
                f"{res['contract_demand']:.0f} kVA). Demand "
                f"{'EXCEEDED' if res['md_cur_exceeds'] else 'stayed within'} contract this period; "
                f"{'exceeded' if res['md_prev_exceeds'] else 'stayed within'} contract previous "
                f"period. Demand penalty: \u20b9{res['demand_penalty_cur']:.2f} this period vs "
                f"\u20b9{res['demand_penalty_prev']:.2f} previous period.")
    if "pf_cur" in res and "pf_prev" in res:
        lines.append(f"Average power factor: {res['pf_cur']:.3f} this period vs "
                     f"{res['pf_prev']:.3f} previous period.")
    lines.append(f"Component change -- energy \u20b9{res['energy_delta']:+.2f}, "
                f"demand \u20b9{res['demand_delta']:+.2f}, demand penalty "
                f"\u20b9{res['penalty_delta']:+.2f}, duty \u20b9{res['duty_delta']:+.2f}.")
    return "\n".join(lines)

# 5) Power quality: voltage/current unbalance, neutral current
def power_quality(tenant, start, end) -> dict:
    df, tcol = _load_range(tenant, start, end)
    out = {"rows": len(df)}

    def col(name):
        return next((c for c in df.columns if c.lower() == name), None)

    vln = col("vln_avg"); vr = col("v_r"); vy = col("v_y"); vb = col("v_b")
    if vln and vr and vy and vb:
        a = pd.to_numeric(df[vln], errors="coerce")
        r = pd.to_numeric(df[vr], errors="coerce")
        y = pd.to_numeric(df[vy], errors="coerce")
        b = pd.to_numeric(df[vb], errors="coerce")
        vunb = (pd.concat([(r-a).abs(), (y-a).abs(), (b-a).abs()], axis=1).max(axis=1)
                / a.replace(0, pd.NA)) * 100
        vunb = vunb.dropna()
        if not vunb.empty:
            out["v_unbalance_max"] = float(vunb.max())
            out["v_unbalance_avg"] = float(vunb.mean())
            out["v_unbalance_warn_pct"] = float((vunb > 1).mean() * 100)

    itot = col("i_total"); ir = col("i_r"); iy = col("i_y"); ib = col("i_b")
    if itot and ir and iy and ib:
        a = pd.to_numeric(df[itot], errors="coerce")
        r = pd.to_numeric(df[ir], errors="coerce")
        y = pd.to_numeric(df[iy], errors="coerce")
        b = pd.to_numeric(df[ib], errors="coerce")
        iunb = (pd.concat([(r-a).abs(), (y-a).abs(), (b-a).abs()], axis=1).max(axis=1)
                / a.replace(0, pd.NA)) * 100
        iunb = iunb.dropna()
        if not iunb.empty:
            out["i_unbalance_max"] = float(iunb.max())
            out["i_unbalance_avg"] = float(iunb.mean())
            out["i_unbalance_warn_pct"] = float((iunb > 10).mean() * 100)
        # neutral current (vector sum) if not directly measured
        nc = col("neutral_i")
        if nc:
            n = pd.to_numeric(df[nc], errors="coerce").dropna()
            if not n.empty:
                out["neutral_current_max"] = float(n.max())
                out["neutral_current_avg"] = float(n.mean())
        else:
            import numpy as _np
            calc = (r**2 + y**2 + b**2 - r*y - y*b - b*r).clip(lower=0) ** 0.5
            calc = calc.dropna()
            if not calc.empty:
                out["neutral_current_max"] = float(calc.max())
                out["neutral_current_avg"] = float(calc.mean())
    return out


def power_quality_text(res) -> str:
    lines = [f"Rows analysed: {res['rows']}."]
    if "v_unbalance_max" in res:
        lines.append(f"Voltage unbalance: avg {res['v_unbalance_avg']:.2f}%, "
                     f"max {res['v_unbalance_max']:.2f}% (>1% WARNING, >2% HIGH); "
                     f"{res['v_unbalance_warn_pct']:.1f}% of readings above 1%.")
    if "i_unbalance_max" in res:
        lines.append(f"Current unbalance: avg {res['i_unbalance_avg']:.2f}%, "
                     f"max {res['i_unbalance_max']:.2f}% (>10% WARNING, >30% HIGH, "
                     f">50% CRITICAL); {res['i_unbalance_warn_pct']:.1f}% above 10%.")
    if "neutral_current_max" in res:
        lines.append(f"Neutral current: avg {res['neutral_current_avg']:.2f} A, "
                     f"max {res['neutral_current_max']:.2f} A (>15 A indicates "
                     "harmonics/unbalance).")
    if len(lines) == 1:
        lines.append("Power-quality inputs (V/I phase columns) not available.")
    return "\n".join(lines)



_GLOSSARY_CACHE: dict | None = None


def _load_glossary() -> dict:
    """Parse knowledge_base/power_meter_parameter_glossary.md into
    {normalised_column_name: {"category":..., "oneliner":...}} (once)."""
    global _GLOSSARY_CACHE
    if _GLOSSARY_CACHE is not None:
        return _GLOSSARY_CACHE
    mapping: dict = {}
    p = config.KNOWLEDGE_BASE_DIR / "power_meter_parameter_glossary.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        for block in re.split(r"\n(?=### )", text):
            m = re.match(r"### (.+)", block)
            if not m:
                continue
            names = [n.strip() for n in re.split(r"[/,]", m.group(1)) if n.strip()]
            defm = re.search(r"\*\*Definition:\*\*\s*(.+)", block)
            catm = re.search(r"\*\*Category:\*\*\s*(.+)", block)
            definition = defm.group(1).strip() if defm else ""
            category = catm.group(1).strip() if catm else ""
            oneliner = definition.split(". ")[0].strip().rstrip(".")
            oneliner = (oneliner + ".") if oneliner else (category or "")
            for name in names:
                key = re.sub(r"[^a-z0-9]", "", name.lower())
                mapping[key] = {"category": category, "oneliner": oneliner}
    _GLOSSARY_CACHE = mapping
    return mapping


def _describe_column(col: str, glossary: dict) -> str:
    raw = col.strip().lower()
    key = re.sub(r"[^a-z0-9]", "", raw)
    if key in glossary:
        return glossary[key]["oneliner"]
    base_raw = re.sub(r"_(r|y|b|total|avg|max|min|pct|hz)$", "", raw)
    base_key = re.sub(r"[^a-z0-9]", "", base_raw)
    if base_key and base_key in glossary:
        return glossary[base_key]["oneliner"]
    pretty = re.sub(r"_+", " ", col).strip()
    return f"{pretty} (not documented in the glossary yet)"


def dataset_schema(tenant) -> dict:
    df = analytics.load_tenant_df(tenant)
    tcol = analytics.detect_time_column(df)
    _, tmin, tmax = analytics.tenant_time_bounds(tenant)
    glossary = _load_glossary()
    cols = [c for c in df.columns if c != tcol]
    described = [{"name": c, "meaning": _describe_column(c, glossary)} for c in cols]
    return {
        "total_rows": int(len(df)),
        "total_columns": int(len(df.columns)),
        "time_column": tcol,
        "date_min": str(tmin) if tmin is not None else None,
        "date_max": str(tmax) if tmax is not None else None,
        "columns": described,
    }


def schema_text(res: dict) -> str:
    lines = [f"Total rows: {res['total_rows']}.",
             f"Total columns: {res['total_columns']}"
             + (f" (including the timestamp column '{res['time_column']}')."
                if res["time_column"] else ".")]
    if res["date_min"] and res["date_max"]:
        lines.append(f"Data available from {res['date_min']} to {res['date_max']}.")
    else:
        lines.append("No usable timestamp column was found to determine a date range.")
    lines.append("")
    lines.append("Columns:")
    for c in res["columns"]:
        lines.append(f"- {c['name']}: {c['meaning']}")
    return "\n".join(lines)



_COLUMN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")


def verify_schema_columns(llm_text: str, facts: str) -> str:
    real_names = re.findall(r"^- ([^:]+):", facts, re.MULTILINE)
    if not real_names:
        return llm_text 
    real_by_lower = {n.strip().lower(): n.strip() for n in real_names}

    import difflib

    def _fix(m):
        tok = m.group(0)
        low = tok.lower()
        if low in real_by_lower:
            return real_by_lower[low] 
        close = difflib.get_close_matches(low, real_by_lower.keys(), n=1, cutoff=0.82)
        if close:
            return real_by_lower[close[0]]
        return tok  

    return _COLUMN_TOKEN_RE.sub(_fix, llm_text)
