"""Download a curated list of Wikimedia Commons business-card images (freely licensed) + record license/source."""
import json, urllib.request, urllib.parse, os, sys
T = [l.strip() for l in open("commons_list.txt") if l.strip()]
os.makedirs("real", exist_ok=True); meta = {}
for i, t in enumerate(T):
    q = urllib.parse.urlencode({"action":"query","titles":t,"prop":"imageinfo","iiprop":"url|extmetadata","iiurlwidth":1600,"format":"json"})
    r = urllib.request.Request("https://commons.wikimedia.org/w/api.php?"+q, headers={"User-Agent":"GACpilot/0.1 research"})
    try:
        p = next(iter(json.load(urllib.request.urlopen(r, timeout=30))["query"]["pages"].values()))["imageinfo"][0]
        url = p.get("thumburl") or p["url"]; name = f"wc_{i:02d}.jpg"
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"GACpilot/0.1 research"}), timeout=60).read()
        open("real/"+name,"wb").write(data)
        em = p.get("extmetadata", {})
        meta[name] = {"title": t, "source": p.get("descriptionurl"), "license": em.get("LicenseShortName",{}).get("value")}
        print(name, t, meta[name]["license"])
    except Exception as e: print("FAIL", t, e, file=sys.stderr)
json.dump(meta, open("real/SOURCES.json","w"), indent=1)
