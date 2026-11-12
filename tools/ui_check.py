"""Clicks through every flow of the running app and reports what works.

  .venv\\Scripts\\python.exe tools\\ui_check.py [screenshot_dir]

Resets demo data first and at the end. Needs the stack running and Microsoft Edge.
"""
import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("ui_check")
SHOTS.mkdir(parents=True, exist_ok=True)
results = []


def post(path, body=None):
    req = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def check(name, fn, page):
    try:
        fn()
        results.append((name, "PASS", ""))
    except Exception as exc:
        msg = str(exc).splitlines()[0][:160]
        results.append((name, "FAIL", msg))
        page.screenshot(path=str(SHOTS / f"fail_{len(results):02d}.png"))


post("/settings", {"booking_mode": "safe", "lock_ordering": True})
post("/demo/reset")

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("dialog", lambda d: d.accept())
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    T = 20000

    view = lambda: page.locator(".page > div:not([hidden])")

    def card(text):
        return page.locator(".scen-stage > div:not([hidden])").filter(has_text=text)

    # cover
    def cover():
        page.goto(BASE + "/")
        page.get_by_text("ICU DBMS").first.wait_for(timeout=T) if False else None
        page.get_by_role("button", name="Open the control room").click(timeout=T)
        page.get_by_role("heading", name="Book a bed").wait_for(timeout=T)
    check("Cover opens the control room", cover, page)

    # book flow
    def book():
        page.get_by_role("button", name="Patient Meera Rao, 45 year old female, ICU near koramangla, serious").click(timeout=T)
        assert "Meera Rao" in page.locator("#describe").input_value()
        page.get_by_role("button", name="Continue").click(timeout=T)
        view().locator(".confirm-line").get_by_text("Koramangala").wait_for(timeout=T)
        page.get_by_role("button", name="Hold the nearest bed").click(timeout=T)
        page.locator(".held-num").wait_for(timeout=T)
        page.locator(".db-did summary").click()
        page.locator(".db-did .timeline li").first.wait_for(timeout=T)
    check("Book: describe, confirm, bed held, statements shown", book, page)

    def admit():
        page.get_by_role("button", name="Patient arrived, admit").click(timeout=T)
        view().get_by_text("Patient admitted").wait_for(timeout=T)
    check("Book: admit", admit, page)

    def open_tx():
        page.get_by_role("button", name="Open this transaction in the database").click(timeout=T)
        view().get_by_role("heading", name="Activity").wait_for(timeout=T)
        page.locator(".sq").filter(has_text="COMMIT").first.wait_for(timeout=T)
    check("Book: jump to the transaction in Activity", open_tx, page)

    def manual():
        page.get_by_role("button", name="Book a bed", exact=True).click()
        page.get_by_role("button", name="Book another patient").click(timeout=T)
        page.get_by_role("button", name="Fill in the details yourself").click(timeout=T)
        page.locator("#pn").fill("Test Manual")
        page.get_by_role("radio", name="Oxygen").click()
        page.get_by_role("button", name="Hold the nearest bed").click(timeout=T)
        page.locator(".held-num").wait_for(timeout=T)
        page.get_by_role("button", name="Cancel hold").click()
        view().get_by_text("Hold cancelled").wait_for(timeout=T)
    check("Book: manual form, hold, cancel", manual, page)

    # database views
    def dbviews():
        page.get_by_role("button", name="Database", exact=True).click()
        for sub, probe in (("Beds", ".census"), ("Tables", ".tbl"), ("Activity", ".sqllog"),
                           ("Locks", ".graph"), ("Redis", ".tbl"), ("Health", ".vitals"), ("Ask", "textarea")):
            page.locator(".db-nav nav button").filter(has_text=sub).click()
            page.locator(f".db-main {probe}").first.wait_for(timeout=T)
    check("Database: all seven views load", dbviews, page)

    def beds():
        page.locator(".db-nav nav button").filter(has_text="Beds").click()
        page.locator(".census tr", has_text="Hebbal City Hospital").click()
        view().locator(".card-title", has_text="Hebbal City Hospital").wait_for(timeout=T)
        page.locator(".bed .id").first.wait_for(timeout=T)
    check("Database: Beds opens a hospital bed board", beds, page)

    def ask():
        page.locator(".db-nav nav button").filter(has_text="Ask").click()
        page.locator(".db-main textarea").fill("DELETE FROM bed WHERE bed_id = 101")
        view().locator(".db-main .btn.primary").click()
        view().get_by_text("1142").first.wait_for(timeout=T)
    check("Database: Ask refuses DELETE (1142)", ask, page)

    # scenarios
    def go_scen(name):
        page.get_by_role("button", name="Scenarios", exact=True).click()
        page.locator(".scen-index li button").filter(has_text=name).click()

    def race():
        go_scen("Race for the last bed")
        c = card("Race for the last bed")
        c.get_by_role("button", name="Start the race").click()
        c.locator(".verdict.ok").wait_for(timeout=T)
        c.get_by_role("button", name="Free the bed for a rerun").click()
        c.get_by_role("radio", name="No lock (unsafe)").click()
        c.get_by_role("button", name="Start the race").click()
        c.get_by_text("1062").first.wait_for(timeout=T)
        c.get_by_role("radio", name="Row lock (safe)").click()
    check("Scenario: race (safe winner, then 1062 without lock)", race, page)

    def expiry():
        go_scen("Holds expire")
        c = card("Holds expire by themselves")
        c.get_by_role("button", name="Fast-forward 30 minutes").click()
        c.locator(".verdict.ok").wait_for(timeout=T)
    check("Scenario: holds expire through the MySQL event", expiry, page)

    def deadlock():
        go_scen("Deadlock")
        c = card("Crossing transfers")
        c.get_by_role("radio", name="Request order (deadlock-prone)").click()
        c.get_by_role("button", name="Run both transfers").click()
        c.get_by_text("1213").first.wait_for(timeout=T)
        c.locator(".graph").first.wait_for(timeout=T)
        c.get_by_role("radio", name="Ordered locks (prevention on)").click()
        c.get_by_role("button", name="Run both transfers").click()
        c.get_by_text("Both transfers completed").first.wait_for(timeout=40000)
    check("Scenario: deadlock 1213, then ordered locks complete", deadlock, page)

    def hoarding():
        go_scen("Bed hoarding")
        c = card("Bed blocking")
        c.get_by_role("button", name="Spam 8 fake holds").click()
        c.get_by_text("5 held, 3 refused").wait_for(timeout=T)
        c.get_by_role("button", name="Run audit query").click()
        c.get_by_text("BED BLOCKING").wait_for(timeout=T)
    check("Scenario: hold limit trigger and audit flag", hoarding, page)

    def replica():
        go_scen("Replica lag")
        c = card("Read replica")
        c.get_by_role("button", name="Pause replica").click()
        c.get_by_role("button", name="Book one bed on the primary").click()
        c.locator(".versus").wait_for(timeout=T)
        c.get_by_role("button", name="Resume replica").click()
        page.wait_for_timeout(1500)
    check("Scenario: replica pause, book, resume", replica, page)

    def redis():
        go_scen("Redis outage")
        c = card("Redis outage")
        c.get_by_role("button", name="Stop Redis").click()
        page.wait_for_timeout(2500)
        c.get_by_role("button", name="Book an ICU bed now").click()
        c.locator(".verdict").get_by_text("ST_Distance_Sphere").wait_for(timeout=T)
        c.get_by_role("button", name="Start Redis and rebuild").click()
        c.get_by_text("Redis up").first.wait_for(timeout=40000)
    check("Scenario: Redis outage falls back to MySQL, then rebuilds", redis, page)

    def yourself():
        go_scen("Try it yourself")
        c = card("Check it yourself")
        c.get_by_role("button", name="EXPLAIN the booking query").click()
        view().get_by_role("heading", name="Ask").wait_for(timeout=T)
        view().locator(".tbl").get_by_text("idx_bed_search").first.wait_for(timeout=T)
    check("Scenario: try it yourself opens EXPLAIN in Ask", yourself, page)

    def crash():
        go_scen("Kill the database")
        c = card("Kill the database")
        c.get_by_role("button", name="Start transfer, then kill MySQL").click()
        c.locator("th", has_text="After recovery").wait_for(timeout=150000)
        c.get_by_text("No bed is half-moved").first.wait_for(timeout=T)
    check("Scenario: kill MySQL mid-transfer and recover", crash, page)

    def console():
        page2 = b.new_page(viewport={"width": 1440, "height": 900})
        page2.goto(BASE + "/console#place=database&sub=tables")
        page2.locator(".tbl").first.wait_for(timeout=T)
        page2.close()
    check("Pop-out database window", console, page)

    if errors:
        results.append(("No JavaScript errors", "FAIL", errors[0][:160]))
    else:
        results.append(("No JavaScript errors", "PASS", ""))
    b.close()

post("/settings", {"booking_mode": "safe", "lock_ordering": True})
post("/demo/reset")
for n, s, m in results:
    print(f"{s}  {n}" + (f"  ->  {m}" if m else ""))
print(f"{sum(1 for r in results if r[1] == 'PASS')}/{len(results)} passed")
