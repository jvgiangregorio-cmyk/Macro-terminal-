"""Market scanner: simple rule-based checks on data the terminal already collects.

No downloads and no API calls: this only reads the JSON files that refresh.py
has saved (Twelve Data prices and history, FRED, Bank of England, CFTC COT) and
writes docs/data/scanner.json for the Scanner tab. refresh.py runs it at the end
of every run; it takes well under a second.

Checks
  moves      today's (and this week's) move compared with that market's normal
             day-to-day swings, as a z-score (2 = twice as big as a typical day)
  ma         price vs its 50- and 200-day moving averages, and recent crosses
  trend      1-week, 1-month and 3-month moves, scaled by each market's volatility
             so a quiet market and a jumpy one can be ranked side by side
  cot        futures positioning compared with its own 3-year range (0-100)
  corr       correlation of daily moves over 3 months and 1 year, and pairs whose
             usual relationship has broken over the last month or today
"""

import datetime as dt
import json
import math
from pathlib import Path

ALWAYS_OPEN = {"BTC/USD"}  # trades every day, so its weekend prices are real
DATA = Path(__file__).resolve().parent.parent / "docs" / "data"

# FRED / Bank of England series to scan: (id, display name, group, how to measure a move)
#   pct = percentage change (prices), bp = change in basis points (yields and spreads, stored in %),
#   pt  = change in points (VIX)
FRED_SCAN = [
    ("DGS2", "US 2-year yield", "Rates", "bp"),
    ("DGS10", "US 10-year yield", "Rates", "bp"),
    ("DGS30", "US 30-year yield", "Rates", "bp"),
    ("T10Y2Y", "US 10y minus 2y", "Rates", "bp"),
    ("DFII10", "US 10-year real yield", "Rates", "bp"),
    ("T10YIE", "US 10-year breakeven inflation", "Rates", "bp"),
    ("BAMLC0A0CM", "IG credit spread", "Credit & risk", "bp"),
    ("BAMLH0A0HYM2", "High-yield credit spread", "Credit & risk", "bp"),
    ("VIXCLS", "VIX", "Credit & risk", "pt"),
    ("DTWEXBGS", "Broad US dollar index", "FX", "pct"),
    ("DCOILWTICO", "WTI crude", "Commodities", "pct"),
    ("DCOILBRENTEU", "Brent crude", "Commodities", "pct"),
    ("DHHNGSP", "Henry Hub natural gas", "Commodities", "pct"),
]
BOE_SCAN = [
    ("IUDSNPY", "UK 5-year gilt", "Rates", "bp"),
    ("IUDMNPY", "UK 10-year gilt", "Rates", "bp"),
    ("IUDLNPY", "UK 20-year gilt", "Rates", "bp"),
]
# Markets in the correlation map (kept short so the grid stays readable)
CORR_KEYS = ["SPY", "QQQ", "IWM", "EEM", "EUR/USD", "USD/JPY", "GBP/USD", "AUD/USD", "USD/CAD",
             "XAU/USD", "USO", "BTC/USD", "DGS2", "DGS10", "DTWEXBGS", "VIXCLS", "BAMLH0A0HYM2"]
SHORT = {"DGS2": "US 2y", "DGS10": "US 10y", "DTWEXBGS": "Dollar idx", "VIXCLS": "VIX",
         "BAMLH0A0HYM2": "HY spread", "XAU/USD": "Gold", "USO": "Oil", "BTC/USD": "Bitcoin"}

VOL_WINDOW = 60          # days of moves that define "normal" for the z-score
Z_FLAG = 2.0             # flag moves at least this many times a normal day
TREND_DAYS = {"1w": 5, "1m": 21, "3m": 63}
MA_CROSS_LOOKBACK = 10   # report crosses that happened in the last 10 trading days
COT_WEEKS = 156          # 3 years
COT_FLAG = (10, 90)      # COT index at or beyond these = stretched
CORR_SHORT, CORR_LONG, CORR_BREAK = 21, 250, 63


def load(name):
    p = DATA / name
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except ValueError:
        return None


def r(x, d=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, d)


def sd(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(v) if v > 0 else None


def corr(a, b):
    n = len(a)
    if n < 10:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    saa = sum((x - ma) ** 2 for x in a)
    sbb = sum((y - mb) ** 2 for y in b)
    return sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else None


def change(kind, a, b):
    """Move from level a to level b: % for prices, bp for yields, points for VIX."""
    if kind == "pct":
        return 100 * math.log(b / a) if a > 0 and b > 0 else None
    if kind == "bp":
        return 100 * (b - a)
    return b - a


def universe():
    """Every market to scan: key -> {name, group, kind, src, pts=[[date, level], ...]}"""
    out = {}
    hist = (load("price_history.json") or {}).get("series", {})
    quotes = {q["symbol"]: q for q in (load("prices.json") or {}).get("quotes", [])}
    try:
        from refresh import TD_SYMBOLS
    except ImportError:
        TD_SYMBOLS = [(s, q.get("name", s), q.get("group", "")) for s, q in quotes.items()]
    for sym, name, group in TD_SYMBOLS:
        # Weekend bars (currencies, gold) are dropped: the market is shut, and keeping them would turn
        # the "200-day average" into ~140 trading days and make normal daily swings look smaller.
        keep = lambda day: sym in ALWAYS_OPEN or dt.date.fromisoformat(day[:10]).weekday() < 5
        pts = [p for p in hist.get(sym, []) if p[1] is not None and keep(p[0])]
        q = quotes.get(sym)
        # add the latest live quote, like the page does, so "today" is today
        if q and q.get("price") is not None and q.get("as_of") and keep(q["as_of"]):
            day = q["as_of"][:10]
            if pts and pts[-1][0] == day:
                pts[-1] = [day, q["price"]]
            elif not pts or pts[-1][0] < day:
                pts.append([day, q["price"]])
        if "/" in sym and group == "FX":
            name = sym  # "USD/JPY", not "Japanese yen": USD/JPY rising means the yen is falling
        if len(pts) > 30:
            out[sym] = {"name": name, "group": group, "kind": "pct", "src": "td", "pts": pts}
    for fname, table in (("fred.json", FRED_SCAN), ("boe.json", BOE_SCAN)):
        series = (load(fname) or {}).get("series", {})
        for sid, name, group, kind in table:
            s = series.get(sid)
            if s and len(s.get("obs", [])) > 30:
                out[sid] = {"name": name, "group": group, "kind": kind, "src": "fred", "pts": s["obs"]}
    return out


def moves_of(m):
    pts = m["pts"]
    return [(pts[i][0], change(m["kind"], pts[i - 1][1], pts[i][1])) for i in range(1, len(pts))]


def scan_market(key, m):
    pts, kind = m["pts"], m["kind"]
    mv = [(d, x) for d, x in moves_of(m) if x is not None]
    levels = [p[1] for p in pts]
    row = {"key": key, "name": m["name"], "group": m["group"], "kind": kind, "src": m["src"],
           "date": pts[-1][0], "last": r(levels[-1], 4)}
    # --- unusual moves
    if len(mv) > VOL_WINDOW + 5:
        base = sd([x for _, x in mv[-VOL_WINDOW - 1:-1]])
        if base:
            row["chg1"] = r(mv[-1][1])
            row["z1"] = r(mv[-1][1] / base)
            wk = sum(x for _, x in mv[-5:])
            row["chg5"] = r(wk)
            row["z5"] = r(wk / (base * math.sqrt(5)))
    # --- moving averages
    def ma(n, end):
        return sum(levels[end - n:end]) / n if end >= n else None
    n = len(levels)
    m50, m200 = ma(50, n), ma(200, n)
    if m200:
        row["ma50"], row["ma200"] = r(m50, 4), r(m200, 4)
        row["vs200"] = r(change(kind, m200, levels[-1]))  # % (or bp) above/below the 200-day
        row["above200"] = levels[-1] > m200
        row["above50"] = levels[-1] > m50
        events = []
        for i in range(max(201, n - MA_CROSS_LOOKBACK), n):
            p0, p1 = levels[i - 1], levels[i]
            a0, a1 = ma(200, i), ma(200, i + 1)
            f0, f1 = ma(50, i), ma(50, i + 1)
            if (p0 - a0) * (p1 - a1) < 0:
                events.append({"date": pts[i][0], "type": "up200" if p1 > a1 else "down200"})
            if (f0 - a0) * (f1 - a1) < 0:
                events.append({"date": pts[i][0], "type": "golden" if f1 > a1 else "death"})
        # keep only the latest cross of each kind, and only if it still holds today
        # (a market that dipped under its 200-day and climbed back is not "below its 200-day")
        held = []
        for kind_ in (("up200", "down200"), ("golden", "death")):
            last = [e for e in events if e["type"] in kind_][-1:]
            if last:
                e = last[0]
                ok = {"up200": levels[-1] > m200, "down200": levels[-1] < m200,
                      "golden": m50 > m200, "death": m50 < m200}[e["type"]]
                if ok:
                    held.append(e)
        if held:
            row["crosses"] = sorted(held, key=lambda e: e["date"])
    # --- trend strength: move over n days divided by what a normal n-day move is
    yr = [x for _, x in mv[-250:]]
    dsd = sd(yr)
    if dsd:
        scores = []
        for label, days in TREND_DAYS.items():
            if n > days:
                c = change(kind, levels[-1 - days], levels[-1])
                if c is not None:
                    row["t" + label] = r(c)
                    s = c / (dsd * math.sqrt(days))
                    row["s" + label] = r(s)
                    scores.append(s)
        if len(scores) == len(TREND_DAYS):
            row["trend"] = r(sum(scores) / len(scores))
    return row


def scan_cot():
    rows = []
    for mkt in (load("cot.json") or {}).get("markets", []):
        obs = [o for o in mkt.get("obs", [])][-COT_WEEKS:]
        if len(obs) < 52:
            continue
        # hedge funds (leveraged funds / managed money) where the CFTC reports them, else large speculators
        col, who = (6, "funds") if all(len(o) > 6 and o[6] is not None for o in obs[-52:]) else (1, "specs")
        vals = [o[col] for o in obs if len(o) > col and o[col] is not None]
        if len(vals) < 52:
            continue
        lo, hi, last = min(vals), max(vals), vals[-1]
        idx = 100 * (last - lo) / (hi - lo) if hi > lo else 50
        wk = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
        wsd = sd(wk[-53:-1])
        oi = obs[-1][5] if len(obs[-1]) > 5 else None
        rows.append({"code": mkt["code"], "name": mkt["name"], "group": mkt.get("group", ""), "who": who,
                     "date": obs[-1][0], "net": last, "index": r(idx, 0), "pct_oi": r(100 * last / oi, 1) if oi else None,
                     "wchg": wk[-1] if wk else None, "wz": r(wk[-1] / wsd) if wsd and wk else None,
                     "flag": "long" if idx >= COT_FLAG[1] else "short" if idx <= COT_FLAG[0] else None})
    return rows


def scan_corr(mkts):
    keys = [k for k in CORR_KEYS if k in mkts]
    mv = {k: dict(x for x in moves_of(mkts[k]) if x[1] is not None) for k in keys}
    windows = {"3m": 63, "1y": CORR_LONG}
    mats = {w: [[None] * len(keys) for _ in keys] for w in windows}
    breaks = []
    for i, a in enumerate(keys):
        for j in range(i, len(keys)):
            b = keys[j]
            if i == j:
                for w in windows:
                    mats[w][i][j] = 1.0
                continue
            days = sorted(set(mv[a]) & set(mv[b]))
            got = {}
            for w, n in list(windows.items()) + [("1m", CORR_SHORT)]:
                d = days[-n:]
                got[w] = corr([mv[a][x] for x in d], [mv[b][x] for x in d]) if len(d) >= min(n, 15) else None
            for w in windows:
                mats[w][i][j] = mats[w][j][i] = r(got[w])
            usual, now = got["1y"], got["1m"]
            if usual is None or now is None or abs(usual) < 0.3:
                continue
            pair = {"a": a, "b": b, "usual": r(usual), "now": r(now)}
            # a month of moves that runs against the usual relationship
            if usual * now < 0 and abs(usual - now) >= 0.5 or abs(now) < 0.1 and abs(usual) >= 0.45:
                breaks.append(dict(pair, type="month", since=days[-CORR_SHORT]))
            # today: both moved clearly, in the "wrong" direction for a pair that usually moves together (or apart)
            da, db = mkts[a]["pts"][-1][0], mkts[b]["pts"][-1][0]
            if da == db and days and days[-1] == da and abs(usual) >= 0.4:
                za = mv[a][da] / (sd(list(mv[a].values())[-61:-1]) or 1e9)
                zb = mv[b][da] / (sd(list(mv[b].values())[-61:-1]) or 1e9)
                if abs(za) >= 1 and abs(zb) >= 1 and za * zb * usual < 0:
                    breaks.append(dict(pair, type="today", date=da, za=r(za), zb=r(zb)))
    breaks.sort(key=lambda x: (x["type"] != "today", -abs(x["usual"] - x["now"])))
    return {"keys": keys, "names": [SHORT.get(k, k) for k in keys], "matrix": mats, "breaks": breaks[:20]}


def run():
    mkts = universe()
    rows = [scan_market(k, m) for k, m in mkts.items()]
    payload = {
        "markets": rows,
        "cot": scan_cot(),
        "corr": scan_corr(mkts),
        "settings": {"vol_window": VOL_WINDOW, "z_flag": Z_FLAG, "cot_weeks": COT_WEEKS, "cot_flag": COT_FLAG,
                     "corr_short": CORR_SHORT, "corr_long": CORR_LONG},
        # things Joe asked about that need data the terminal doesn't collect yet
        "missing": [
            "Australian (and other non-US/UK) yield-curve regime changes: no daily AUD curve data is collected yet.",
            "S&P 500 sector leadership: sector prices are not collected (it would need 11 more Twelve Data symbols).",
        ],
    }
    return payload


if __name__ == "__main__":
    out = run()
    out["updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (DATA / "scanner.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"scanner.json: {len(out['markets'])} markets, {len(out['cot'])} COT, {len(out['corr']['breaks'])} breaks")
