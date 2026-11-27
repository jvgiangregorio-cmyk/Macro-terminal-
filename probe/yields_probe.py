"""Temporary: test free daily government bond yield sources from GitHub Actions."""
import io, json, time, urllib.request, zipfile

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "*/*"}

def get(url, headers=None):
    h = dict(UA); h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]
    except Exception as e:
        return "ERR", str(e).encode()

def show(name, url, headers=None, head=6, tail=4, binary=False):
    print("\n=====", name, "\n", url)
    st, b = get(url, headers)
    print("status", st, "bytes", len(b))
    if binary or st != 200:
        if st != 200: print(b[:300])
        return b if st == 200 else None
    try:
        t = b.decode("utf-8", "replace")
    except Exception:
        t = str(b[:500])
    lines = t.splitlines()
    for l in lines[:head]: print("  H|", l[:300])
    print("  ...", len(lines), "lines")
    for l in lines[-tail:]: print("  T|", l[:300])
    return b

# GBP: BoE latest yield curve zip (daily spot/par curves, 0.5y-40y)
b = show("BoE yield curve zip", "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip", binary=True)
if b:
    try:
        z = zipfile.ZipFile(io.BytesIO(b)); print("  zip files:", z.namelist())
    except Exception as e: print("  zip err", e)
show("BoE IADB zero-coupon 5/10/20", "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=01/Nov/2026&Dateto=now&SeriesCodes=IUDSNZC,IUDMNZC,IUDLNZC,IUDSNPY&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")

# EUR: ECB AAA and all-issuer euro area spot curves
show("ECB YC AAA 2y/10y", "https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y+SR_10Y?lastNObservations=3&format=csvdata", tail=6)
show("ECB YC all 2y/10y", "https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_C.SV_C_YM.SR_2Y+SR_10Y?lastNObservations=3&format=csvdata", tail=6)
# EUR: Bundesbank German Bund yields (term structure)
show("Bundesbank 10y csv", "https://api.statistiken.bundesbank.de/rest/download/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?format=csv&lang=en", head=10)
show("Bundesbank 2y sdmx-csv", "https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZST.ZI.EUR.S1311.B.A604.R02XX.R.A.A._Z._Z.A?lastNObservations=3", headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"})

# JPY: Ministry of Finance JGB curve
show("MoF JGB current month", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv")
show("MoF JGB all", "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv", head=3)

# CHF: SNB Confederation bond spot rates (daily)
show("SNB rendoblid", "https://data.snb.ch/api/cube/rendoblid/data/csv/en", head=8, tail=12)
show("SNB rendoblid dims", "https://data.snb.ch/api/cube/rendoblid/dimensions/en", head=40, tail=1)

# CAD: Bank of Canada Valet benchmark bond yields
show("BoC Valet benchmark", "https://www.bankofcanada.ca/valet/observations/group/bond_yields_benchmark/csv?recent=3", head=30, tail=5)

# AUD: RBA F2 (daily CGS yields)
show("RBA F2", "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv", head=12, tail=4)
show("RBA F17 zero coupon", "https://www.rba.gov.au/statistics/tables/csv/f17-yields.csv", head=12, tail=2)

# NZD: RBNZ B2 wholesale rates (daily)
for u in ["https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily.xlsx",
          "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/statistics/series/b/b2/hb2-daily-close.xlsx"]:
    show("RBNZ B2", u, headers={"Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*", "Accept-Language": "en-NZ,en;q=0.9", "Referer": "https://www.rbnz.govt.nz/statistics/series/exchange-and-interest-rates/wholesale-interest-rates"}, binary=True)
show("DBnomics RBNZ provider", "https://api.db.nomics.world/v22/datasets/RBNZ?limit=50", head=3, tail=1)
show("DBnomics search NZ govt bond", "https://api.db.nomics.world/v22/search?q=new%20zealand%20government%20bond%20yield&limit=10", head=3, tail=1)

# Fallback for everyone: Stooq daily CSVs
for s in ["10nzy.b", "2nzy.b", "10auy.b", "2jpy.b"]:
    show("Stooq " + s, f"https://stooq.com/q/d/l/?s={s}&i=d", head=3, tail=2)
    time.sleep(2)
