"""Economic indicators for the eight major currencies (the Fundamentals tab).

Each economy uses the best free source that is up to date:
  USD  FRED (Federal Reserve Bank of St. Louis), needs FRED_API_KEY
  GBP  Office for National Statistics, read through DBnomics (no key)
  EUR  European Central Bank data portal (no key)
  JPY  Statistics Bureau of Japan, read through DBnomics (no key)
  CHF  Swiss National Bank data portal (no key)
  CAD  Statistics Canada web data service (no key)
  AUD  Reserve Bank of Australia statistical tables (no key)
  All  OECD (growth, retail, trade, wages, confidence surveys) and BIS (policy rates), no key

Purchasing managers' indexes (PMIs) are owned by S&P Global and ISM and are not
free, so the OECD business and consumer confidence surveys stand in for them.

Official figures change at most once a day, so this runs every 6 hours and makes
about 55 requests. A source that fails keeps its previous data and the error is
shown on the page; the rest still update.
"""

import csv
import datetime as dt
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request

START = "2000-01-01"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

COUNTRIES = [
    ("USD", "United States"), ("EUR", "Euro area"), ("GBP", "United Kingdom"), ("JPY", "Japan"),
    ("CHF", "Switzerland"), ("CAD", "Canada"), ("AUD", "Australia"), ("NZD", "New Zealand"),
]
OECD_AREA = {"USD": "USA", "EUR": "EA20", "GBP": "GBR", "JPY": "JPN", "CHF": "CHE", "CAD": "CAN", "AUD": "AUS", "NZD": "NZL"}
BIS_AREA = {"USD": "US", "EUR": "XM", "GBP": "GB", "JPY": "JP", "CHF": "CH", "CAD": "CA", "AUD": "AU", "NZD": "NZ"}
GAPS = {
    "EUR": "Euro-area trade figures are not in the free OECD feed.",
    "CHF": "No free monthly core inflation or monthly unemployment rate; unemployment is the quarterly ILO measure.",
    "AUD": "Australia replaced monthly retail sales with a household spending indicator that has no free feed.",
    "NZD": "Stats NZ has no free data feed, so New Zealand figures come from the OECD and are mostly quarterly.",
}

# Groups, in the order the page shows them
GROUPS = ["Growth", "Inflation", "Labour", "Consumer", "Business", "Trade", "Rates"]


def I(cur, key, name, group, unit, src, ref, tf=None, dp=1, note=""):
    """One indicator. ref says where it comes from; tf is an optional transform:
    yoy / mom (percent change over 12 months or 1 period), chg (difference), k (divide by 1000)."""
    return {"id": f"{cur}.{key}", "cur": cur, "name": name, "group": group, "unit": unit,
            "src": src, "ref": ref, "tf": tf, "dp": dp, "note": note}


def oecd_common(cur, retail=True, trade=True, wages=True, ip="BTE", li=True, gdp=True):
    a = OECD_AREA[cur]
    out = []
    if gdp:
        out += [I(cur, "gdp_q", "GDP growth, q/q", "Growth", "%", "OECD", ("kei", a, "Q", "B1GQ_Q", "_T", "G1"), dp=2),
                I(cur, "gdp_y", "GDP growth, y/y", "Growth", "%", "OECD", ("kei", a, "Q", "B1GQ_Q", "_T", "GY"))]
    if ip:
        nm = "Industrial production, y/y" if ip == "BTE" else "Manufacturing output, y/y"
        out.append(I(cur, "ip", nm, "Growth", "%", "OECD", ("kei", a, "M", "PRVM", ip, "GY")))
    if li:
        out.append(I(cur, "cli", "Leading indicator (100 = trend)", "Growth", "index", "OECD", ("cli", a, "LI"), dp=2))
    if retail:
        out += [I(cur, "retail_m", "Retail sales volume, m/m", "Consumer", "%", "OECD", ("kei", a, "M", "TOVM", "G47", "G1")),
                I(cur, "retail_y", "Retail sales volume, y/y", "Consumer", "%", "OECD", ("kei", a, "M", "TOVM", "G47", "GY"))]
    if wages:
        out.append(I(cur, "wages", "Hourly earnings, y/y", "Labour", "%", "OECD", ("kei", a, "M", "H_EARN", "C", "GY")))
    out += [I(cur, "cci", "Consumer confidence (100 = average)", "Consumer", "index", "OECD", ("cli", a, "CCICP"), dp=2),
            I(cur, "bci", "Business confidence (100 = average)", "Business", "index", "OECD", ("cli", a, "BCICP"), dp=2)]
    if trade:
        out += [I(cur, "exports", "Exports, y/y", "Trade", "%", "OECD", ("kei", a, "M", "EX", "_T", "GY")),
                I(cur, "imports", "Imports, y/y", "Trade", "%", "OECD", ("kei", a, "M", "IM", "_T", "GY"))]
    return out


def policy(cur, name):
    return I(cur, "policy", name, "Rates", "%", "BIS", ("bis", BIS_AREA[cur]), dp=2)


def fred10(cur, sid):
    return I(cur, "y10", "10-year government bond yield", "Rates", "%", "FRED (OECD)", ("fred", sid, "lin", "m"), dp=2)


INDICATORS = (
    # ---- United States: official US data via FRED
    [I("USD", "gdp", "GDP growth, q/q annualised", "Growth", "%", "FRED", ("fred", "A191RL1Q225SBEA", "lin")),
     I("USD", "gdp_y", "Real GDP, y/y", "Growth", "%", "FRED", ("fred", "GDPC1", "pc1")),
     I("USD", "ip", "Industrial production, y/y", "Growth", "%", "FRED", ("fred", "INDPRO", "pc1")),
     I("USD", "cli", "Leading indicator (100 = trend)", "Growth", "index", "OECD", ("cli", "USA", "LI"), dp=2),
     I("USD", "cpi", "CPI inflation, y/y", "Inflation", "%", "FRED", ("fred", "CPIAUCSL", "pc1")),
     I("USD", "cpi_m", "CPI, m/m", "Inflation", "%", "FRED", ("fred", "CPIAUCSL", "pch"), dp=2),
     I("USD", "core_cpi", "Core CPI, y/y", "Inflation", "%", "FRED", ("fred", "CPILFESL", "pc1")),
     I("USD", "core_pce", "Core PCE prices, y/y", "Inflation", "%", "FRED", ("fred", "PCEPILFE", "pc1")),
     I("USD", "unemp", "Unemployment rate", "Labour", "%", "FRED", ("fred", "UNRATE", "lin")),
     I("USD", "nfp", "Nonfarm payrolls, change", "Labour", "k", "FRED", ("fred", "PAYEMS", "chg"), dp=0),
     I("USD", "ahe", "Average hourly earnings, y/y", "Labour", "%", "FRED", ("fred", "CES0500000003", "pc1")),
     I("USD", "claims", "Initial jobless claims", "Labour", "k", "FRED", ("fred", "ICSA", "lin"), tf="k", dp=0),
     I("USD", "jolts", "Job openings (JOLTS)", "Labour", "k", "FRED", ("fred", "JTSJOL", "lin"), dp=0),
     I("USD", "retail_m", "Retail sales, m/m", "Consumer", "%", "FRED", ("fred", "RSAFS", "pch")),
     I("USD", "retail_xauto", "Retail sales ex autos, m/m", "Consumer", "%", "FRED", ("fred", "RSFSXMV", "pch")),
     I("USD", "umich", "UMich consumer sentiment", "Consumer", "index", "FRED", ("fred", "UMCSENT", "lin")),
     I("USD", "cci", "Consumer confidence (100 = average)", "Consumer", "index", "OECD", ("cli", "USA", "CCICP"), dp=2),
     I("USD", "bci", "Business confidence (100 = average)", "Business", "index", "OECD", ("cli", "USA", "BCICP"), dp=2),
     I("USD", "housing", "Housing starts (annual rate)", "Business", "k", "FRED", ("fred", "HOUST", "lin"), dp=0),
     I("USD", "trade", "Trade balance", "Trade", "$bn", "FRED", ("fred", "BOPGSTB", "lin"), tf="k"),
     policy("USD", "Fed funds target (midpoint)"),
     I("USD", "y10", "10-year Treasury yield", "Rates", "%", "FRED", ("fred", "DGS10", "lin", "m"), dp=2)]
    # ---- United Kingdom: ONS via DBnomics
    + [I("GBP", "gdp_q", "GDP growth, q/q", "Growth", "%", "ONS", ("dbn", "ONS/QNA/IHYQ.Q")),
       I("GBP", "gdp_m", "Monthly GDP, m/m", "Growth", "%", "ONS", ("dbn", "ONS/MGDP/ECYX.M")),
       I("GBP", "ip", "Industrial production, y/y", "Growth", "%", "ONS", ("dbn", "ONS/DIOP/K222.M"), tf="yoy"),
       I("GBP", "cli", "Leading indicator (100 = trend)", "Growth", "index", "OECD", ("cli", "GBR", "LI"), dp=2),
       I("GBP", "cpi", "CPI inflation, y/y", "Inflation", "%", "ONS", ("dbn", "ONS/MM23/D7G7.M")),
       I("GBP", "core_cpi", "Core CPI, y/y", "Inflation", "%", "ONS", ("dbn", "ONS/MM23/DKO8.M")),
       I("GBP", "services_cpi", "Services CPI, y/y", "Inflation", "%", "ONS", ("dbn", "ONS/MM23/D7NN.M")),
       I("GBP", "unemp", "Unemployment rate (3 months)", "Labour", "%", "ONS", ("dbn", "ONS/LMS/MGSX.M")),
       I("GBP", "awe", "Average weekly earnings, total pay, y/y (3m)", "Labour", "%", "ONS", ("dbn", "ONS/LMS/KAC3.M")),
       I("GBP", "awe_reg", "Average weekly earnings, regular pay, y/y (3m)", "Labour", "%", "ONS", ("dbn", "ONS/LMS/KAI9.M")),
       I("GBP", "retail_m", "Retail sales incl. fuel, m/m", "Consumer", "%", "ONS", ("dbn", "ONS/DRSI/J5EK.M"), tf="mom"),
       I("GBP", "retail_y", "Retail sales incl. fuel, y/y", "Consumer", "%", "ONS", ("dbn", "ONS/DRSI/J5EK.M"), tf="yoy"),
       I("GBP", "retail_xf_m", "Retail sales excl. fuel, m/m", "Consumer", "%", "ONS", ("dbn", "ONS/DRSI/J467.M"), tf="mom"),
       I("GBP", "retail_xf_y", "Retail sales excl. fuel, y/y", "Consumer", "%", "ONS", ("dbn", "ONS/DRSI/J467.M"), tf="yoy"),
       I("GBP", "cci", "Consumer confidence (100 = average)", "Consumer", "index", "OECD", ("cli", "GBR", "CCICP"), dp=2),
       I("GBP", "bci", "Business confidence (100 = average)", "Business", "index", "OECD", ("cli", "GBR", "BCICP"), dp=2),
       I("GBP", "trade", "Trade balance", "Trade", "£bn", "ONS", ("dbn", "ONS/MRET/IKBJ.M"), tf="k", dp=2),
       policy("GBP", "Bank Rate"),
       fred10("GBP", "IRLTLT01GBM156N")]
    # ---- Euro area: ECB, plus OECD
    + [I("EUR", "gdp_q", "GDP growth, q/q", "Growth", "%", "OECD", ("kei", "EA20", "Q", "B1GQ_Q", "_T", "G1"), dp=2),
       I("EUR", "gdp_y", "GDP growth, y/y", "Growth", "%", "OECD", ("kei", "EA20", "Q", "B1GQ_Q", "_T", "GY")),
       I("EUR", "ip", "Industrial production, y/y", "Growth", "%", "OECD", ("kei", "EA20", "M", "PRVM", "BTE", "GY")),
       I("EUR", "cpi", "HICP inflation, y/y", "Inflation", "%", "ECB", ("ecb", "HICP/M.U2.N.000000.4D0.ANR", "ICP/M.U2.N.000000.4.ANR")),
       I("EUR", "core_cpi", "Core HICP, y/y", "Inflation", "%", "ECB", ("ecb", "HICP/M.U2.N.XEF000.4D0.ANR", "ICP/M.U2.N.XEF000.4.ANR"),
         note="Excludes energy, food, alcohol and tobacco"),
       I("EUR", "services_cpi", "Services HICP, y/y", "Inflation", "%", "ECB", ("ecb", "HICP/M.U2.N.SERV00.4D0.ANR", "ICP/M.U2.N.SERV00.4.ANR")),
       I("EUR", "unemp", "Unemployment rate", "Labour", "%", "ECB", ("ecb", "LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T")),
       I("EUR", "wages", "Hourly earnings, y/y", "Labour", "%", "OECD", ("kei", "EA20", "Q", "H_EARN", "C", "GY")),
       I("EUR", "retail_m", "Retail sales volume, m/m", "Consumer", "%", "OECD", ("kei", "EA20", "M", "TOVM", "G47", "G1")),
       I("EUR", "retail_y", "Retail sales volume, y/y", "Consumer", "%", "OECD", ("kei", "EA20", "M", "TOVM", "G47", "GY")),
       I("EUR", "cci", "Consumer confidence (100 = average)", "Consumer", "index", "OECD", ("cli", "EA20", "CCICP"), dp=2),
       I("EUR", "bci", "Business confidence (100 = average)", "Business", "index", "OECD", ("cli", "EA20", "BCICP"), dp=2),
       I("EUR", "policy", "ECB deposit rate", "Rates", "%", "ECB", ("ecb", "FM/D.U2.EUR.4F.KR.DFR.LEV"), dp=2),
       I("EUR", "y10", "10-year government bond yield (euro area)", "Rates", "%", "ECB", ("ecb", "FM/M.U2.EUR.4F.BB.U2_10Y.YLD"), dp=2)]
    # ---- Japan: Statistics Bureau via DBnomics, plus OECD
    + oecd_common("JPY", wages=True)
    + [I("JPY", "cpi", "CPI inflation, y/y", "Inflation", "%", "Statistics Bureau of Japan", ("dbn", "STATJP/CPIm/001"), tf="yoy"),
       I("JPY", "core_cpi", "Core CPI (ex fresh food), y/y", "Inflation", "%", "Statistics Bureau of Japan", ("dbn", "STATJP/CPIm/733"), tf="yoy"),
       I("JPY", "corecore_cpi", "CPI ex fresh food and energy, y/y", "Inflation", "%", "Statistics Bureau of Japan", ("dbn", "STATJP/CPIm/740"), tf="yoy"),
       I("JPY", "unemp", "Unemployment rate", "Labour", "%", "Statistics Bureau of Japan", ("dbn", "STATJP/MIm/M.UR.B.PCT.SA")),
       policy("JPY", "BoJ policy rate"),
       fred10("JPY", "IRLTLT01JPM156N")]
    # ---- Switzerland: SNB, plus OECD
    + oecd_common("CHF", wages=False, ip="C", li=False)
    + [I("CHF", "cpi", "CPI inflation, y/y", "Inflation", "%", "SNB", ("snb", "plkopr", "VVP")),
       I("CHF", "unemp", "Unemployment rate (ILO, quarterly)", "Labour", "%", "OECD", ("une", "CHE", "Q")),
       policy("CHF", "SNB policy rate"),
       fred10("CHF", "IRLTLT01CHM156N")]
    # ---- Canada: Statistics Canada, plus OECD
    + oecd_common("CAD")
    + [I("CAD", "gdp_m", "Monthly GDP, m/m", "Growth", "%", "Statistics Canada", ("statcan", 65201210), tf="mom", dp=2),
       I("CAD", "cpi", "CPI inflation, y/y", "Inflation", "%", "Statistics Canada", ("statcan", 41690973), tf="yoy"),
       I("CAD", "cpi_trim", "CPI-trim, y/y", "Inflation", "%", "Statistics Canada", ("statcan", 108785713)),
       I("CAD", "cpi_median", "CPI-median, y/y", "Inflation", "%", "Statistics Canada", ("statcan", 108785714)),
       I("CAD", "unemp", "Unemployment rate", "Labour", "%", "Statistics Canada", ("statcan", 2062815)),
       I("CAD", "jobs", "Employment, change", "Labour", "k", "Statistics Canada", ("statcan", 2062811), tf="chg", dp=1),
       policy("CAD", "BoC policy rate"),
       fred10("CAD", "IRLTLT01CAM156N")]
    # ---- Australia: RBA tables, plus OECD
    + oecd_common("AUD", retail=False, wages=False, ip=None)
    + [I("AUD", "cpi", "CPI inflation, y/y (monthly)", "Inflation", "%", "OECD", ("prices", "AUS", "M", "_T")),
       I("AUD", "trimmed", "Trimmed mean inflation, y/y", "Inflation", "%", "RBA", ("rba", "g1", "trimmed mean", "year-ended")),
       I("AUD", "unemp", "Unemployment rate", "Labour", "%", "RBA", ("rba", "h5", "unemployment rate", "seasonally adjusted")),
       I("AUD", "jobs", "Employment, change", "Labour", "k", "RBA", ("rba", "h5", "employment", "seasonally adjusted"), tf="chg", dp=1),
       policy("AUD", "RBA cash rate"),
       fred10("AUD", "IRLTLT01AUM156N")]
    # ---- New Zealand: OECD (quarterly)
    + oecd_common("NZD", ip=None, li=False)
    + [I("NZD", "cpi", "CPI inflation, y/y (quarterly)", "Inflation", "%", "OECD", ("prices", "NZL", "Q", "_T")),
       I("NZD", "core_cpi", "CPI ex food and energy, y/y", "Inflation", "%", "OECD", ("prices", "NZL", "Q", "_TXCP01_NRG")),
       I("NZD", "unemp", "Unemployment rate (quarterly)", "Labour", "%", "OECD", ("une", "NZL", "Q")),
       policy("NZD", "RBNZ official cash rate"),
       fred10("NZD", "IRLTLT01NZM156N")]
)
# New Zealand retail and wages are quarterly in the OECD feed
for _i in INDICATORS:
    if _i["cur"] == "NZD" and _i["ref"][0] == "kei" and _i["ref"][3] in ("TOVM", "H_EARN"):
        _i["ref"] = ("kei", "NZL", "Q") + _i["ref"][3:]
        _i["name"] = _i["name"].replace("m/m", "q/q")
    if _i["cur"] == "CHF" and _i["ref"][0] == "kei" and _i["ref"][3] == "H_EARN":
        _i["ref"] = ("kei", "CHE", "Q") + _i["ref"][3:]


# ---------------------------------------------------------------- fetching

def _get(url, timeout=90, data=None, headers=None):
    h = {"User-Agent": BROWSER_UA, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # drop NaN


def _date(p):
    """'2026-10' / '2026-Q3' / '2026-10-01' / '2026' -> first day of the period."""
    p = str(p).strip()
    if "-Q" in p:
        y, q = p.split("-Q")
        return f"{y}-{(int(q) - 1) * 3 + 1:02d}-01"
    if len(p) == 7:
        return p + "-01"
    if len(p) == 4:
        return p + "-01-01"
    return p[:10]


def fred_series(key, sid, units, freq=None):
    q = {"series_id": sid, "api_key": key, "file_type": "json", "observation_start": START, "units": units}
    if freq:
        q.update({"frequency": freq, "aggregation_method": "eop"})
    obs = json.loads(_get("https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(q)))["observations"]
    return [[o["date"], v] for o in obs if (v := _num(o["value"])) is not None]


def dbnomics(sid):
    doc = json.loads(_get(f"https://api.db.nomics.world/v22/series/{sid}?observations=1"))["series"]["docs"][0]
    return [[_date(p), v] for p, x in zip(doc["period"], doc["value"]) if (v := _num(x)) is not None and _date(p) >= START]


def ecb(*keys):
    """Several keys are joined: later keys fill dates the earlier ones lack (old and new datasets)."""
    out, errs = {}, []
    for k in reversed(keys):
        try:
            text = _get(f"https://data-api.ecb.europa.eu/service/data/{k}?format=csvdata&detail=dataonly&startPeriod=2000-01").decode("utf-8-sig")
            for r in csv.DictReader(io.StringIO(text)):
                v = _num(r.get("OBS_VALUE"))
                if v is not None:
                    out[_date(r["TIME_PERIOD"])] = v
        except Exception as e:  # noqa: BLE001
            errs.append(f"{k}: {e}")
    if not out:
        raise RuntimeError("; ".join(errs) or "no data")
    return sorted([d, v] for d, v in out.items())


OECD_QUERIES = {
    "kei": "OECD.SDD.STES,DSD_KEI@DF_KEI,/{a}.M+Q.B1GQ_Q+PRVM+TOVM+H_EARN+EX+IM.GR..Y.GY+G1",
    "cli": "OECD.SDD.STES,DSD_STES@DF_CLI,/{a}.M.BCICP+CCICP+LI...AA...",
    "prices": "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,/{a}.M+Q.N.CPI.PA._T+_TXCP01_NRG.N.GY",
    "une": "OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,/{a}..._Z.Y._T.Y_GE15..M+Q",
}


def oecd(kind, areas):
    url = "https://sdmx.oecd.org/public/rest/data/" + OECD_QUERIES[kind].format(a="+".join(areas)) + "?startPeriod=2000-01&format=csvfile"
    for attempt in range(2):
        try:
            text = _get(url, timeout=120).decode("utf-8-sig")
            break
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt == 0:
                time.sleep(70)   # the OECD limits how often one address may ask
                continue
            raise
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        v = _num(r.get("OBS_VALUE"))
        if v is None:
            continue
        if kind == "kei":
            k = (r["REF_AREA"], r["FREQ"], r["MEASURE"], r["ACTIVITY"], r["TRANSFORMATION"])
        elif kind == "cli":
            k = (r["REF_AREA"], r["MEASURE"])
        elif kind == "prices":
            k = (r["REF_AREA"], r["FREQ"], r["EXPENDITURE"])
        else:
            k = (r["REF_AREA"], r["FREQ"])
        out.setdefault(k, []).append([_date(r["TIME_PERIOD"]), v])
    return {k: sorted(v) for k, v in out.items()}


def bis(areas):
    text = _get("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D." + "+".join(areas)
                + f"?startPeriod={START}&format=csv&detail=dataonly").decode("utf-8-sig")
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        v = _num(r.get("OBS_VALUE"))
        if v is not None:
            out.setdefault(r["REF_AREA"], []).append([r["TIME_PERIOD"][:10], v])
    return {k: sorted(v) for k, v in out.items()}


def statcan(vectors):
    body = json.dumps([{"vectorId": v, "latestN": 330} for v in vectors]).encode()
    reply = json.loads(_get("https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods",
                            data=body, headers={"Content-Type": "application/json"}))
    out = {}
    for item in reply:
        o = item.get("object") or {}
        if item.get("status") == "SUCCESS":
            out[o["vectorId"]] = sorted([p["refPer"][:10], v] for p in o.get("vectorDataPoint", [])
                                        if (v := _num(p.get("value"))) is not None and p["refPer"] >= START)
    return out


def rba_table(name):
    """RBA statistical table CSV -> list of columns {title, type, pts}."""
    text = _get(f"https://www.rba.gov.au/statistics/tables/csv/{name}-data.csv").decode("utf-8-sig", "replace")
    rows = list(csv.reader(io.StringIO(text)))
    meta = {r[0].strip(): r for r in rows if r and r[0].strip() in ("Title", "Type", "Series ID", "Frequency")}
    titles = meta.get("Title", [])
    cols = [{"title": titles[i].strip(), "type": (meta.get("Type") or [""] * len(titles))[i].strip() if i < len(meta.get("Type", [])) else "",
             "pts": []} for i in range(len(titles))]
    for r in rows:
        if not r:
            continue
        d = None
        for f in ("%d-%b-%Y", "%b-%Y", "%d/%m/%Y"):
            try:
                d = dt.datetime.strptime(r[0].strip(), f).date()
                break
            except ValueError:
                pass
        if not d or d.isoformat() < START:
            continue
        for i in range(1, min(len(r), len(cols))):
            v = _num(r[i])
            if v is not None:
                cols[i]["pts"].append([d.replace(day=1).isoformat(), v])
    return cols[1:]


def rba_pick(cols, title_words, type_word):
    """The column whose title matches best: exact title first, else one containing all the words."""
    want = title_words.lower()
    exact = [c for c in cols if c["title"].lower() == want and type_word in c["type"].lower() and c["pts"]]
    loose = [c for c in cols if all(w in c["title"].lower() for w in want.split()) and type_word in (c["title"] + c["type"]).lower() and c["pts"]]
    pick = exact or loose
    if not pick:
        raise RuntimeError(f"no RBA column for {title_words}")
    return max(pick, key=lambda c: (c["pts"][-1][0], len(c["pts"])))["pts"]


def snb_cube(cube, item):
    text = _get(f"https://data.snb.ch/api/cube/{cube}/data/csv/en?fromDate=2000-01").decode("utf-8-sig")
    out = []
    for r in csv.reader(io.StringIO(text), delimiter=";"):
        if len(r) == 3 and r[1] == item:
            v = _num(r[2])
            if v is not None:
                out.append([_date(r[0]), v])
    return sorted(out)


# ---------------------------------------------------------------- transforms

def transform(pts, tf):
    if tf == "k":
        return [[d, v / 1000] for d, v in pts]
    if tf in ("yoy", "mom"):
        by = {d: v for d, v in pts}
        out = []
        for i in range(1, len(pts)):
            d, v = pts[i]
            # match on the date a year (or a period) earlier, so gaps don't shift the comparison
            prev = pts[i - 1]
            if tf == "yoy":
                y, m, dd = d.split("-")
                key = f"{int(y) - 1}-{m}-{dd}"
                prev = [key, by[key]] if key in by else None
            if prev and prev[1]:
                out.append([d, (v / prev[1] - 1) * 100])
        return out
    if tf == "chg":
        return [[pts[i][0], pts[i][1] - pts[i - 1][1]] for i in range(1, len(pts))]
    return pts


def monthly(pts):
    """Daily data -> one point per month (the last one), plus the newest day."""
    out = {}
    for d, v in pts:
        out[d[:7]] = [d, v]
    return list(out.values())


def freq_of(pts):
    if len(pts) < 3:
        return "M"
    gap = (dt.date.fromisoformat(pts[-1][0]) - dt.date.fromisoformat(pts[-3][0])).days / 2
    return "W" if gap < 10 else "Q" if gap > 60 else "M"


# ---------------------------------------------------------------- main entry

def fetch_all(fred_key, old=None):
    """Return (payload, errors). Indicators that fail keep their old data."""
    old_items = {i["id"]: i for c in (old or {}).get("countries", {}).values() for i in c.get("items", [])}
    raw, errors = {}, []

    def note(msg):
        print("  " + msg)
        errors.append(msg)

    # batch sources first
    areas = list(OECD_AREA.values())
    oecd_data = {}
    for n, kind in enumerate(OECD_QUERIES):
        if n:
            time.sleep(20)   # be gentle with the OECD's per-address limit
        try:
            oecd_data[kind] = oecd(kind, areas)
            print(f"  OECD {kind}: {len(oecd_data[kind])} series")
        except Exception as e:  # noqa: BLE001
            note(f"OECD {kind}: {str(e)[:120]}")
    try:
        bis_data = bis(list(BIS_AREA.values()))
    except Exception as e:  # noqa: BLE001
        bis_data = None
        note(f"BIS policy rates: {str(e)[:120]}")
    sc_ids = [i["ref"][1] for i in INDICATORS if i["ref"][0] == "statcan"]
    try:
        sc_data = statcan(sc_ids)
    except Exception as e:  # noqa: BLE001
        sc_data = None
        note(f"Statistics Canada: {str(e)[:120]}")
    rba_cache = {}

    for ind in INDICATORS:
        ref, kind = ind["ref"], ind["ref"][0]
        try:
            if kind == "fred":
                if not fred_key:
                    raise RuntimeError("FRED_API_KEY is not set")
                pts = fred_series(fred_key, *ref[1:])
                time.sleep(0.6)
            elif kind == "dbn":
                pts = dbnomics(ref[1])
            elif kind == "ecb":
                pts = ecb(*ref[1:])
                if "/D." in ref[1]:
                    pts = monthly(pts)
            elif kind in ("kei", "cli", "prices", "une"):
                if kind not in oecd_data:
                    raise RuntimeError("OECD unavailable this run")
                pts = oecd_data[kind].get(tuple(ref[1:]), [])
            elif kind == "bis":
                if bis_data is None:
                    raise RuntimeError("BIS unavailable this run")
                pts = monthly(bis_data.get(ref[1], []))
            elif kind == "statcan":
                if sc_data is None:
                    raise RuntimeError("Statistics Canada unavailable this run")
                pts = sc_data.get(ref[1], [])
            elif kind == "rba":
                if ref[1] not in rba_cache:
                    rba_cache[ref[1]] = rba_table(ref[1])
                pts = rba_pick(rba_cache[ref[1]], ref[2], ref[3])
            elif kind == "snb":
                pts = snb_cube(ref[1], ref[2])
            else:
                raise RuntimeError(f"unknown source {kind}")
            pts = transform(pts, ind["tf"])
            pts = [[d, round(v, 4)] for d, v in pts if d >= START]
            if len(pts) < 2:
                raise RuntimeError("no data returned")
            raw[ind["id"]] = pts
        except Exception as e:  # noqa: BLE001
            msg = str(e).replace(fred_key, "***") if fred_key else str(e)
            note(f"{ind['id']} ({ind['src']}): {msg[:140]}")
            if ind["id"] in old_items:
                raw[ind["id"]] = old_items[ind["id"]]["pts"]

    countries = {}
    for cur, name in COUNTRIES:
        items = []
        for ind in INDICATORS:
            if ind["cur"] != cur or ind["id"] not in raw:
                continue
            pts = raw[ind["id"]]
            items.append({"id": ind["id"], "name": ind["name"], "group": ind["group"], "unit": ind["unit"],
                          "dp": ind["dp"], "src": ind["src"], "freq": freq_of(pts), "note": ind["note"], "pts": pts})
        items.sort(key=lambda i: GROUPS.index(i["group"]))
        countries[cur] = {"name": name, "gap": GAPS.get(cur, ""), "items": items}
    return {"groups": GROUPS, "countries": countries}, errors
