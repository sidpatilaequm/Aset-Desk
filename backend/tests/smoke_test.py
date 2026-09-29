"""End-to-end smoke test of every workflow.
Run against an EMPTY test database with DEV_LOGIN=true and ADMIN_EMAILS=admin@acme.test:
    python tests/smoke_test.py
"""
import sys; import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from fastapi.testclient import TestClient
from app.main import app
H = {"X-Requested-With": "AssetDesk"}

def login(email, name):
    c = TestClient(app); c.headers.update(H)
    r = c.post("/auth/dev", data={"email": email, "name": name}, follow_redirects=False); assert r.status_code == 303, r.text
    return c

def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text); return r.json() if r.headers.get("content-type","").startswith("application/json") else r.text

admin = login("admin@acme.test", "Asha Admin")
st = ok(admin.get("/api/state")); print("admin role:", st["me"]["role"], "| owner:", st["me"]["isOwner"])
itam = login("itam@acme.test", "Ivan AssetMgr"); itm = login("itmgr@acme.test", "Ira ITManager")
fin = login("fin@acme.test", "Farah Finance"); fin2 = login("fin2@acme.test", "Fred Finance")
sup = login("support@acme.test", "Sam Support"); emp = login("emp@acme.test", "Esha Employee")
people = {p["email"]: p["id"] for p in ok(admin.get("/api/state"))["people"]}
for e, role in [("itam@acme.test","IT Asset Manager"),("itmgr@acme.test","IT Manager"),("fin@acme.test","Finance"),("fin2@acme.test","Finance"),("support@acme.test","IT Support")]:
    ok(admin.put(f"/api/people/{people[e]}/role", json={"role": role}))
# CSRF guard
r = TestClient(app).post("/api/assets", json={}); print("no header ->", r.status_code)
# employee cannot create assets
print("employee create ->", emp.post("/api/assets", json={"name":"x","cost":1}).status_code)
a1 = ok(itam.post("/api/assets", json={"name":"ThinkPad X1","category":"Laptop","serial":"PF3KX91","cost":150000,"life":3,"method":"SL","purchaseDate":"2025-06-01","inServiceDate":"2025-06-01"}))
a2 = ok(itam.post("/api/assets", json={"name":"iPhone 15","category":"Mobile phone","serial":"F2LZQ8","cost":80000,"life":2,"method":"WDV","rate":40,"purchaseDate":"2026-01-10","inServiceDate":"2026-01-10"}))
print("created:", a1["id"], a2["id"])
# admin cannot allocate (segregation)
print("admin allocate ->", admin.post(f"/api/assets/{a1['id']}/allocate", json={"to": people["emp@acme.test"]}).status_code)
x = ok(itam.post(f"/api/assets/{a1['id']}/allocate", json={"to": people["emp@acme.test"], "when": "2026-09-28T14:45:00+05:30", "note": "with charger"}))
print("allocatedAt:", x["allocatedAt"], x["status"])
ok(itam.post(f"/api/assets/{a2['id']}/allocate", json={"to": people["emp@acme.test"]}))
ok(emp.post(f"/api/assets/{a1['id']}/acknowledge", json={"name":"Esha Employee"}))
print("employee sees assets:", [a["id"] for a in ok(emp.get("/api/state"))["assets"]])
# ticket on someone else's asset is refused; on own works
a3 = ok(itam.post("/api/assets", json={"name":"Monitor","category":"Monitor","serial":"CN0XYZ","cost":20000,"life":5}))
print("ticket on unallocated ->", emp.post("/api/tickets", json={"assetId": a3["id"], "category":"Hardware fault","body":"broken screen"}).status_code)
t = ok(emp.post("/api/tickets", json={"assetId": a1["id"], "category":"Hardware fault","priority":"High","body":"Screen flickers after waking"}))
print("ticket:", t["id"], t["status"], t["assetSerial"])
ok(sup.post(f"/api/tickets/{t['id']}/repair", json={"on": True}))
ok(sup.post(f"/api/tickets/{t['id']}/messages", json={"body":"Internal: order cable","kind":"internal","status":"Open"}))
ok(sup.post(f"/api/tickets/{t['id']}/messages", json={"body":"Try a driver update","kind":"public","status":"Pending"}))
ms = ok(emp.get(f"/api/tickets/{t['id']}/messages")); print("employee sees internal?", any(m["kind"]=="internal" for m in ms), "| msgs:", len(ms))
ok(emp.post(f"/api/tickets/{t['id']}/messages", json={"body":"Still flickering"}))
print("solve w/o text ->", sup.post(f"/api/tickets/{t['id']}/messages", json={"body":"","status":"Solved"}).status_code)
t2 = ok(sup.post(f"/api/tickets/{t['id']}/messages", json={"body":"Replaced the display cable.","status":"Solved"}))
print("solved:", t2["status"], "| asset:", [a for a in ok(itam.get("/api/state"))["assets"] if a["id"]==a1["id"]][0]["status"])
ok(emp.post(f"/api/tickets/{t['id']}/confirm", json={"fixed": True})); ok(emp.post(f"/api/tickets/{t['id']}/rate", json={"rating":"good"}))
# routine return of a2
rr = ok(emp.post("/api/returns", json={"assetIds":[a2["id"]], "reason":"Routine return", "plannedAt":"2026-10-01T10:00"}))
print("dup return ->", emp.post("/api/returns", json={"assetIds":[a2["id"]]}).status_code)
print("self-receive blocked? (employee lacks perm) ->", emp.post(f"/api/returns/{rr['id']}/items/a-{a2['id']}/receive", json={"condition":"Good"}).status_code)
rr = ok(itam.post(f"/api/returns/{rr['id']}/items/a-{a2['id']}/receive", json={"condition":"Good"}))
print("return:", rr["stage"])
# sale of a2 to employee: itam creates -> fin approves -> employee accepts
s = ok(itam.post("/api/sales", json={"assetId": a2["id"], "employeeId": people["emp@acme.test"], "price": 30000, "instalments": 6, "startMonth": "2026-10"}))
print("sale:", s["id"], s["stage"], [i["amount"] for i in s["schedule"]][-1], "| bv:", s["bookValueAtOffer"])
s = ok(fin.post(f"/api/sales/{s['id']}/approve", json={"approve": True}))
print("buyer accept w/o consent ->", emp.post(f"/api/sales/{s['id']}/accept", json={"accept":True,"name":"Esha"}).status_code)
s = ok(emp.post(f"/api/sales/{s['id']}/accept", json={"accept":True,"consent":True,"name":"Esha Employee"}))
print("sold:", s["stage"], "| asset status:", [a for a in ok(itam.get("/api/state"))["assets"] if a["id"]==a2["id"]][0]["status"])
pr = ok(fin.get("/api/payroll?month=2026-10")); print("payroll Oct:", [(l["ref"], l["amount"], l["status"]) for l in pr["lines"]])
ok(fin.post("/api/payroll/deduct", json={"lines":[{"kind":"sale","ref":s["id"],"no":1}]}))
print("csv:", fin.get("/api/payroll.csv?month=2026-10").text.splitlines()[1][:80])
# exit clearance
ex = ok(emp.post("/api/exits", json={"lastDay":"2026-10-31","reason":"Resignation","assetIds":[],"otherItems":["Access card"],"confirm":True}))
print("exit:", ex["id"], ex["stage"], "| items:", [i["name"] for i in ex["items"]])
ex = ok(itam.post(f"/api/returns/{ex['id']}/items/o-0/receive", json={"condition":"Good"}))
print("after receive with undeclared laptop:", ex["stage"])
ex = ok(itam.post(f"/api/returns/{ex['id']}/add-asset", json={"assetId": a1["id"]}))
ex = ok(itam.post(f"/api/returns/{ex['id']}/items/a-{a1['id']}/receive", json={"condition":"Damaged","recovery":5000,"note":"cracked bezel"}))
print("stage:", ex["stage"])
print("finance too early ->", fin.post(f"/api/returns/{ex['id']}/finance-signoff", json={"approve":True}).status_code)
ex = ok(itm.post(f"/api/returns/{ex['id']}/it-signoff", json={"approve":True,"comment":"Accounts disabled"}))
out = ok(fin.get(f"/api/returns/{ex['id']}/outstanding"))["outstanding"]; print("outstanding sale balance:", out)
ex = ok(fin.post(f"/api/returns/{ex['id']}/finance-signoff", json={"approve":True,"deduction":5000+out,"comment":"Damage + balance"}))
print("cleared:", ex["stage"], ex["signoffs"]["finance"]["deduction"])
print("sale schedule now:", [i["status"] for i in ok(fin.get("/api/state"))["sales"][0]["schedule"]])
print("certificate:", emp.get(f"/api/returns/{ex['id']}/certificate").status_code)
print("payroll Oct incl F&F:", [(l["ref"], l["amount"]) for l in ok(fin.get("/api/payroll?month=2026-10"))["lines"]])
hist = [a for a in ok(itam.get("/api/state"))["assets"] if a["id"]==a1["id"]][0]
print("laptop allocations:", [(x["from"], x["until"], x["returnCondition"]) for x in hist["allocations"]])
