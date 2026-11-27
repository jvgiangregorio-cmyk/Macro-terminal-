"""Temporary: which research sites have feeds, and can their articles be shown in a pop-up?"""
import re, urllib.request, urllib.parse, xml.etree.ElementTree as ET
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
def get(u):
    r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=25)
    return r, r.read()
FEEDS = ["https://think.ing.com/rss/", "https://www.nordea.com/en/data_export/articles_xml/275",
         "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "https://www.federalreserve.gov/feeds/press_all.xml"]
SITES = ["https://www.mufgresearch.com/", "https://www.mufgresearch.com/fx/", "https://www.mufgemea.com/research/",
         "https://research.danskebank.com/", "https://www.commerzbank.de/en/hauptnavigation/presse/research/",
         "https://www.rabobank.com/knowledge", "https://www.kbc.com/en/kbc-economics.html", "https://www.westpaciq.com.au/economics/",
         "https://www.scotiabank.com/ca/en/about/economics.html", "https://economics.cibccm.com/", "https://sebgroup.com/our-offering/research-and-strategy",
         "https://www.abnamro.com/research/en/home", "https://www.dbresearch.com/", "https://www.nomuraconnects.com/", "https://www.caixabankresearch.com/en/publications",
         "https://www.anz.com.au/institutional/insights/", "https://www.bnz.co.nz/about-us/economic-research", "https://www.unicredit.eu/en/research.html",
         "https://www.societegenerale.com/en/economic-research", "https://www.ubs.com/global/en/wealthmanagement/insights/house-view.html"]
GUESS = ["feed", "feed/", "rss", "rss/", "rss.xml", "feed.xml", "atom.xml", "?format=rss"]
def isfeed(b):
    try: root = ET.fromstring(b)
    except Exception: return 0
    return len(root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry"))
def frame(u):
    try:
        r, b = get(u)
        h = r.headers
        return f"XFO={h.get('X-Frame-Options')} CSP-fa={re.findall(r'frame-ancestors[^;]*', h.get('Content-Security-Policy') or '')} len={len(b)}"
    except Exception as e: return f"ERR {e}"[:120]
print("== existing feeds: description length + can article be framed")
for f in FEEDS:
    try:
        _, b = get(f); root = ET.fromstring(b)
        it = (root.findall(".//item") or [None])[0]
        if it is None: print(f, "no items"); continue
        link = (it.findtext("link") or "").strip()
        desc = re.sub("<[^>]+>", "", it.findtext("description") or "")
        enc = it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
        print(f"{f}\n  desc={len(desc)} chars content:encoded={len(enc)} first={desc[:120]!r}\n  {link}\n  {frame(link)}")
    except Exception as e: print(f, "ERR", str(e)[:150])
print("== sites: feed links on page, guessed feed URLs, framing")
for s in SITES:
    try:
        r, b = get(s); html = b.decode("utf-8", "ignore")
        alts = re.findall(r'<link[^>]+(?:rss|atom)\+xml[^>]*>', html, re.I)
        rssy = sorted(set(re.findall(r'href="([^"]*(?:rss|feed|xml)[^"]*)"', html, re.I)))[:8]
        print(f"{s} status={r.status} XFO={r.headers.get('X-Frame-Options')} alt={[re.findall(r'href=\"([^\"]+)', a) for a in alts]} rssy={rssy}")
    except Exception as e:
        print(s, "ERR", str(e)[:120]); continue
    for g in GUESS:
        u = urllib.parse.urljoin(s, g)
        try:
            _, b = get(u); n = isfeed(b)
            if n: print(f"   FEED {u} items={n}")
        except Exception: pass
