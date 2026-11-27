"""Dump T3 run/item/request history for coordinator threads and their workers.
usage: dbdump.py DB < {"coord_sessions": {...session: [thread ids referenced]}}  -> JSON on stdout"""
import json,sqlite3,sys
db=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True)
q=lambda s,*a: db.execute(s,a).fetchall()
inp=json.load(sys.stdin)
out={}
for sess,refs in inp.items():
    row=q("select thread_id from orchestration_v2_projection_provider_threads where payload_json like ? limit 1",f"%{sess}%")
    if not row: out[sess]=None; continue
    coord=row[0][0]
    kids={r[0] for r in q("select thread_id from orchestration_v2_projection_threads where json_extract(payload_json,'$.lineage.parentThreadId')=?",coord)}
    threads={}
    for t in sorted(kids|set(refs)|{coord}):
        meta=q("select json_extract(payload_json,'$.lineage.parentThreadId'), json_extract(payload_json,'$.lineage.relationshipToParent'), title from orchestration_v2_projection_threads where thread_id=?",t)
        if not meta: continue
        runs=q("select ordinal,status,requested_at,completed_at from orchestration_v2_projection_runs where thread_id=? and requested_at>='2026-10-28' order by ordinal",t)
        items=[r[0][:16] for r in q("select updated_at from orchestration_v2_projection_turn_items where thread_id=? and updated_at>='2026-10-28'",t)]
        reqs=q("select created_at, resolved_at from orchestration_v2_projection_runtime_requests where thread_id=?",t) if t!=coord else []
        threads[t]={'parent':meta[0][0],'rel':meta[0][1],'title':meta[0][2],'runs':runs,'items':sorted(set(items)),'reqs':reqs}
    out[sess]={'coord':coord,'threads':threads}
print(json.dumps(out))
