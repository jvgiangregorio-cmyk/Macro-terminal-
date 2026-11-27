"""Temporary: second look at MUFG, Deutsche Bank Research, Danske, KBC, CaixaBank."""
import re, urllib.request, xml.etree.ElementTree as ET
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=25).read().decode("utf-8", "ignore")
def show(u, pat=r'href="([^"]+)"[^>]*>([^<]{15,140})<', n=25):
    try:
        h = get(u); print(f"== {u} ({len(h)} bytes)")
        for a, t in re.findall(pat, h)[:n]: print("  ", a[:110], "|", t.strip()[:90])
        return h
    except Exception as e: print(f"== {u} ERR {e}")
for u in ["https://www.mufgresearch.com/robots.txt", "https://research.danskebank.com/robots.txt"]:
    try: print("==", u, "\n", get(u)[:600])
    except Exception as e: print(u, e)
show("https://www.mufgresearch.com/fx/")
show("https://www.mufgresearch.com/")
h = show("https://www.dbresearch.com/PROD/IE-PROD/RSS_FEEDS_EN.calias", r'href="([^"]*(?:rss|RSS|xml)[^"]*)"()', 15)
show("https://research.danskebank.com/")
for f in ["https://www.caixabankresearch.com/en/rss.xml"]:
    try:
        root = ET.fromstring(get(f).encode())
        for it in root.findall(".//item")[:6]: print("  ", it.findtext("pubDate"), "|", it.findtext("title"), "|", (it.findtext("link") or "")[:90])
    except Exception as e: print(f, e)
