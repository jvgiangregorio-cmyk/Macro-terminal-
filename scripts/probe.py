"""Temporary: check which candidate series exist and are current. Removed before merge."""
import json, os, urllib.request, urllib.parse, sys
KEY = os.environ.get("FRED_API_KEY", "")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
def get(url, t=40):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(r, timeout=t) as f: return f.read()
def fred(ids):
    for i in ids:
        try:
            s = json.loads(get("https://api.stlouisfed.org/fred/series?" + urllib.parse.urlencode({"series_id": i, "api_key": KEY, "file_type": "json"})))["seriess"][0]
            print(f"FRED {i:24s} {s['observation_start']}..{s['observation_end']} {s['frequency_short']} {s['seasonal_adjustment_short']} | {s['title'][:90]} [{s['units_short']}]")
        except Exception as e: print(f"FRED {i:24s} ERR {str(e)[:60]}")
def fredsearch(q, n=8):
    try:
        d = json.loads(get("https://api.stlouisfed.org/fred/series/search?" + urllib.parse.urlencode({"search_text": q, "api_key": KEY, "file_type": "json", "limit": n, "order_by": "popularity", "sort_order": "desc"})))
        print(f"## FREDSEARCH {q}")
        for s in d["seriess"]: print(f"   {s['id']:26s} ..{s['observation_end']} {s['frequency_short']} {s['seasonal_adjustment_short']} | {s['title'][:80]} [{s['units_short']}]")
    except Exception as e: print(f"## FREDSEARCH {q} ERR {e}")
def dbn(ids):
    for i in ids:
        try:
            d = json.loads(get("https://api.db.nomics.world/v22/series/" + i + "?observations=1&format=json"))
            s = d["series"]["docs"][0]
            p = s.get("period", [])
            print(f"DBN  {i:50s} {p[0] if p else ''}..{p[-1] if p else ''} n={len(p)} | {s.get('series_name','')[:80]}")
        except Exception as e: print(f"DBN  {i:50s} ERR {str(e)[:60]}")
def dbq(ds, q, n=12):
    try:
        d = json.loads(get("https://api.db.nomics.world/v22/series/" + ds + "?" + urllib.parse.urlencode({"q": q, "limit": n, "observations": 0, "format": "json"})))
        docs = d["series"]["docs"]
        print(f"## DBQ {ds} q={q} total={d['series'].get('num_found')}")
        for s in docs: print(f"   {s['series_code']:45s} {s.get('indexed_at','')[:10]} | {s.get('series_name','')[:100]}")
    except Exception as e: print(f"## DBQ {ds} q={q} ERR {str(e)[:80]}")
def dbsearch(q, n=10):
    try:
        d = json.loads(get("https://api.db.nomics.world/v22/search?" + urllib.parse.urlencode({"q": q, "limit": n})))
        print(f"## DBSEARCH {q}")
        for r in d["results"]["docs"]: print(f"   {r.get('provider_code')}/{r.get('code')} nb={r.get('nb_series')} upd={str(r.get('indexed_at',''))[:10]} | {r.get('name','')[:80]}")
    except Exception as e: print(f"## DBSEARCH {q} ERR {str(e)[:80]}")
def raw(url):
    try: b = get(url); print(f"RAW OK {len(b)} {url[:100]}\n   {b[:300]!r}")
    except Exception as e: print(f"RAW ERR {url[:100]} {str(e)[:80]}")

fred("GDPC1 A191RL1Q225SBEA CPIAUCSL CPILFESL PCEPILFE UNRATE PAYEMS RSAFS RSFSXMV CES0500000003 BOPGSTB INDPRO UMCSENT ICSA HOUST JTSJOL DFF DGS10".split())
cc = {"GB":"GBR","JP":"JPN","DE":"DEU","EZ":"EA19","CA":"CAN","AU":"AUS","NZ":"NZL","CH":"CHE"}
for c in ["GB","JP","CA","AU","NZ","CH","EZ"]:
    fred([f"CPALTT01{c}M659N", f"LRHUTTTT{c}M156S", f"IRLTLT01{c}M156N", f"IR3TIB01{c}M156N", f"SLRTTO01{c}M657S", f"BSCICP03{c}M665S", f"CSCICP03{c}M665S", f"LOLITOAA{c}M156N", f"XTEXVA01{c}M667S", f"NAEXKP01{c}Q657S"])
fred(["CLVMNACSCAB1GQUK","CLVMNACSCAB1GQEA19","CLVMEURSCAB1GQEA19","JPNRGDPEXP","NGDPRSAXDCCAQ","NGDPRSAXDCAUQ","NZLRGDPEXP","CLVMNACSCAB1GQCH","ECBDFR","IRSTCI01JPM156N","INTDSRJPM193N","CP0000EZ19M086NEST","CPHPTT01EZM659N","EA19CPHPLA01GYM"])
for q in ["United Kingdom retail sales","Japan CPI","Canada unemployment rate","Australia CPI","New Zealand unemployment","Switzerland CPI","Euro area unemployment","Japan retail","Canada retail sales","Switzerland unemployment","policy rate Bank of Japan","BIS central bank policy rate"]:
    fredsearch(q)
for q in ["ONS retail sales","Statistics Canada consumer price","ABS consumer price index","Stats NZ","Swiss consumer price","Japan consumer price index","BIS central bank policy rates","Eurostat HICP monthly","OECD key short-term economic indicators","Statistics Bureau Japan labour force"]:
    dbsearch(q)
dbn(["ONS/MM23/D7G7.M","ONS/MM23/DKO8.M","ONS/DRSI/J5EK.M","ONS/DRSI/J5EB.M","ONS/LMS/MGSX.M","ONS/LMS/KAC3.M","ONS/QNA/IHYQ.Q","ONS/QNA/ABMI.Q",
     "ECB/ICP/M.U2.N.000000.4.ANR","ECB/ICP/M.U2.N.XEF000.4.ANR","ECB/FM/D.U2.EUR.4F.KR.DFR.LEV","ECB/FM/B.U2.EUR.4F.KR.DFR.LEV",
     "Eurostat/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA20","Eurostat/prc_hicp_manr/M.RCH_A.CP00.EA","Eurostat/namq_10_gdp/Q.CLV_PCH_PRE.SCA.B1GQ.EA20","Eurostat/sts_trtu_m/M.VOL_SLS.G47.SCA.I21.EA20",
     "BIS/WS_CBPOL/M.GB","BIS/WS_CBPOL/D.JP","BIS/WS_CBPOL/M.CH"])
for ds,q in [("ONS/DRSI","volume seasonally adjusted"),("ONS/MM23","annual rate"),("ONS/LMS","unemployment rate"),("ONS/LMS","average weekly earnings"),("ONS/QNA","gross domestic product chained volume"),("ONS/MRET","volume"),
             ("BIS/WS_CBPOL",""),("Eurostat/sts_trtu_m","EA20 volume retail"),("Eurostat/une_rt_m","EA20 SA total percentage active"),
             ("STATCAN/18100004",""),("ABS/CPI","all groups")]:
    dbq(ds,q)
raw("https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/GBR+JPN.M.N.CPI.PA._T.N.GY?startPeriod=2025-01&format=csvfilewithlabels")
raw("https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods")
raw("https://www.ons.gov.uk/generator?format=csv&uri=/businessindustryandtrade/retailindustry/timeseries/j5ek/drsi")
raw("https://api.beta.ons.gov.uk/v1/datasets")
raw("https://data-api.ecb.europa.eu/service/data/ICP/M.U2.N.000000.4.ANR?format=csvdata&lastNObservations=2")
raw("https://data.snb.ch/api/cube/snbgwdzid/data/csv/en")
raw("https://www.rba.gov.au/statistics/tables/csv/g1-data.csv")
raw("https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily.xlsx")
