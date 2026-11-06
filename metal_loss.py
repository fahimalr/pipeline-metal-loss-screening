"""
Metal-loss screening for pipeline corrosion features.

Implements ASME B31G (original), Modified B31G (0.85dL) and DNV-RP-F101 Part B
(single defect, internal pressure, no partial safety factors), plus estimated
repair factor (ERF), remaining life at a linear depth growth rate, and dig
prioritisation for an in-line inspection (ILI) anomaly list.

Units: millimetres and MPa throughout (pressures returned in MPa).

Usage:
    python metal_loss.py data/sample_ili_anomalies.csv
"""
from __future__ import annotations

import csv
import math
import sys
from dataclasses import dataclass

GRADES = {  # SMYS, SMTS in MPa (API 5L / CSA Z245.1 minimums)
    "X42": (290, 415), "X52": (359, 455), "X60": (414, 517),
    "X65": (448, 531), "X70": (483, 565), "X80": (552, 621),
}


@dataclass
class Pipe:
    D: float          # outside diameter, mm
    t: float          # nominal wall thickness, mm
    smys: float       # MPa
    smts: float       # MPa
    maop: float       # MPa
    F: float = 0.80   # design factor
    cgr: float = 0.10  # depth growth rate, mm/yr


def p_b31g(p: Pipe, d: float, L: float, t: float | None = None) -> float:
    """Failure pressure, ASME B31G original (MPa)."""
    t = t or p.t
    a, sflow, z = d / t, 1.1 * p.smys, L * L / (p.D * t)
    if z <= 20:
        M = math.sqrt(1 + 0.8 * z)
        S = sflow * (1 - 2 / 3 * a) / (1 - 2 / 3 * a / M)
    else:
        S = sflow * (1 - a)
    return 2 * S * t / p.D


def p_mod_b31g(p: Pipe, d: float, L: float, t: float | None = None) -> float:
    """Failure pressure, Modified B31G / 0.85dL (MPa)."""
    t = t or p.t
    a, sflow, z = d / t, p.smys + 69, L * L / (p.D * t)
    M = math.sqrt(1 + 0.6275 * z - 0.003375 * z * z) if z <= 50 else 0.032 * z + 3.3
    S = sflow * (1 - 0.85 * a) / (1 - 0.85 * a / M)
    return 2 * S * t / p.D


def p_dnv(p: Pipe, d: float, L: float, t: float | None = None) -> float:
    """Capacity, DNV-RP-F101 Part B single defect, no safety factors (MPa)."""
    t = t or p.t
    a = d / t
    Q = math.sqrt(1 + 0.31 * (L / math.sqrt(p.D * t)) ** 2)
    return 2 * t * p.smts * (1 - a) / ((p.D - t) * (1 - a / Q))


METHODS = {"B31G": p_b31g, "ModB31G": p_mod_b31g, "DNV-RP-F101": p_dnv}


def erf(p: Pipe, method, d: float, L: float, t: float | None = None) -> float:
    """Estimated repair factor = MAOP / (failure pressure x design factor)."""
    return p.maop / (method(p, d, L, t) * p.F)


def years_to_erf1(p: Pipe, method, d: float, L: float, t: float | None = None) -> float:
    """Years until ERF reaches 1 or depth reaches 80% WT, with length held constant."""
    t = t or p.t
    dmax = 0.8 * t
    if d >= dmax or erf(p, method, d, L, t) >= 1:
        return 0.0
    if p.cgr <= 0:
        return math.inf
    lo, hi = 0.0, (dmax - d) / p.cgr
    if erf(p, method, dmax, L, t) < 1:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2
        if erf(p, method, d + p.cgr * mid, L, t) >= 1:
            hi = mid
        else:
            lo = mid
    return hi


def priority(worst_erf: float, years: float, d_over_t: float) -> str:
    if worst_erf >= 1 or d_over_t >= 0.8:
        return "Immediate"
    if worst_erf >= 0.9 or years < 5:
        return "Scheduled"
    return "Monitor"


def assess_list(p: Pipe, rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        t = float(r["wt_mm"]) if r.get("wt_mm") else p.t
        d = float(r["depth_pct"]) / 100 * t
        L = float(r["length_mm"])
        erfs = {k: erf(p, f, d, L, t) for k, f in METHODS.items()}
        yrs = min(years_to_erf1(p, f, d, L, t) for f in METHODS.values())
        worst = max(erfs.values())
        out.append({**r, **{f"ERF_{k}": round(v, 3) for k, v in erfs.items()},
                    "years_to_ERF1": round(yrs, 1), "priority": priority(worst, yrs, d / t),
                    "_worst": worst})
    return sorted(out, key=lambda x: -x["_worst"])


if __name__ == "__main__":
    smys, smts = GRADES["X52"]
    pipe = Pipe(D=323.9, t=6.4, smys=smys, smts=smts, maop=9.93)
    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_ili_anomalies.csv"
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    res = assess_list(pipe, rows)
    print(f"{'id':8} {'depth%':>6} {'L mm':>6} {'B31G':>6} {'Mod':>6} {'DNV':>6} {'yrs':>6}  priority")
    for x in res:
        print(f"{x['id']:8} {x['depth_pct']:>6} {x['length_mm']:>6} {x['ERF_B31G']:>6.2f} "
              f"{x['ERF_ModB31G']:>6.2f} {x['ERF_DNV-RP-F101']:>6.2f} {x['years_to_ERF1']:>6}  {x['priority']}")
