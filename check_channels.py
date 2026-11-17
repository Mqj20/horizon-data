#!/usr/bin/env python3
"""يفحص كل قنوات content_v2.json: تشتغل لو لا؟ ويكتب channels_status.json و channels_status.md
الاستعمال:  python check_channels.py content_v2.json      (أو بدون وسيط: يقرأ content_v2.json من نفس المجلد)
"""
import json, sys, time, re, os, base64, hashlib, concurrent.futures as cf
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from urllib.request import Request, urlopen
from urllib.parse import urljoin
from urllib.error import HTTPError

TIMEOUT = 12
UA = "Mozilla/5.0 (Linux; Android 11) HorizonCheck/1.0"

# كلمة سر التشفير تأتي من متغير بيئة HZ_KEY (سر GitHub)، ولا تُكتب داخل الملف أبداً.
_KEY = hashlib.sha256(os.environ["HZ_KEY"].encode()).digest() if os.environ.get("HZ_KEY") else None

def dec(u):
    """يفك صيغة HZ2: (AES-256-GCM) إن وُجدت، وإلا يرجع الرابط كما هو."""
    if not isinstance(u, str) or not u.startswith("HZ2:"):
        return u
    if _KEY is None:
        return "ENCRYPTED-NO-KEY"
    try:
        raw = base64.b64decode(u[4:])
        return AESGCM(_KEY).decrypt(raw[:12], raw[12:], None).decode("utf-8")
    except Exception:
        return "DECRYPT-FAILED"

def get(url, headers=None, rng=None, limit=200_000):
    h = {"User-Agent": UA, **(headers or {})}
    if rng: h["Range"] = rng
    with urlopen(Request(url, headers=h), timeout=TIMEOUT) as r:
        return r.status, r.read(limit)

def check_url(url, headers=None):
    """يرجع (ok, السبب)"""
    if url == "ENCRYPTED-NO-KEY":
        return False, "الرابط مشفر ولم يوضع HZ_KEY"
    if url == "DECRYPT-FAILED":
        return False, "فشل فك التشفير (تأكد من HZ_KEY)"
    if not url.lower().startswith("http"):
        return None, "رابط غير http (تخطّي)"
    if "example.com" in url or "REPLACE" in url:
        return False, "رابط تجريبي لم يُستبدل"
    t0 = time.time()
    try:
        st, body = get(url, headers)
        txt = body.decode("utf-8", "ignore")
        if ".m3u8" in url.lower() or txt.lstrip().startswith("#EXTM3U"):
            if not txt.lstrip().startswith("#EXTM3U"):
                return False, "الرد ليس قائمة m3u8"
            lines = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("#")]
            if not lines:
                return False, "القائمة فارغة"
            nxt = urljoin(url, lines[0])
            if ".m3u8" in nxt.lower():              # قائمة رئيسية → افحص القائمة الفرعية
    src = sys.argv[1] if len(sys.argv) > 1 else "content_v2.json"
    data = json.load(open(src, encoding="utf-8-sig"))
    def urls_of(v):
        if isinstance(v, str): return [v] if v.strip() and v != "null" else []
        if isinstance(v, list): return [u for u in v if isinstance(u, str) and u.strip() and u != "null"]
        return []
    jobs = []
    for g in data.get("channels", []):
        for ch in g.get("channels", []):
            hdr = ch.get("headers") if isinstance(ch.get("headers"), dict) else None
            items = []
            st = ch.get("streams")
            if isinstance(st, dict):
                for q, v in st.items():
                    for i, u in enumerate(urls_of(v)):
                        items.append((q if i == 0 else f"{q} احتياطي{i}", u))
            else:
                for u in urls_of(ch.get("url")): items.append(("HD", u))
            bs = ch.get("backupStreams")
            if isinstance(bs, dict):
                for q, v in bs.items():
                    for i, u in enumerate(urls_of(v)): items.append((f"{q} احتياطي{i+1}", u))
            for q, u in items:
                jobs.append((g.get("name", ""), ch.get("name", ""), q, dec(u), hdr))
    def run(j):
        try:
            ok, why = check_url(j[3], j[4])
        except Exception as e:
            ok, why = False, "خطأ: " + type(e).__name__
        return {"group": j[0], "channel": j[1], "quality": j[2], "ok": ok, "detail": why}
    with cf.ThreadPoolExecutor(16) as ex:
        res = list(ex.map(run, jobs))
    # القناة تعتبر شغالة إذا أي جودة شغالة
    chans = {}
    for r in res:
        k = (r["group"], r["channel"])
        c = chans.setdefault(k, {"group": r["group"], "channel": r["channel"], "ok": False, "checked": False, "detail": []})
        if r["ok"] is None: continue
        c["checked"] = True
        c["ok"] = c["ok"] or bool(r["ok"])
        c["detail"].append(f'{r["quality"]}: {r["detail"]}')
    out = [c for c in chans.values() if c["checked"]]
    up = sum(c["ok"] for c in out)
    summary = {"updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
               "total": len(out), "working": up, "down": len(out) - up, "channels": out}
    json.dump(summary, open("channels_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = [f"# حالة القنوات — {summary['updated']}", f"شغالة **{up}** من **{len(out)}**", ""]
    down = [c for c in out if not c["ok"]]
    md.append("## المتوقفة" if down else "## كل القنوات شغالة ✅")
    md += [f"- ❌ {c['group']} / {c['channel']} — {'; '.join(c['detail'])}" for c in down]
    md += ["", "## الشغالة"] + [f"- ✅ {c['group']} / {c['channel']}" for c in out if c["ok"]]
    open("channels_status.md", "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md[:40]))

if __name__ == "__main__":
    main()
