"""Temporary: check which candidate series exist and are current. Removed before merge."""
import json, urllib.request, urllib.parse
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
def get(url): 
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90) as f: return f.read()
def listall(ds, filt, q=""):
    off, out = 0, []
    while True:
        d = json.loads(get(f"https://api.db.nomics.world/v22/series/{ds}?" + urllib.parse.urlencode({"limit": 1000, "offset": off, "observations": 0, "q": q})))["series"]
        out += d["docs"]; off += 1000
        if off >= d["num_found"]: break
    print(f"## {ds} total {len(out)}")
    for s in out:
        n = s.get("series_name", "")
        if all(f.lower() in n.lower() for f in filt): print(f"   {s['series_code']:40s} | {n[:150]}")
def dbn(ids):
    for i in ids:
        try:
            s = json.loads(get("https://api.db.nomics.world/v22/series/" + i + "?observations=1"))["series"]["docs"][0]
            p = s.get("period", []); v = s.get("value", [])
            print(f"DBN {i:42s} {p[0] if p else ''}..{p[-1] if p else ''} last3={v[-3:]} n={len(p)} | {s.get('series_name','')[:90]}")
        except Exception as e: print(f"DBN {i:42s} ERR {str(e)[:60]}")
listall("ONS/DRSI", ["VOL SA", ".M"])
listall("ONS/DRSI", ["Volume Seasonally Adjusted", "Monthly"])
listall("ECB/HICP", ["all-items"], "U2 annual rate")
listall("ECB/HICP", ["excluding"], "U2 annual rate")
listall("ONS/LMS", ["claimant", "Monthly"])
dbn(["STATJP/CPIm/001", "STATJP/CPIm/733", "STATJP/CPIm/740", "STATJP/MIm/M.UR.B.PCT.SA", "ECB/HICP/M.U2.N.000000.4.ANR"])
