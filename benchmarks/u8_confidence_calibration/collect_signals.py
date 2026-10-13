"""U8: which hybrid signals separate a right answer from a wrong or off-topic one?
For each query, record the top hits' dense cosine and the dense/sparse ranks, and whether the right command is in
the top 5. In-domain = engineer-worded MML titles (as in the O1 A/B, seed 13); off-topic = questions the manuals
cannot answer. Read-only. Output: JSON lines on stdout."""
import json, random, re, sqlite3, sys
sys.path.insert(0, "/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance"); sys.path.insert(0, "/home/tlima/Enterprise_Hub")
from core.search.searcher import SovereignSearcher
DB = "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 80
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = con.execute("select doc_identifier, title from document_records where record_kind='native' and doc_identifier like '%/mml/document/%' and title like '%(%)'").fetchall()
random.seed(7)  # a different sample from the A/B (seed 13), so the thresholds are not fitted to the test set
PARA = [("display ", "show me the "), ("list ", "what are the configured "), ("modify ", "change the "), ("remove ", "delete the "),
        ("add ", "create a new "), ("set ", "configure the "), ("clear ", "reset the "), ("query ", "check the "), ("reset ", "restart the ")]
def nl(t):
    t = re.sub(r"^[^:]*:\s*", "", t); t = re.sub(r"\([^)]*\)\s*$", "", t).strip().lower()
    for a, b in PARA:
        if t.startswith(a):
            return b + t[len(a):]
    return t
code_of = lambda t: (re.search(r"\(([^()]*)\)\s*$", t or "") or [None, None])[1]
OFF = ["what is the best pizza in naples", "how do I bake sourdough bread", "who won the 2018 world cup",
       "recommend a good science fiction novel", "how to train a puppy to sit", "what is the capital of australia",
       "how do I change a car tire", "best way to learn the guitar", "symptoms of the common cold",
       "how to plant tomatoes in a balcony", "explain the rules of cricket", "what time is sunset in lisbon",
       "how do I file my income tax return", "convert celsius to fahrenheit", "how to knit a scarf",
       "what is the plot of hamlet", "how do I reset my iphone", "cheap flights to tokyo", "how to cook rice",
       "what is a black hole", "how many calories in an apple", "how to write a cover letter",
       "configure a wordpress plugin", "how to set up a kubernetes ingress controller", "show me the excel pivot table menu",
       "list the docker containers", "check my bank account balance", "how to paint a bedroom wall",
       "what are the symptoms of diabetes", "how to fix a leaking faucet"]
s = SovereignSearcher()
def rec(kind, q, target_code):
    hits = s.search(q, limit=10)
    m = [h.get("meta") or {} for h in hits]
    codes = [code_of(h.get("title")) for h in hits]
    right = next((i + 1 for i, c in enumerate(codes) if target_code and c and c.strip() == target_code), None)
    print(json.dumps({"kind": kind, "q": q, "right_rank": right,
                      "top": [{"rrf": h.get("rrf_score"), "dr": x.get("dense_rank"), "ds": x.get("dense_score"), "sr": x.get("sparse_rank"),
                               "ss": x.get("sparse_score"), "title": (h.get("title") or "")[:70]} for h, x in zip(hits[:5], m[:5])]}), flush=True)
for d, t in random.sample(rows, N):
    q = nl(t)
    if len(q.split()) >= 2:
        rec("in", q, code_of(t).strip())
for q in OFF:
    rec("off", q, None)
