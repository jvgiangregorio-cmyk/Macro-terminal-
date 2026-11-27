"""Temporary: check which candidate series exist and are current. Removed before merge."""
import csv, io, json, os, urllib.request, urllib.parse, collections
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
def get(url, t=60, data=None, hdr=None):
    h = {"User-Agent": UA, "Accept": "*/*"}; h.update(hdr or {})
    r = urllib.request.Request(url, headers=h, data=data)
    with urllib.request.urlopen(r, timeout=t) as f: return f.read()
def oecd(label, url, keys):
    try:
        b = get(url).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(b)))
        last = {}
        for r in rows:
            k = tuple(r.get(x, "") for x in keys)
            if k not in last or r["TIME_PERIOD"] > last[k][0]: last[k] = (r["TIME_PERIOD"], r["OBS_VALUE"])
        print(f"## OECD {label} rows={len(rows)} cols={list(rows[0].keys())[:30] if rows else ''}")
        for k, v in sorted(last.items()): print("   ", " | ".join(k), "->", v)
    except Exception as e: print(f"## OECD {label} ERR {str(e)[:200]}")
A = "USA+GBR+EA20+JPN+CHE+CAN+AUS+NZL"
oecd("KEI", f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_KEI@DF_KEI,/{A}.......?startPeriod=2025-01&format=csvfile", ["REF_AREA","FREQ","MEASURE","UNIT_MEASURE","ACTIVITY","ADJUSTMENT","TRANSFORMATION"])
oecd("PRICES", f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,/{A}..N.CPI.PA._T+_TXCP01_NRG.N.GY?startPeriod=2025-01&format=csvfile", ["REF_AREA","FREQ","METHODOLOGY","EXPENDITURE","TRANSFORMATION"])
oecd("BCICCI", f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI,/{A}.M.BCICP+CCICP+LI...AA...?startPeriod=2025-01&format=csvfile", ["REF_AREA","MEASURE","ADJUSTMENT","METHODOLOGY"])
oecd("UNEMP", f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,/{A}..._Z.Y._T.Y_GE15..M+Q?startPeriod=2025-01&format=csvfile", ["REF_AREA","FREQ","MEASURE","UNIT_MEASURE","ADJUSTMENT"])
oecd("QNA", f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA,/Q..{A}.S1..B1GQ._Z...USD_PPP+XDC.LR.GY+G1.?startPeriod=2025-Q1&format=csvfile", ["REF_AREA","TRANSACTION","UNIT_MEASURE","PRICE_BASE","TRANSFORMATION","ADJUSTMENT"])
def raw(url, n=400, **kw):
    try: b = get(url, **kw); print(f"RAW OK {len(b)} {url[:140]}\n   {b[:n]!r}\n   ...{b[-300:]!r}")
    except Exception as e: print(f"RAW ERR {url[:140]} {str(e)[:120]}")
raw("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.US+GB+JP+CH+CA+AU+NZ+XM?startPeriod=2026-10-01&format=csv", 300)
for k in ["LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T","STS/M.I9.Y.TOVT.3.G47.3.INX","STS/M.I9.Y.TOVV.4000.4.ANR","MNA/Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY","MNA/Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GO","STS/M.I9.Y.PROD.NS0020.4.000","ICP/M.U2.N.XEF000.4.ANR","ICP/M.U2.N.000000.4.ANR","FM/D.U2.EUR.4F.KR.DFR.LEV","FM/M.U2.EUR.4F.BB.U2_10Y.YLD","YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y","BP6/M.N.I9.W1.S1.S1.T.B.G._Z._Z._Z.EUR._T._X.N","MNA/Q.Y.I9.W0.S1.S1._Z.COM_HW._Z._T._Z.IX.V.N","STS/M.I9.S.UNEH.RTT000.4.000"]:
    raw(f"https://data-api.ecb.europa.eu/service/data/{k}?format=csvdata&lastNObservations=1&detail=dataonly", 50)
raw("https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods", 1500, data=json.dumps([{"vectorId": v, "latestN": 1} for v in [41690973, 41690914, 108785713, 2062815, 2062811, 52367097, 65201210, 1235044, 87552811, 80691311]]).encode(), hdr={"Content-Type": "application/json"})
raw("https://api.data.abs.gov.au/data/ABS,CPI_M,1.0.0/all?startPeriod=2026-08&detail=serieskeysonly&format=csvfilewithlabels", 600)
raw("https://api.data.abs.gov.au/data/ABS,LF,1.0.0/M13.3.1599.20.AUS.M?startPeriod=2026-06&format=csv", 600)
raw("https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=json&lang=en&db=IR01&code=MADR1M&startDate=202501", 600)
raw("https://www.rba.gov.au/statistics/tables/csv/f1.1-data.csv", 200)
raw("https://www.rbnz.govt.nz/statistics/series/exchange-and-interest-rates/interest-rates", 200, hdr={"Accept": "text/html", "Accept-Language": "en-GB"})
raw("https://data.snb.ch/api/cube/snbgwdzid/data/csv/en?fromDate=2026-11-01", 600)
raw("https://data.snb.ch/api/cube/plkopr/data/csv/en?fromDate=2026-06", 600)
for cdid, ds, path in [("J5EK","drsi","businessindustryandtrade/retailindustry"),("J5EL","drsi","businessindustryandtrade/retailindustry"),("J5BE","drsi","businessindustryandtrade/retailindustry"),("J5C4","drsi","businessindustryandtrade/retailindustry"),
                       ("D7G7","mm23","economy/inflationandpriceindices"),("DKO8","mm23","economy/inflationandpriceindices"),("D7NN","mm23","economy/inflationandpriceindices"),
                       ("MGSX","lms","employmentandlabourmarket/peoplenotinwork/unemployment"),("KAC3","lms","employmentandlabourmarket/peopleinwork/earningsandworkinghours"),("KAI9","lms","employmentandlabourmarket/peopleinwork/earningsandworkinghours"),
                       ("IHYQ","qna","economy/grossdomesticproductgdp"),("ECY2","mgdp","economy/grossdomesticproductgdp"),("IKBJ","mret","economy/nationalaccounts/balanceofpayments"),("K222","diop","economy/economicoutputandproductivity/output"),("LZVB","lms","employmentandlabourmarket/peopleinwork/employmentandemployeetypes"),("AP2Y","lms","employmentandlabourmarket/peopleinwork/employmentandemployeetypes")]:
    raw(f"https://www.ons.gov.uk/generator?format=csv&uri=/{path}/timeseries/{cdid.lower()}/{ds}", 120)
