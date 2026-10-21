"""Proves the ported functions match Scout Dev. Run: python3 -I check_port.py  (needs sourcing-scout-dev next to this repo)."""
import ast, os
B = os.path.expanduser("~/Claude_projects/sourcing-scout-dev/backend/")
def top(p):
    s = open(p).read()
    out = {}
    for n in ast.parse(s).body:
        if isinstance(n, ast.FunctionDef): out[n.name] = ast.get_source_segment(s, n)
        elif isinstance(n, ast.Assign) and hasattr(n.targets[0], "id"): out[n.targets[0].id] = ast.get_source_segment(s, n)
    return out
src = {**top(B + "order_confirm_engine.py"), **top(B + "scout_engine.py")}
bad = 0
for f in ("scout_port.py", "scout_port_buttons.py"):
    for n, body in top(f).items():
        o = src.get(n)
        if o is None: print(f"  new here   {n}"); continue
        same = o == body
        print(f"  {'identical' if same else 'DIFFERS  '} {n}")
        bad += not same
print("ALL MATCH" if not bad else f"{bad} DIFFER (expected only: AIRTABLE_PAT, create_autopilot_review_sheet, env-based ALLWHERE_AUTH/PS_AUTH)")
