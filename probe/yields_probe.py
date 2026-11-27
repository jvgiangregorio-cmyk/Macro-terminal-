"""Temporary: round 2 of the bond yield source checks (SNB, BoE curve, RBA)."""
import io, urllib.request, zipfile, csv, subprocess
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()[:300]
    except Exception as e: return "ERR", str(e).encode()
def show(name, url, head=5, tail=5):
    st, b = get(url); print("\n=====", name, url, "\nstatus", st, "bytes", len(b))
    if st != 200: print(b[:300]); return None
    lines = [l for l in b.decode("utf-8", "replace").splitlines() if l.strip(" ,")]
    for l in lines[:head]: print("  H|", l[:400])
    print("  ...", len(lines))
    for l in lines[-tail:]: print("  T|", l[:400])
    return b

show("SNB rendoblid from 2026-11", "https://data.snb.ch/api/cube/rendoblid/data/csv/en?fromDate=2026-11-01")
for cube in ["rendoblim", "rendopar", "zimoma"]:
    show("SNB cube " + cube, f"https://data.snb.ch/api/cube/{cube}/data/csv/en?fromDate=2026-10-01", head=3, tail=3)
show("SNB RSS interest rates", "https://www.snb.ch/public/rss/en/interestRates", head=60, tail=1)

subprocess.run(["pip", "install", "-q", "openpyxl"])
import openpyxl
st, b = get("https://www.snb.ch/public/rates/interestRates.xlsx"); print("\n===== SNB interestRates.xlsx", st, len(b))
if st == 200:
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    for ws in wb:
        print(" sheet", ws.title)
        for r in list(ws.iter_rows(values_only=True))[:40]: print("  ", [c for c in r[:8] if c is not None])

st, b = get("https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip")
z = zipfile.ZipFile(io.BytesIO(b))
wb = openpyxl.load_workbook(io.BytesIO(z.read("GLC Nominal daily data current month.xlsx")), read_only=True, data_only=True)
print("\n===== BoE nominal sheets", wb.sheetnames)
for name in wb.sheetnames:
    if "spot" in name.lower():
        rows = list(wb[name].iter_rows(values_only=True))
        for r in rows[:6]: print("  H|", list(r[:22]))
        for r in rows[-2:]: print("  T|", list(r[:22]))
        break
st, b = get("https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip"); print("BoE nominal history zip", st, len(b))
if st == 200: print(zipfile.ZipFile(io.BytesIO(b)).namelist())

st, b = get("https://www.rba.gov.au/statistics/tables/csv/f2-data.csv")
rows = [r for r in csv.reader(io.StringIO(b.decode("utf-8-sig"))) if r and r[0][:1].isdigit()]
print("\n===== RBA F2 last rows"); [print("  ", r) for r in rows[-3:]]
