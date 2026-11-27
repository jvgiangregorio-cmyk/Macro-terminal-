"""Temporary: what date fields do Nordea and Deutsche Bank Research items have?"""
import urllib.request
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
for u in ["https://www.nordea.com/en/data_export/articles_xml/275", "https://www.dbresearch.com/PROD/IE-PROD/RSS_GROUP_HOME_EN.calias"]:
    try:
        b = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=25).read().decode("utf-8", "ignore")
        print("==", u, len(b)); print(b[:1800].replace("\n", " ")[:1800])
    except Exception as e: print(u, e)
