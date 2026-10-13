"""Read-only onboarding scorecard: what each source holds at the source vs in each store."""
import glob, json, os, sqlite3, urllib.request, zipfile, io, datetime
HUB = "/home/tlima/Enterprise_Hub"; DB = f"{HUB}/docs/.aegis_vault/sovereign_router.db"; Q = "http://127.0.0.1:6333"
def q(path, body=None):
    req = urllib.request.Request(Q + path, data=json.dumps(body).encode() if body else None, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=20))["result"]
out = {}
# --- manuals at source
entries = 0; pk = []
for z in sorted(glob.glob(f"{HUB}/docs/Hua_Docs/*.zip")):
    with zipfile.ZipFile(z) as zf:
        n = 0
        for i in zf.infolist():
            if i.filename.lower().endswith(".hwics"):
                with zipfile.ZipFile(zf.open(i)) as inner: n += len(inner.infolist())
            else: n += 1
        entries += n; pk.append((os.path.basename(z), n, round(os.path.getsize(z) / 2**20, 1)))
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c = con.cursor()
one = lambda s: c.execute(s).fetchone()[0]
out["manuals"] = dict(packages=pk, source_entries=entries,
    native=one("select count(*) from document_records where record_kind='native'"),
    native_no_topic=one("select count(*) from document_records where record_kind='native' and topic_id is null"),
    composite=one("select count(*) from document_records where record_kind='composite'"),
    topic_nodes=one("select count(*) from topic_nodes"), vectors=0)
# --- wiki
notes = [p for p in glob.glob(f"{HUB}/docs/wiki/**/*.md", recursive=True) if "/.obsidian/" not in p]
uris = [r[0] for r in c.execute("select distinct json_extract(metadata,'$.virtual_uri') from document_records where record_kind='external' and (doc_identifier like '%.md%' or metadata like '%docs/wiki%')")]
snap = one("select max(created_at) from document_records where record_kind='external' and (doc_identifier like '%.md%' or metadata like '%docs/wiki%')")
snap_ts = datetime.datetime.fromisoformat(snap).replace(tzinfo=datetime.timezone.utc).timestamp()
pts = q("/collections/wiki_chunks")["points_count"]
files = set(); off = None
while True:
    r = q("/collections/wiki_chunks/points/scroll", {"limit": 256, "with_payload": ["file_path"], "with_vector": False, **({"offset": off} if off else {})})
    files |= {p["payload"].get("file_path") for p in r["points"]}; off = r.get("next_page_offset")
    if not off: break
out["wiki"] = dict(notes=len(notes),
    sqlite_records=one("select count(*) from document_records where record_kind='external' and (doc_identifier like '%.md%' or metadata like '%docs/wiki%')"),
    sqlite_paths=len(uris), sqlite_missing=sum(1 for u in uris if u and not os.path.exists(u.replace("file://", ""))),
    sqlite_obsidian=sum(1 for u in uris if u and "/.obsidian/" in u), sqlite_snapshot=snap,
    changed_since_snapshot=sum(1 for p in notes if os.path.getmtime(p) > snap_ts),
    qdrant_points=pts, qdrant_files=len(files - {None}), graph_notes=len(notes))
out["fixtures"] = one("select count(*) from document_records where record_kind='external' and not (doc_identifier like '%.md%' or metadata like '%docs/wiki%')")
out["paperless_vectors"] = q("/collections/paperless_chunks")["points_count"]
out["total_records"] = one("select count(*) from document_records")
print(json.dumps(out, indent=1)); json.dump(out, open("scorecard.json", "w"), indent=1)
