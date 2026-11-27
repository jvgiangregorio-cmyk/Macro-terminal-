"""Temporary: does Finnhub's free plan give government bond yields?"""
import json, os, time, urllib.request
KEY = os.environ["FINNHUB_API_KEY"]
def get(path):
    url = "https://finnhub.io/api/v1/" + path + ("&" if "?" in path else "?") + "token=" + KEY
    try:
        with urllib.request.urlopen(url, timeout=30) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()[:300]
    except Exception as e: return "ERR", str(e).encode()
for p in ["bond/yield-curve?code=US", "bond/yield-curve?code=CH", "bond/yield-curve?code=NZ",
          "economic/code", "economic?code=MA-NZ-10YRBOND", "quote?symbol=US10Y", "quote?symbol=TNX",
          "forex/rates?base=USD"]:
    st, b = get(p); print("=====", p, "status", st, "bytes", len(b)); print(b[:400].decode("utf-8", "replace")); time.sleep(1.5)
