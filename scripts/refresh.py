"""Fetch fresh market data for the Macro Terminal and save it as JSON files.

GitHub runs this on a schedule (see .github/workflows/refresh.yml).
It reads the two API keys from environment variables, which GitHub fills in
from the repository's Secrets. The keys are never written to any file.

Sources
  Twelve Data  stock ETFs, currencies, gold, silver, oil, bitcoin
  FRED         Treasury yields, Fed funds, spreads, VIX, dollar, economic data
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
    ("XAG/USD", "Silver", "Commodities"),
    ("WTI/USD", "WTI crude oil", "Commodities"),
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
    data = get_json(f"https://api.twelvedata.com/{endpoint}?" + urllib.parse.urlencode(q))
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


def fetch_news():
    print("News")
    items, errors = [], []
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
    save("news.json", {"updated": iso(now_utc()), "errors": errors, "items": items[:80]})


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

    fetch_news()


if __name__ == "__main__":
    main()
