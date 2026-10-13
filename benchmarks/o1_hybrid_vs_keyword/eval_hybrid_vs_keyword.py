"""A/B: keyword-only (sparse) vs hybrid (dense+sparse RRF) on sovereign_chunks.
Queries = the natural-language part of vendor page titles, code removed:
'USC 26.1.0: Display Optical Module Information (DSP OPTMODULE)' -> 'display optical module information'.
Hit = the exact page (same doc_identifier) in the top k. Seeded random sample of native MML + alarm pages."""
import json, random, re, sqlite3, sys, time
sys.path.insert(0, "/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance"); sys.path.insert(0, "/home/tlima/Enterprise_Hub")
from core.search.searcher import SovereignSearcher
DB = "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 150
PARA = len(sys.argv) > 2 and sys.argv[2] == "para"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = con.execute("select doc_identifier, title from document_records where record_kind='native' and doc_identifier like '%/mml/document/%' and title like '%(%)'").fetchall()
alarms = con.execute("select doc_identifier, title from document_records where record_kind='native' and title like '%: ALM-%'").fetchall()
random.seed(13)
def nl(t):
    t = re.sub(r"^[^:]*:\s*", "", t); t = re.sub(r"\([^)]*\)\s*$", "", t)
    t = re.sub(r"\bALM-\d+\s*", "", t); t = t.strip().lower()
    if PARA:
        for a, b in [("display ", "show me the "), ("list ", "what are the configured "), ("modify ", "change the "),
                     ("remove ", "delete the "), ("add ", "create a new "), ("set ", "configure the "),
                     ("clear ", "reset the "), ("query ", "check the "), ("reset ", "restart the ")]:
            if t.startswith(a):
                t = b + t[len(a):]; break
    return t
sample = [("mml", d, t, nl(t)) for d, t in random.sample(rows, min(N, len(rows)))] + [("alarm", d, t, nl(t)) for d, t in random.sample(alarms, min(N // 3, len(alarms)))]
sample = [x for x in sample if len(x[3].split()) >= 2]
s = SovereignSearcher()
orig = s.client.query_points
def sparse_only(*a, **kw):
    if kw.get("using") == "dense": return type("R", (), {"points": []})()
    return orig(*a, **kw)
res = {"keyword": [], "hybrid": []}
for mode in ("keyword", "hybrid"):
    s.client.query_points = sparse_only if mode == "keyword" else orig
    t0 = time.time()
    for kind, doc, title, q in sample:
        hits = s.search(q, limit=10)
        ids = [h.get("doc_identifier") for h in hits]
        res[mode].append(ids.index(doc) + 1 if doc in ids else None)
    print(mode, f"{time.time()-t0:.1f}s", file=sys.stderr)
def summ(r, sel=None):
    r = [x for x, smp in zip(r, sample) if sel is None or smp[0] == sel]; n = len(r)
    return {"n": n, "hit@1": sum(1 for x in r if x == 1) / n, "hit@5": sum(1 for x in r if x and x <= 5) / n,
            "hit@10": sum(1 for x in r if x) / n, "mrr@10": sum(1 / x for x in r if x) / n}
out = {m: {"all": summ(res[m]), "mml": summ(res[m], "mml"), "alarm": summ(res[m], "alarm")} for m in res}
gains = [(smp[3], smp[2], k, h) for smp, k, h in zip(sample, res["keyword"], res["hybrid"]) if (h or 99) < (k or 99)]
out["examples_gain"] = [{"q": q, "target": t, "keyword_rank": k, "hybrid_rank": h} for q, t, k, h in gains[:12]]
out["losses"] = sum(1 for k, h in zip(res["keyword"], res["hybrid"]) if (h or 99) > (k or 99))
print(json.dumps(out, indent=1))
