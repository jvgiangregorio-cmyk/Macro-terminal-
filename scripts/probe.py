"""Temporary: run the fundamentals collector once and summarise. Removed before merge."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import fundamentals as f
t = time.time()
payload, errors = f.fetch_all(os.environ.get("FRED_API_KEY", ""))
print(f"took {time.time()-t:.0f}s")
for cur, c in payload["countries"].items():
    print(f"## {cur} {c['name']} {len(c['items'])} items")
    for i in c["items"]:
        p = i["pts"]
        print(f"   {i['id']:22s} {i['freq']} n={len(p):4d} {p[0][0]}..{p[-1][0]} last={p[-1][1]} prev={p[-2][1]} | {i['name']}")
print("ERRORS", json.dumps(errors, indent=1))
os.makedirs("out", exist_ok=True)
json.dump(dict(updated="test", errors=errors, **payload), open("out/fundamentals.json", "w"), separators=(",", ":"))
print("size", os.path.getsize("out/fundamentals.json"))
