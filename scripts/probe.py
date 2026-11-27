"""Temporary: check which candidate series exist and are current. Removed before merge."""
import csv, io, json, os, time, urllib.request, urllib.parse
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
def get(url, t=90, data=None, hdr=None):
    h = {"User-Agent": UA, "Accept": "*/*"}; h.update(hdr or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h, data=data), timeout=t) as f: return f.read()
def raw(url, n=400, m=300, **kw):
    t0 = time.time()
    try: b = get(url, **kw); print(f"RAW OK {len(b)} {time.time()-t0:.1f}s {url[:150]}\n   {b[:n]!r}\n   ...{b[-m:]!r}")
    except Exception as e: print(f"RAW ERR {url[:150]} {str(e)[:120]}")
def dbq(ds, q, n=40):
    try:
        d = json.loads(get("https://api.db.nomics.world/v22/series/" + ds + "?" + urllib.parse.urlencode({"q": q, "limit": n, "observations": 0})))
        print(f"## DBQ {ds} q={q} total={d['series'].get('num_found')}")
        for s in d["series"]["docs"]: print(f"   {s['series_code']:40s} | {s.get('series_name','')[:130]}")
    except Exception as e: print(f"## DBQ {ds} q={q} ERR {str(e)[:80]}")
def dbn(ids):
    for i in ids:
        try:
            s = json.loads(get("https://api.db.nomics.world/v22/series/" + i + "?observations=1"))["series"]["docs"][0]
            p = s.get("period", []); v = s.get("value", [])
            print(f"DBN {i:42s} {p[0] if p else ''}..{p[-1] if p else ''} last={v[-1] if v else ''} n={len(p)} | {s.get('series_name','')[:90]}")
        except Exception as e: print(f"DBN {i:42s} ERR {str(e)[:60]}")
for k in ["HICP/M.U2.N.000000.4.ANR", "HICP/M.U2.N.XEF000.4.ANR", "HICP/M.U2.N.SERV00.4.ANR", "ICP/M.U2.Y.000000.3.INX", "STS/M.I9.Y.TOVT.4000.4.ANR", "STS/M.I9.W.TOVV.4700.4.ANR", "STS/M.I9.Y.TOVV.4700.4.ANR", "STS/M.I9.Y.TOVV.G47.4.ANR", "LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T", "MNA/Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY", "MNA/Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N", "STS/M.I9.Y.PROD.NS0020.4.ANR", "STS/M.I9.W.PROD.NS0020.4.ANR"]:
    raw(f"https://data-api.ecb.europa.eu/service/data/{k}?format=csvdata&lastNObservations=1&detail=dataonly", 0, 140)
raw("https://data-api.ecb.europa.eu/service/data/ICP/M.U2.N.000000.4.ANR?format=csvdata&startPeriod=2025-10&detail=dataonly", 0, 400)
raw("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.US+GB+JP+CH+CA+AU+NZ+XM?startPeriod=2026-11-15&format=csv&detail=dataonly", 200, 600)
raw("https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.US+GB+JP+CH+CA+AU+NZ+XM?startPeriod=2000-01&format=csv&detail=dataonly", 200, 300)
for v in [41690973, 41690914, 108785713, 108785714, 108785715, 2062815, 52367097, 52367098, 65201210, 1235044, 65201483]:
    raw("https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods", 0, 500, data=json.dumps([{"vectorId": v, "latestN": 1}]).encode(), hdr={"Content-Type": "application/json"})
raw("https://www150.statcan.gc.ca/t1/wds/rest/getSeriesInfoFromVector", 0, 600, data=json.dumps([{"vectorId": 41690973}]).encode(), hdr={"Content-Type": "application/json"})
raw("https://data.api.abs.gov.au/rest/data/ABS,LF,1.0.0/M13.3.1599.20.AUS.M?startPeriod=2026-06&format=csv", 300, 300)
raw("https://www.rba.gov.au/statistics/tables/csv/g1-data.csv", 1500, 600)
raw("https://www.rba.gov.au/statistics/tables/csv/h5-data.csv", 1200, 300)
t0 = time.time()
raw("https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,/USA+GBR+EA20+JPN+CHE+CAN+AUS+NZL.M+Q.N.CPI.PA._T+_TXCP01_NRG.N.GY?startPeriod=2000-01&dimensionAtObservation=AllDimensions&format=csvfile", 300, 200)
time.sleep(4)
raw("https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_KEI@DF_KEI,/USA+GBR+EA20+JPN+CHE+CAN+AUS+NZL.M+Q.B1GQ_Q+PRVM+TOVM+H_EARN+EX+IM+EMP+NODW...GY+G1?startPeriod=2000-01&format=csvfile", 300, 200)
time.sleep(4)
raw("https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_KEI@DF_KEI,/USA+GBR.M..?startPeriod=2026-01&format=csvfile", 600, 200)
dbq("ONS/DRSI", "excluding fuel")
dbq("ONS/DRSI", "All Retailers")
dbq("ONS/MM23", "CPI ANNUAL RATE 00")
dbq("ONS/LMS", "AWE")
dbq("ONS/LMS", "claimant")
dbq("ONS/MGDP", "")
dbq("STATJP/CPIm", "", 90)
dbq("STATJP/MIm", "", 40)
dbn(["ONS/MGDP/ECY2.M", "ONS/MRET/IKBJ.M", "ONS/MM23/D7NN.M", "ONS/MM23/D7G8.M", "ONS/LMS/KAI9.M", "ONS/LMS/BCJD.M", "ONS/DIOP/K222.M"])
