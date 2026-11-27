"""Fetch fresh market data for the Macro Terminal and save it as JSON files.

GitHub runs this on a schedule (see .github/workflows/refresh.yml).
It reads the two API keys from environment variables, which GitHub fills in
from the repository's Secrets. The keys are never written to any file.

Sources
  Twelve Data  stock ETFs, currencies, gold, silver, oil, bitcoin
  FRED         Treasury yields, Fed funds, spreads, VIX, dollar, economic data
  Bank of England  UK Bank Rate, SONIA, gilt yields, sterling (no key needed)
  Finnhub      earnings dates
  CFTC         Commitments of Traders futures positioning (no key needed)
  Forex Factory  this week's economic calendar (no key needed)
  Fundamentals  economic indicators for the eight major currencies from FRED, ONS,
                ECB, OECD, BIS, Statistics Canada, RBA, SNB and Japan's Statistics
                Bureau (see scripts/fundamentals.py; only FRED needs a key)

GitHub starts this every 10 minutes. Each source has its own timer (SCHEDULE
below) so nobody's limits are hit, and docs/data/status.json records when each
source was last checked and last had new data (the page shows both).

Twelve Data's free plan allows 800 calls a day and 8 a minute, where each
symbol counts as one call. Currencies, gold and bitcoin (10 symbols) refresh
every 20 minutes on weekdays 06:00-21:59 UTC (~480 calls); the US-listed ETFs
(8 symbols) every 20 minutes while US markets are open (~190 calls); plus one
daily history download (18 calls). Total ~690, leaving room for a manual run.
The page works out all 28 crosses between the eight major currencies from the
dollar pairs, so the crosses cost no extra calls.

Run locally:  TWELVEDATA_API_KEY=... FRED_API_KEY=... python scripts/refresh.py
Options:      --all   fetch everything now, ignoring the schedule rules
"""

import datetime as dt
import email.utils
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "docs" / "data"
UA = "macro-terminal/1.0 (personal dashboard)"

# ---------------------------------------------------------------- what to fetch

# (Twelve Data symbol, display name, group)
TD_SYMBOLS = [
    ("SPY", "S&P 500 (SPY)", "Equities"),
    ("QQQ", "Nasdaq 100 (QQQ)", "Equities"),
    ("DIA", "Dow Jones (DIA)", "Equities"),
    ("IWM", "Russell 2000 (IWM)", "Equities"),
    ("EFA", "Developed ex-US (EFA)", "Equities"),
    ("EEM", "Emerging mkts (EEM)", "Equities"),
    ("EUR/USD", "Euro", "FX"),
    ("USD/JPY", "Japanese yen", "FX"),
    ("GBP/USD", "British pound", "FX"),
    ("USD/CNY", "Chinese yuan", "FX"),
    ("AUD/USD", "Australian dollar", "FX"),
    ("NZD/USD", "New Zealand dollar", "FX"),
    ("USD/CAD", "Canadian dollar", "FX"),
    ("USD/CHF", "Swiss franc", "FX"),
    ("XAU/USD", "Gold", "Commodities"),
    ("SLV", "Silver (SLV ETF)", "Commodities"),   # XAG/USD is not on the free plan
    ("USO", "Oil (USO ETF)", "Commodities"),      # WTI/USD is not on the free plan
    ("BTC/USD", "Bitcoin", "Commodities"),
]
# Minutes between checks for each source (the job itself runs every 10 minutes).
SCHEDULE = {
    "prices_fx": 20,      # Twelve Data, 10 symbols, weekdays 06-22 UTC
    "prices_us": 20,      # Twelve Data, 8 symbols, US market hours only
    "fred": 30,           # FRED data is daily or slower
    "boe": 30,
    "cot": 10,            # quick "is there a new report?" check
    "calendar": 60,       # earnings dates + US release dates
    "forexfactory": 30,   # Forex Factory asks people not to poll it often
    "fundamentals": 360,  # official economic statistics (scripts/fundamentals.py), ~55 requests
}
US_SESSION_UTC = (13 * 60 + 30, 21 * 60 + 15)   # minutes after midnight UTC (covers summer and winter time)
TD_BATCH = 8          # free plan: 8 calls per minute
TD_PAUSE = 62         # seconds to wait between batches
PRICE_HOURS_UTC = range(6, 22)
HISTORY_DAYS = 400    # trading days of daily closes kept for charts

# (FRED id, display name, group, unit, FRED "units" transform, years of history)
FRED_SERIES = [
    ("DFF", "Fed funds (effective)", "Rates", "%", "lin", 2),
    ("SOFR", "SOFR", "Rates", "%", "lin", 2),
    ("DGS3MO", "3-month Treasury", "Rates", "%", "lin", 2),
    ("DGS2", "2-year Treasury", "Rates", "%", "lin", 2),
    ("DGS5", "5-year Treasury", "Rates", "%", "lin", 2),
    ("DGS10", "10-year Treasury", "Rates", "%", "lin", 2),
    ("DGS30", "30-year Treasury", "Rates", "%", "lin", 2),
    ("T10Y2Y", "10y minus 2y", "Rates", "pp", "lin", 2),
    ("DFII10", "10-year real yield", "Rates", "%", "lin", 2),
    ("T10YIE", "10-year breakeven inflation", "Rates", "%", "lin", 2),
    ("MORTGAGE30US", "30-year mortgage", "Rates", "%", "lin", 2),
    ("BAMLC0A0CM", "IG credit spread", "Credit & risk", "%", "lin", 2),
    ("BAMLH0A0HYM2", "High-yield credit spread", "Credit & risk", "%", "lin", 2),
    ("VIXCLS", "VIX", "Credit & risk", "", "lin", 2),
    ("DTWEXBGS", "Broad US dollar index", "Credit & risk", "", "lin", 2),
    ("DCOILWTICO", "WTI crude", "Credit & risk", "$", "lin", 2),
    ("DCOILBRENTEU", "Brent crude", "Credit & risk", "$", "lin", 2),
    ("DHHNGSP", "Henry Hub natural gas", "Credit & risk", "$", "lin", 2),
    ("CPIAUCSL", "CPI inflation", "Economy", "% y/y", "pc1", 6),
    ("CPILFESL", "Core CPI inflation", "Economy", "% y/y", "pc1", 6),
    ("PCEPILFE", "Core PCE inflation", "Economy", "% y/y", "pc1", 6),
    ("UNRATE", "Unemployment rate", "Economy", "%", "lin", 6),
    ("PAYEMS", "Payrolls, monthly change", "Economy", "k", "chg", 6),
    ("ICSA", "Initial jobless claims", "Economy", "", "lin", 3),
    ("GDPC1", "Real GDP growth", "Economy", "% ann.", "pca", 8),
]

# CFTC Commitments of Traders (legacy, futures only). Contract codes stay the same
# even when the CFTC renames a market, so we match on the code.
# (code, display name, group)
COT_MARKETS = [
    ("042601", "2-year T-note", "Rates"),
    ("044601", "5-year T-note", "Rates"),
    ("043602", "10-year T-note", "Rates"),
    ("020601", "Treasury bond", "Rates"),
    ("134741", "3-month SOFR", "Rates"),
    ("13874A", "S&P 500 e-mini", "Equities"),
    ("209742", "Nasdaq 100 e-mini", "Equities"),
    ("124603", "Dow e-mini", "Equities"),
    ("1170E1", "VIX", "Equities"),
    ("098662", "US dollar index", "FX"),
    ("099741", "Euro", "FX"),
    ("097741", "Japanese yen", "FX"),
    ("096742", "British pound", "FX"),
    ("232741", "Australian dollar", "FX"),
    ("090741", "Canadian dollar", "FX"),
    ("088691", "Gold", "Commodities"),
    ("084691", "Silver", "Commodities"),
    ("067651", "WTI crude oil", "Commodities"),
    ("085692", "Copper", "Commodities"),
    ("023651", "Natural gas", "Commodities"),
    ("133741", "Bitcoin", "Commodities"),
]
COT_YEARS = 10
COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# Bank of England statistical database (IADB). (code, display name, group, unit)
BOE_SERIES = [
    ("IUDBEDR", "Bank Rate", "UK", "%"),
    ("IUDSOIA", "SONIA", "UK", "%"),
    ("IUDSNPY", "5-year gilt", "UK", "%"),
    ("IUDMNPY", "10-year gilt", "UK", "%"),
    ("IUDLNPY", "20-year gilt", "UK", "%"),
    ("XUDLUSS", "Sterling in dollars", "UK", ""),
    ("XUDLERS", "Sterling in euros", "UK", ""),
    ("XUDLBK67", "Sterling index (trade-weighted)", "UK", ""),
]
BOE_YEARS = 5
BOE_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
# The Bank's site turns away requests that don't look like a browser.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# Finnhub (free key). Countries and companies to keep from the calendars.
FINNHUB_URL = "https://finnhub.io/api/v1"
CAL_COUNTRIES = {"US", "GB", "EU", "DE", "FR", "JP", "CN", "CA", "AU"}
EARNINGS_WATCH = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "BRK.B", "JPM", "V", "MA",
    "UNH", "XOM", "LLY", "JNJ", "WMT", "PG", "HD", "COST", "ORCL", "NFLX", "CRM", "AMD", "ADBE",
    "BAC", "WFC", "GS", "MS", "C", "KO", "PEP", "MCD", "NKE", "DIS", "INTC", "CSCO", "CVX", "CAT",
    "BA", "IBM", "QCOM", "TXN", "MU", "PLTR", "UBER", "FDX", "TGT", "LOW", "SBUX",
}

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_CURRENCIES = {"USD", "GBP", "EUR", "JPY", "CNY", "CAD", "AUD", "CHF", "NZD"}

# ---------------------------------------------------------------- helpers


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(url):
    return json.loads(get(url).decode("utf-8"))


def load(name):
    p = DATA / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            pass
    return None


def save(name, payload):
    """Write the file only if the data changed, so unchanged runs make no commit."""
    old = load(name)
    strip = lambda d: {k: v for k, v in (d or {}).items() if k != "updated"}
    if old is not None and strip(old) == strip(payload):
        print(f"  {name}: unchanged")
        return False
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    print(f"  {name}: saved")
    return True


# ---------------------------------------------------------------- run status

STATUS = {}


def due(source, force=False):
    """True if this source hasn't been checked for its SCHEDULE minutes (with 3 minutes' slack)."""
    if force:
        return True
    last = STATUS.get(source, {}).get("checked")
    if not last:
        return True
    age = now_utc() - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
    return age >= dt.timedelta(minutes=SCHEDULE[source] - 3)


def run_source(source, fn, *args):
    """Run one fetch, record when it was checked and whether it brought new data."""
    st = STATUS.setdefault(source, {})
    st["checked"] = iso(now_utc())
    try:
        changed = fn(*args)
        st["ok"] = True
        st.pop("error", None)
        if changed:
            st["changed"] = st["checked"]
    except Exception as e:  # noqa: BLE001
        msg = str(e)[:200]
        for k in (os.environ.get(v, "") for v in ("TWELVEDATA_API_KEY", "FRED_API_KEY", "FINNHUB_API_KEY")):
            msg = hide_key(msg, k)
        print(f"  {source} failed: {msg}")
        st["ok"] = False
        st["error"] = msg


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def hide_key(text, key):
    return text.replace(key, "***") if key else text


# ---------------------------------------------------------------- Twelve Data


def td_call(endpoint, symbols, key, **params):
    """One batched Twelve Data request. Returns {symbol: response} or raises."""
    q = dict(params, symbol=",".join(symbols), apikey=key)
    url = f"https://api.twelvedata.com/{endpoint}?" + urllib.parse.urlencode(q)
    for attempt in (1, 2):
        try:
            data = get_json(url)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            data = {"status": "error", "code": 429}
        limited = isinstance(data, dict) and data.get("status") == "error" and data.get("code") == 429
        if limited and attempt == 1:
            print("  Twelve Data says too many calls this minute; waiting and trying once more")
            time.sleep(TD_PAUSE)
            continue
        break
    # A whole-request error (bad key, out of credits) comes back flat.
    if isinstance(data, dict) and data.get("status") == "error" and "code" in data:
        raise RuntimeError(f"Twelve Data error {data.get('code')}: {data.get('message')}")
    if len(symbols) == 1:
        return {symbols[0]: data}
    return data


def td_batches(endpoint, key, syms=None, **params):
    out, errors = {}, []
    syms = syms or [s for s, _, _ in TD_SYMBOLS]
    for i in range(0, len(syms), TD_BATCH):
        if i:
            time.sleep(TD_PAUSE)
        batch = syms[i:i + TD_BATCH]
        try:
            out.update(td_call(endpoint, batch, key, **params))
        except Exception as e:  # noqa: BLE001
            msg = hide_key(str(e), key)
            print(f"  Twelve Data {endpoint} failed: {msg}")
            errors.append(msg)
            if "401" in msg or "403" in msg or "credits" in msg.lower():
                break
    return out, errors


US_SYMBOLS = [s for s, _, _ in TD_SYMBOLS if "/" not in s]      # US-listed ETFs
FX_SYMBOLS = [s for s, _, _ in TD_SYMBOLS if "/" in s]          # trade around the clock


def fetch_prices(key, syms):
    print(f"Twelve Data prices: {', '.join(syms)}")
    raw, errors = td_batches("quote", key, syms)
    old = {q["symbol"]: q for q in (load("prices.json") or {}).get("quotes", [])}
    quotes = []
    for sym, name, group in TD_SYMBOLS:
        if sym not in syms:
            if sym in old:
                quotes.append(old[sym])
            continue
        r = raw.get(sym) or {}
        if r.get("status") == "error" or num(r.get("close")) is None:
            msg = r.get("message") or "no data returned"
            q = dict(old.get(sym, {}), symbol=sym, name=name, group=group, error=msg[:160])
            quotes.append(q)
            continue
        quotes.append({
            "symbol": sym, "name": name, "group": group,
            "price": num(r.get("close")),
            "prev_close": num(r.get("previous_close")),
            "change": num(r.get("change")),
            "pct": num(r.get("percent_change")),
            "high_52w": num((r.get("fifty_two_week") or {}).get("high")),
            "low_52w": num((r.get("fifty_two_week") or {}).get("low")),
            "market_open": r.get("is_market_open"),
            "as_of": r.get("datetime"),
            "ts": r.get("timestamp"),
        })
    if not any(raw.get(s) for s in syms):
        raise RuntimeError("; ".join(errors) or "no prices returned")
    return save("prices.json", {"updated": iso(now_utc()), "errors": errors, "quotes": quotes})


def fetch_price_history(key):
    print("Twelve Data daily history")
    raw, errors = td_batches("time_series", key, interval="1day", outputsize=HISTORY_DAYS)
    old = (load("price_history.json") or {}).get("series", {})
    series = {}
    for sym, _, _ in TD_SYMBOLS:
        r = raw.get(sym) or {}
        vals = r.get("values")
        if vals:
            pts = [[v["datetime"][:10], num(v["close"])] for v in reversed(vals)]
            series[sym] = [p for p in pts if p[1] is not None]
        elif sym in old:
            series[sym] = old[sym]
    if not series:
        raise RuntimeError("; ".join(errors) or "no history returned")
    return save("price_history.json", {"updated": iso(now_utc()), "errors": errors, "series": series})


def history_is_stale():
    """Daily closes: download once every 20 hours."""
    last = STATUS.get("price_history", {}).get("checked") or (load("price_history.json") or {}).get("updated")
    if not last:
        return True
    return now_utc() - dt.datetime.fromisoformat(last.replace("Z", "+00:00")) > dt.timedelta(hours=20)


# ---------------------------------------------------------------- FRED


def fetch_fred(key):
    print("FRED")
    today = now_utc().date()
    old = (load("fred.json") or {}).get("series", {})
    series, errors = {}, []
    for sid, name, group, unit, units, years in FRED_SERIES:
        start = today.replace(year=today.year - years)
        q = {"series_id": sid, "api_key": key, "file_type": "json",
             "observation_start": start.isoformat(), "units": units}
        url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(q)
        try:
            obs = get_json(url)["observations"]
            pts = [[o["date"], round(float(o["value"]), 4)] for o in obs if o["value"] not in (".", "")]
            series[sid] = {"name": name, "group": group, "unit": unit, "obs": pts}
        except Exception as e:  # noqa: BLE001
            msg = hide_key(str(e), key)
            print(f"  {sid} failed: {msg}")
            errors.append(f"{sid}: {msg}")
            if sid in old:
                series[sid] = old[sid]
        time.sleep(0.6)  # FRED allows 120 requests a minute; stay well below
    if series:
        return save("fred.json", {"updated": iso(now_utc()), "errors": errors, "series": series})
    raise RuntimeError("; ".join(errors[:3]) or "no data")


# ---------------------------------------------------------------- CFTC COT


def fetch_cot():
    """Weekly positioning. Each point: [date, spec net, spec long, spec short, commercial net, open interest].

    "Spec" is the CFTC's non-commercial group (mostly hedge funds and other
    speculators). Net = long contracts minus short contracts.
    """
    print("CFTC Commitments of Traders")
    have = load("cot.json")
    if have and have.get("markets"):
        latest = get_json(COT_URL + "?" + urllib.parse.urlencode({"$select": "max(report_date_as_yyyy_mm_dd) as d"}))
        newest = (latest[0].get("d") or "")[:10] if latest else ""
        mine = max(m["obs"][-1][0] for m in have["markets"])
        if newest and newest <= mine:
            print(f"  no new report (latest is {mine})")
            return False
        print(f"  new report for {newest}: downloading")
    start = now_utc().date().replace(year=now_utc().year - COT_YEARS)
    codes = ",".join(f"'{c}'" for c, _, _ in COT_MARKETS)
    q = {
        "$select": "cftc_contract_market_code,report_date_as_yyyy_mm_dd,open_interest_all,"
                   "noncomm_positions_long_all,noncomm_positions_short_all,"
                   "comm_positions_long_all,comm_positions_short_all",
        "$where": f"cftc_contract_market_code in({codes}) AND report_date_as_yyyy_mm_dd >= '{start}'",
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": "50000",
    }
    rows = get_json(COT_URL + "?" + urllib.parse.urlencode(q))
    by_code = {}
    for r in rows:
        try:
            nl, ns = int(r["noncomm_positions_long_all"]), int(r["noncomm_positions_short_all"])
            cl, cs = int(r["comm_positions_long_all"]), int(r["comm_positions_short_all"])
            oi = int(r["open_interest_all"])
        except (KeyError, ValueError):
            continue
        by_code.setdefault(r["cftc_contract_market_code"], {})[r["report_date_as_yyyy_mm_dd"][:10]] = \
            [nl - ns, nl, ns, cl - cs, oi]
    markets = []
    for code, name, group in COT_MARKETS:
        pts = by_code.get(code)
        if not pts:
            print(f"  {name}: no data")
            continue
        markets.append({"code": code, "name": name, "group": group,
                        "obs": [[d] + v for d, v in sorted(pts.items())]})
    print(f"  {len(markets)} markets, {len(rows)} weekly rows")
    if not markets:
        raise RuntimeError("no COT rows returned")
    return save("cot.json", {"updated": iso(now_utc()), "markets": markets})


# ---------------------------------------------------------------- Bank of England


def fetch_boe():
    print("Bank of England")
    start = now_utc().date().replace(year=now_utc().year - BOE_YEARS)
    q = {"csv.x": "yes", "Datefrom": start.strftime("%d/%b/%Y"), "Dateto": "now",
         "SeriesCodes": ",".join(c for c, *_ in BOE_SERIES),
         "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N"}
    try:
        req = urllib.request.Request(BOE_URL + "?" + urllib.parse.urlencode(q),
                                     headers={"User-Agent": BROWSER_UA, "Accept": "text/csv,*/*"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
        if text.lstrip().startswith("<"):
            raise RuntimeError("the Bank returned a web page instead of data")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Bank of England: {e}") from e
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    header = lines[0].split(",")
    cols = {code: header.index(code) for code, *_ in BOE_SERIES if code in header}
    obs = {code: [] for code in cols}
    for line in lines[1:]:
        parts = line.split(",")
        try:
            day = dt.datetime.strptime(parts[0], "%d %b %Y").date().isoformat()
        except ValueError:
            continue
        for code, i in cols.items():
            v = num(parts[i]) if i < len(parts) else None
            if v is not None:
                obs[code].append([day, round(v, 4)])
    series = {code: {"name": name, "group": group, "unit": unit, "src": "Bank of England", "obs": obs[code]}
              for code, name, group, unit in BOE_SERIES if obs.get(code)}
    print(f"  {len(series)} series")
    if not series:
        raise RuntimeError("no Bank of England series in the reply")
    return save("boe.json", {"updated": iso(now_utc()), "errors": [], "series": series})


# ---------------------------------------------------------------- Finnhub


def finnhub(path, key, **params):
    req = urllib.request.Request(f"{FINNHUB_URL}/{path}?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": UA, "X-Finnhub-Token": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# US data releases worth watching (FRED release names). Finnhub's free plan has no
# economic calendar, so the release dates come from FRED instead.
KEY_RELEASES = {
    "Consumer Price Index": "US CPI inflation",
    "Employment Situation": "US jobs report (payrolls, unemployment)",
    "Gross Domestic Product": "US GDP",
    "Personal Income and Outlays": "US PCE inflation, income & spending",
    "Producer Price Index": "US PPI (producer prices)",
    "Advance Monthly Sales for Retail and Food Services": "US retail sales",
    "Unemployment Insurance Weekly Claims Report": "US jobless claims",
    "Job Openings and Labor Turnover Survey": "US job openings (JOLTS)",
    "G.17 Industrial Production and Capacity Utilization": "US industrial production",
    "ISM Manufacturing": "ISM manufacturing",
    "Surveys of Consumers": "UMich consumer sentiment",
    "New Residential Construction": "US housing starts",
    "Durable Goods": "US durable goods orders",
}


def fetch_release_dates(fred_key):
    today = now_utc().date()
    q = {"api_key": fred_key, "file_type": "json", "realtime_start": today.isoformat(),
         "realtime_end": (today + dt.timedelta(days=21)).isoformat(),
         "include_release_dates_with_no_data": "true", "limit": "1000", "sort_order": "asc"}
    rows = get_json("https://api.stlouisfed.org/fred/releases/dates?" + urllib.parse.urlencode(q))["release_dates"]
    out = []
    for r in rows:
        label = next((v for k, v in KEY_RELEASES.items() if r.get("release_name", "").startswith(k)), None)
        if label:
            out.append({"date": r["date"], "event": label, "country": "US"})
    seen, uniq = set(), []
    for r in out:
        if (r["date"], r["event"]) not in seen:
            seen.add((r["date"], r["event"]))
            uniq.append(r)
    return uniq


def fetch_calendar(key, fred_key=""):
    print("Finnhub calendars")
    today = now_utc().date()
    frm, to = today - dt.timedelta(days=3), today + dt.timedelta(days=10)
    old = load("calendar.json") or {}
    # Finnhub's economic calendar is not in the free plan, so only earnings come from Finnhub.
    out = {"earnings": old.get("earnings", []), "releases": old.get("releases", []), "notes": []}
    try:
        rows = finnhub("calendar/earnings", key, **{"from": frm.isoformat(), "to": to.isoformat()})
        rows = rows.get("earningsCalendar", []) if isinstance(rows, dict) else []
        out["earnings"] = sorted(
            [{"date": r.get("date"), "symbol": r.get("symbol"), "hour": r.get("hour"),
              "eps_est": r.get("epsEstimate"), "eps": r.get("epsActual"),
              "rev_est": r.get("revenueEstimate"), "rev": r.get("revenueActual"),
              "quarter": r.get("quarter"), "year": r.get("year")}
             for r in rows if r.get("symbol") in EARNINGS_WATCH],
            key=lambda r: (r["date"] or "", r["symbol"]))
        print(f"  earnings: {len(out['earnings'])} watched companies")
    except Exception as e:  # noqa: BLE001
        print(f"  earnings calendar failed: {e}")
        out["notes"].append(f"Earnings calendar: {e}")
    if fred_key:
        try:
            out["releases"] = fetch_release_dates(fred_key)
            print(f"  US release dates from FRED: {len(out['releases'])}")
        except Exception as e:  # noqa: BLE001
            print(f"  FRED release dates failed: {hide_key(str(e), fred_key)}")
    return save("calendar.json", dict(out, updated=iso(now_utc()), window=[frm.isoformat(), to.isoformat()]))


def fetch_forexfactory():
    """This week's economic calendar from Forex Factory's public feed (forecast and previous; no actuals)."""
    print("Forex Factory calendar")
    rows = json.loads(get(FF_URL).decode("utf-8"))
    events = []
    for r in rows:
        if r.get("country") not in FF_CURRENCIES or r.get("impact") not in ("High", "Medium", "Holiday"):
            continue
        when = parse_date(r.get("date"))
        events.append({"time": when, "ccy": r.get("country"), "event": (r.get("title") or "").strip(),
                       "impact": r.get("impact"), "forecast": r.get("forecast") or None,
                       "previous": r.get("previous") or None, "actual": r.get("actual") or None})
    events.sort(key=lambda e: e["time"] or "")
    print(f"  {len(events)} medium/high-impact events")
    if not events:
        raise RuntimeError("empty calendar")
    return save("ff.json", {"updated": iso(now_utc()), "events": events})


# ---------------------------------------------------------------- dates


def parse_date(s):
    if not s:
        return None
    try:
        t = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return iso(t.astimezone(dt.timezone.utc))


# ---------------------------------------------------------------- Fundamentals


def fetch_fundamentals(fred_key):
    import fundamentals
    print("Fundamentals")
    payload, errors = fundamentals.fetch_all(fred_key, load("fundamentals.json"))
    n = sum(len(c["items"]) for c in payload["countries"].values())
    print(f"  {n} indicators, {len(errors)} problems")
    if not n:
        raise RuntimeError("; ".join(errors[:3]) or "no data")
    payload["errors"] = errors
    return save("fundamentals.json", dict(updated=iso(now_utc()), **payload))


# ---------------------------------------------------------------- main


def main():
    global STATUS
    force = "--all" in sys.argv
    t = now_utc()
    STATUS = (load("status.json") or {}).get("sources", {})
    td_key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    fh_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    weekday = t.weekday() < 5
    mins = t.hour * 60 + t.minute

    # --- Twelve Data (the only source with a tight daily limit)
    if not td_key:
        print("TWELVEDATA_API_KEY is not set: skipping prices. Add it under Settings > Secrets.")
    else:
        batches = 0
        if (force or weekday and t.hour in PRICE_HOURS_UTC) and due("prices_fx", force):
            run_source("prices_fx", fetch_prices, td_key, FX_SYMBOLS)
            batches += 1
        us_open = weekday and US_SESSION_UTC[0] <= mins <= US_SESSION_UTC[1]
        if (force or us_open or load("prices.json") is None) and due("prices_us", force):
            if batches:
                time.sleep(TD_PAUSE)  # stay under 8 calls a minute
            run_source("prices_us", fetch_prices, td_key, US_SYMBOLS)
            batches += 1
        if force or (weekday and history_is_stale()) or load("price_history.json") is None:
            if batches:
                time.sleep(TD_PAUSE)
            run_source("price_history", fetch_price_history, td_key)

    # --- everything else is generous, so check more often
    if fred_key and due("fred", force):
        run_source("fred", fetch_fred, fred_key)
    elif not fred_key:
        print("FRED_API_KEY is not set: skipping FRED. Add it under Settings > Secrets.")
    if due("boe", force):
        run_source("boe", fetch_boe)
    if due("cot", force):
        run_source("cot", fetch_cot)
    if due("forexfactory", force):
        run_source("forexfactory", fetch_forexfactory)

    if not fh_key:
        print("FINNHUB_API_KEY is not set: skipping earnings dates. Add it under Settings > Secrets.")
    elif due("calendar", force) or load("calendar.json") is None:
        run_source("calendar", fetch_calendar, fh_key, fred_key)

    if due("fundamentals", force) or load("fundamentals.json") is None:
        run_source("fundamentals", fetch_fundamentals, fred_key)

    # Sources that were removed from the terminal: drop their old files and status.
    for gone in ("news", "finnhub_news", "research"):
        STATUS.pop(gone, None)
        (DATA / f"{gone}.json").unlink(missing_ok=True)

    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "status.json").write_text(json.dumps({"run": iso(t), "sources": STATUS}, separators=(",", ":")))
    print("status.json: saved")


if __name__ == "__main__":
    main()
