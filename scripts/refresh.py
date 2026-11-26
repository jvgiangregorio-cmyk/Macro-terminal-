"""Fetch fresh market data for the Macro Terminal and save it as JSON files.

GitHub runs this on a schedule (see .github/workflows/refresh.yml).
It reads the two API keys from environment variables, which GitHub fills in
from the repository's Secrets. The keys are never written to any file.

Sources
  Twelve Data  stock ETFs, currencies, gold, silver, oil, bitcoin
  FRED         Treasury yields, Fed funds, spreads, VIX, dollar, economic data
  Bank of England  UK Bank Rate, SONIA, gilt yields, sterling (no key needed)
  Finnhub      economic calendar, earnings dates, market news
  CFTC         Commitments of Traders futures positioning (no key needed)
  RSS feeds    headlines (no key needed)

Twelve Data's free plan allows 800 calls a day and 8 a minute, where each
symbol counts as one call. This script asks for prices only on weekdays
between 06:00 and 21:59 UTC (about 32 runs, 16 symbols each = ~512 calls),
plus one daily history download (16 calls). That leaves headroom for manual runs.

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
import xml.etree.ElementTree as ET
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
    ("USD/CAD", "Canadian dollar", "FX"),
    ("XAU/USD", "Gold", "Commodities"),
    ("SLV", "Silver (SLV ETF)", "Commodities"),   # XAG/USD is not on the free plan
    ("USO", "Oil (USO ETF)", "Commodities"),      # WTI/USD is not on the free plan
    ("BTC/USD", "Bitcoin", "Commodities"),
]
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

NEWS_FEEDS = [
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB", "https://www.ecb.europa.eu/rss/press.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
]
NEWS_PER_SOURCE = 15

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
        return
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    print(f"  {name}: saved")


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


def td_batches(endpoint, key, **params):
    out, errors = {}, []
    syms = [s for s, _, _ in TD_SYMBOLS]
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


def fetch_prices(key):
    print("Twelve Data prices")
    raw, errors = td_batches("quote", key)
    old = {q["symbol"]: q for q in (load("prices.json") or {}).get("quotes", [])}
    quotes = []
    for sym, name, group in TD_SYMBOLS:
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
    if not any("price" in q for q in quotes):
        print("  no prices at all; keeping the old file")
        if old:
            return
    save("prices.json", {"updated": iso(now_utc()), "errors": errors, "quotes": quotes})


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
    if series:
        save("price_history.json", {"updated": iso(now_utc()), "errors": errors, "series": series})


def history_is_stale():
    h = load("price_history.json")
    if not h or not h.get("updated"):
        return True
    last = dt.datetime.fromisoformat(h["updated"].replace("Z", "+00:00"))
    return now_utc() - last > dt.timedelta(hours=20)


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
        save("fred.json", {"updated": iso(now_utc()), "errors": errors, "series": series})


# ---------------------------------------------------------------- CFTC COT


def fetch_cot():
    """Weekly positioning. Each point: [date, spec net, spec long, spec short, commercial net, open interest].

    "Spec" is the CFTC's non-commercial group (mostly hedge funds and other
    speculators). Net = long contracts minus short contracts.
    """
    print("CFTC Commitments of Traders")
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
    try:
        rows = get_json(COT_URL + "?" + urllib.parse.urlencode(q))
    except Exception as e:  # noqa: BLE001
        print(f"  failed: {e}")
        return
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
    if markets:
        save("cot.json", {"updated": iso(now_utc()), "markets": markets})


def cot_due(t):
    """The report comes out weekly (usually Friday 15:30 US Eastern), so checking every 3 hours is plenty."""
    return load("cot.json") is None or (t.hour % 3 == 0 and t.minute < 30)


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
        print(f"  failed: {e}")
        old = load("boe.json")
        if old is not None:
            old["errors"] = [str(e)[:200]]
            save("boe.json", old)
        return
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
    if series:
        save("boe.json", {"updated": iso(now_utc()), "errors": [], "series": series})


# ---------------------------------------------------------------- Finnhub


def finnhub(path, key, **params):
    req = urllib.request.Request(f"{FINNHUB_URL}/{path}?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": UA, "X-Finnhub-Token": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_finnhub_news(key):
    print("Finnhub news")
    items = []
    for cat in ("general", "forex"):
        try:
            for n in finnhub("news", key, category=cat)[:40]:
                url, title = n.get("url") or "", (n.get("headline") or "").strip()
                if title and url.startswith("https://"):
                    when = iso(dt.datetime.fromtimestamp(n["datetime"], dt.timezone.utc)) if n.get("datetime") else None
                    items.append({"source": n.get("source") or "Finnhub", "title": title, "link": url,
                                  "published": when, "via": "Finnhub"})
        except Exception as e:  # noqa: BLE001
            print(f"  {cat} failed: {e}")
    print(f"  {len(items)} headlines")
    return items


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
    out = {"economic": old.get("economic", []), "earnings": old.get("earnings", []), "notes": []}
    try:
        rows = finnhub("calendar/economic", key, **{"from": frm.isoformat(), "to": to.isoformat()})
        rows = rows.get("economicCalendar", []) if isinstance(rows, dict) else []
        out["economic"] = sorted(
            [{"time": r.get("time"), "country": r.get("country"), "event": r.get("event"),
              "impact": r.get("impact"), "actual": r.get("actual"), "estimate": r.get("estimate"),
              "prev": r.get("prev"), "unit": r.get("unit")}
             for r in rows if r.get("country") in CAL_COUNTRIES and r.get("impact") in ("high", "medium")],
            key=lambda r: r["time"] or "")
        print(f"  economic: {len(out['economic'])} events")
    except urllib.error.HTTPError as e:
        msg = "not included in Finnhub's free plan" if e.code in (401, 403) else f"HTTP {e.code}"
        print(f"  economic calendar: {msg}")
        out["economic"] = []
    except Exception as e:  # noqa: BLE001
        print(f"  economic calendar failed: {e}")
        out["notes"].append(f"Economic calendar: {e}")
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
    if not out["economic"] and fred_key:
        try:
            out["releases"] = fetch_release_dates(fred_key)
            print(f"  US release dates from FRED: {len(out['releases'])}")
        except Exception as e:  # noqa: BLE001
            print(f"  FRED release dates failed: {hide_key(str(e), fred_key)}")
    save("calendar.json", dict(out, updated=iso(now_utc()), window=[frm.isoformat(), to.isoformat()]))


# ---------------------------------------------------------------- news


def text_of(el, *names):
    for n in names:
        found = el.find(n)
        if found is not None:
            if found.text and found.text.strip():
                return found.text.strip()
            if found.get("href"):
                return found.get("href")
    return ""


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


def fetch_news(extra=()):
    print("News")
    items, errors = list(extra), []
    atom = "{http://www.w3.org/2005/Atom}"
    for source, url in NEWS_FEEDS:
        try:
            root = ET.fromstring(get(url))
            entries = root.findall(".//item") or root.findall(f".//{atom}entry")
            n = 0
            for e in entries:
                title = text_of(e, "title", f"{atom}title")
                link = text_of(e, "link", f"{atom}link")
                when = parse_date(text_of(e, "pubDate", f"{atom}updated", f"{atom}published",
                                          "{http://purl.org/dc/elements/1.1/}date"))
                if title and link.startswith("https://"):
                    items.append({"source": source, "title": title, "link": link, "published": when})
                    n += 1
                if n >= NEWS_PER_SOURCE:
                    break
            print(f"  {source}: {n} headlines")
        except Exception as e:  # noqa: BLE001
            print(f"  {source} failed: {e}")
            errors.append(f"{source}: {e}")
    if not items:
        return
    items.sort(key=lambda i: i["published"] or "", reverse=True)
    seen, unique = set(), []
    for i in items:
        k = i["title"].lower()[:80]
        if k not in seen:
            seen.add(k)
            unique.append(i)
    save("news.json", {"updated": iso(now_utc()), "errors": errors, "items": unique[:120]})


# ---------------------------------------------------------------- main


def main():
    force = "--all" in sys.argv
    t = now_utc()
    td_key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    fred_key = os.environ.get("FRED_API_KEY", "").strip()
    weekday = t.weekday() < 5

    if not td_key:
        print("TWELVEDATA_API_KEY is not set: skipping prices. Add it under Settings > Secrets.")
    else:
        did_prices = False
        if force or (weekday and t.hour in PRICE_HOURS_UTC):
            fetch_prices(td_key)
            did_prices = True
        else:
            print("Outside price hours: skipping Twelve Data prices to save free-plan calls")
        if force or (weekday and history_is_stale()) or load("price_history.json") is None:
            if did_prices:
                time.sleep(TD_PAUSE)  # stay under 8 calls a minute
            fetch_price_history(td_key)

    if not fred_key:
        print("FRED_API_KEY is not set: skipping FRED. Add it under Settings > Secrets.")
    else:
        fetch_fred(fred_key)

    if force or cot_due(t):
        fetch_cot()

    if force or t.minute < 30 or load("boe.json") is None:  # hourly is plenty
        fetch_boe()

    fh_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    fh_news = []
    if not fh_key:
        print("FINNHUB_API_KEY is not set: skipping Finnhub. Add it under Settings > Secrets.")
    else:
        fh_news = fetch_finnhub_news(fh_key)
        if force or cot_due(t) or load("calendar.json") is None:
            fetch_calendar(fh_key, fred_key)

    fetch_news(fh_news)


if __name__ == "__main__":
    main()
