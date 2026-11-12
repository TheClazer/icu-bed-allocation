"""Records a captioned walkthrough video of the running app.

  .venv\\Scripts\\python.exe tools\\record_demo.py  <output.mp4>

Needs the stack running (run.bat), Microsoft Edge, Playwright and ffmpeg.
Drives the real app: a drawn cursor, a blue ring around what is being clicked,
and a caption bar explaining each step. Resets the demo data first.
"""
import json
import time
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
W, H = 1600, 900

OVERLAY = r"""
(() => {
  if (window.top !== window) return;
  const css = `
  #tour-cap{position:fixed;left:22px;bottom:20px;z-index:2147483646;width:min(860px,56vw);pointer-events:none;
    background:#13202b;color:#fff;border-radius:8px;padding:13px 20px 14px;font:500 17px/1.42 Barlow,'Segoe UI',sans-serif;
    box-shadow:0 12px 32px rgba(19,32,43,.28);transition:opacity .3s;opacity:0}
  #tour-cap .t{display:flex;align-items:baseline;gap:10px;font:600 23px/1.15 'Barlow Condensed',Barlow,sans-serif;margin-bottom:3px}
  #tour-cap .n{color:#9db4ff;font:600 13px 'Geist Mono',monospace}
  #tour-ring{position:fixed;z-index:2147483645;border:3px solid #1f4fd1;border-radius:8px;
    box-shadow:0 0 0 7px rgba(31,79,209,.16);pointer-events:none;transition:all .4s ease;opacity:0}
  #tour-tag{position:fixed;z-index:2147483646;background:#1f4fd1;color:#fff;font:600 14px Barlow,sans-serif;
    padding:4px 10px;border-radius:4px;pointer-events:none;transition:all .4s ease;opacity:0;white-space:nowrap}
  #tour-cursor{position:fixed;z-index:2147483647;width:26px;height:26px;pointer-events:none;left:-60px;top:-60px}
  .tour-click{position:fixed;z-index:2147483646;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;
    border:2px solid #1f4fd1;pointer-events:none;animation:tourc .7s ease-out forwards}
  @keyframes tourc{to{transform:scale(3.6);opacity:0}}`;
  function setup() {
    if (document.getElementById('tour-cap')) return;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    const cap = document.createElement('div'); cap.id = 'tour-cap'; document.body.appendChild(cap);
    const ring = document.createElement('div'); ring.id = 'tour-ring'; document.body.appendChild(ring);
    const tag = document.createElement('div'); tag.id = 'tour-tag'; document.body.appendChild(tag);
    const cur = document.createElement('div'); cur.id = 'tour-cursor';
    cur.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7.5 19 2.6-7.9L21 10.5z" fill="#13202b" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cur);
    window.addEventListener('mousemove', (e) => { cur.style.left = (e.clientX - 3) + 'px'; cur.style.top = (e.clientY - 2) + 'px'; }, true);
    window.addEventListener('mousedown', (e) => {
      const r = document.createElement('div'); r.className = 'tour-click';
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.body.appendChild(r); setTimeout(() => r.remove(), 800);
    }, true);
  }
  window.__tour = {
    cap(n, title, text) {
      setup();
      const c = document.getElementById('tour-cap');
      c.innerHTML = `<div class="t"><span class="n">${n}</span><span>${title}</span></div><div>${text}</div>`;
      c.style.opacity = 1;
    },
    hide() { const c = document.getElementById('tour-cap'); if (c) c.style.opacity = 0; },
    ring(b, label) {
      setup();
      const r = document.getElementById('tour-ring'); const t = document.getElementById('tour-tag');
      const p = 6;
      Object.assign(r.style, { left: (b.x - p) + 'px', top: (b.y - p) + 'px', width: (b.width + 2 * p) + 'px', height: (b.height + 2 * p) + 'px', opacity: 1 });
      if (label) {
        t.textContent = label;
        const ty = b.y - p - 34 < 4 ? b.y + b.height + p + 8 : b.y - p - 34;
        Object.assign(t.style, { left: Math.max(6, Math.min(window.innerWidth - 360, b.x - p)) + 'px', top: ty + 'px', opacity: 1 });
      } else { t.style.opacity = 0; }
    },
    unring() { ['tour-ring', 'tour-tag'].forEach((id) => { const e = document.getElementById(id); if (e) e.style.opacity = 0; }); },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup); else setup();
})();
"""


def post(path, body=None):
    req = urllib.request.Request(BASE + "/api" + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main(out):
    post("/settings", {"booking_mode": "safe", "lock_ordering": True})
    post("/demo/reset")
    vid_dir = Path(tempfile.mkdtemp())

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True,
                                    args=["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vid_dir),
                                  record_video_size={"width": W, "height": H})
        ctx.add_init_script(OVERLAY)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        t0 = time.time()
        chapters = []

        def wait(ms):
            page.wait_for_timeout(ms)

        def cap(n, title, text, ms=0):
            if not chapters or chapters[-1][0] != n:
                chapters.append((n, title, time.time() - t0))
            page.evaluate("([n, t, x]) => window.__tour && window.__tour.cap(n, t, x)", [n, title, text])
            if ms:
                wait(ms)

        def ring(loc, label=None):
            try:   # centre the target so the caption bar at the bottom never hides it
                loc.evaluate("e => e.scrollIntoView({block: 'center', inline: 'nearest'})", timeout=5000)
                wait(250)
            except Exception:
                pass
            box = loc.bounding_box(timeout=5000)
            if box:
                page.evaluate("([b, l]) => window.__tour.ring(b, l)", [box, label])
            return box

        def unring():
            page.evaluate("() => window.__tour && window.__tour.unring()")

        def point(loc, label=None, steps=28, after=500):
            box = ring(loc, label)
            if box:
                page.mouse.move(box["x"] + min(box["width"] / 2, 120), box["y"] + box["height"] / 2, steps=steps)
            wait(after)
            return box

        def click(loc, label=None, after=900):
            box = point(loc, label, after=350)
            if box:
                page.mouse.down()
                page.mouse.up()
            else:
                loc.click()
            wait(300)
            unring()               # the page may re-layout after a click; never leave a stale ring
            wait(max(0, after - 300))

        main_tab = lambda name: page.locator("nav.tabs:not(.small) .tab", has_text=name)
        db_tab = lambda name: page.locator("nav.tabs.small .tab", has_text=name)
        card = lambda text: page.locator(".card", has_text=text).first

        # ------------------------------------------------------------ 1. cover
        page.goto(BASE + "/")
        page.mouse.move(300, 250)
        wait(1500)
        cap("1/12", "The cover screen", "This opens first when you start the app. Move the mouse around: a trail of the real booking SQL follows the cursor.")
        for i in range(60):
            page.mouse.move(300 + i * 17, 250 + 90 * ((i // 10) % 2) + (i % 10) * 6)
            wait(25)
        wait(1200)
        point(page.locator(".cover-vitals"), "Live numbers read from the database", after=2600)
        cap("1/12", "The cover screen", "Two ways in: the full control room, or only the database monitor in its own window. Click Open the control room.")
        click(page.get_by_role("button", name="Open the control room"), "Click here to enter", after=1500)

        # ------------------------------------------------------------ 2. layout tour
        unring()
        cap("2/12", "The control room has two halves", "Left: you use the system like a helpline would. Right: the live database, showing what MySQL and Redis are doing at this exact moment.", 3200)
        point(page.locator("main.main"), "Left: using the system", after=2200)
        point(page.locator("aside.console"), "Right: the LIVE DATABASE, always visible", after=3000)
        cap("2/12", "The live database panel", "Six vitals of the database, traced like an ICU monitor: queries per second, transactions, rows waiting on locks, deadlocks, replica lag and Redis activity.")
        point(page.locator(".vitals"), "Database vitals, updated every second", after=3800)
        cap("2/12", "Six views of the database", "Tables shows rows live. SQL log shows every statement. X-Ray shows locks and deadlocks. Redis, Metrics and a read-only Query box complete it.")
        point(page.locator("nav.tabs.small"), "Switch what you see about the database", after=3800)
        cap("2/12", "Controls in the top bar", "Who you are acting as, whether bookings lock rows, the order transfers lock beds, and the simulated clock used for hold expiry.")
        point(page.locator(".topbar .ctl").nth(0), "Acting as: pick a user", after=1700)
        point(page.locator(".topbar .ctl").nth(1), "Row lock on or off", after=1700)
        point(page.locator(".topbar .ctl").nth(2), "Lock ordering for transfers", after=1700)

        # ------------------------------------------------------------ 3. request a bed
        click(db_tab("Tables"), "Tables tab", after=600)
        cap("3/12", "Request a bed in plain English", "Type the request like a helpline operator would, or click an example. The parser fills the form and shows which words it understood.")
        click(page.locator(".chip", has_text="Patient Meera Rao"), "Click an example request", after=1600)
        point(page.locator(".parsed"), "What the parser extracted, and from which words", after=3200)
        point(page.locator(".form-grid"), "The form is filled in for you", after=2000)
        cap("3/12", "Book it", "One click runs a single MySQL transaction: find the nearest free ICU bed, lock it, create a 30 minute hold.")
        click(page.get_by_role("button", name="Find nearest bed and hold it"), "Find nearest bed and hold it", after=2200)
        cap("3/12", "The result, and how the database decided", "Hospital, bed, distance and a countdown. Below it, every statement in order: Redis finds nearby hospitals, then MySQL locks one bed and commits.")
        point(card("Allocation result").locator(".result-bed"), "The held bed", after=2600)
        point(card("Allocation result").locator(".timeline"), "Every statement the transaction ran", after=3600)
        cap("3/12", "Watch it land in the database", "The bed row just changed from FREE to HELD. Changed rows flash in the live table on the right.")
        point(page.locator(".console-body .tbl-wrap").first, "bed table, live from MySQL", after=3200)
        click(db_tab("SQL log"), "Now the SQL log", after=1200)
        point(page.locator(".console-body .tbl-wrap").first, "START TRANSACTION ... COMMIT, with timings", after=3600)
        cap("3/12", "Admit the patient", "When the ambulance arrives, admit: the hold becomes ADMITTED and the bed OCCUPIED, in one more transaction.")
        click(page.get_by_role("button", name="Patient arrived: admit"), "Patient arrived: admit", after=2200)

        # ------------------------------------------------------------ 4. dashboard
        click(main_tab("City dashboard"), "City dashboard tab", after=1500)
        cap("4/12", "The city at a glance", "Every square is one bed. Solid blue is free, an outline is on hold, dark is occupied. Click a hospital to open its beds.")
        point(page.locator(".census"), "One row per hospital, one square per bed", after=3200)
        click(page.locator(".census tr", has_text="Koramangala Multispeciality"), "Open a hospital", after=1500)
        point(card("bed board read straight from MySQL"), "Its beds: discharge, transfer or maintenance from here", after=3200)

        # ------------------------------------------------------------ 5. race
        click(main_tab("Demo lab"), "Demo lab tab", after=1500)
        cap("5/12", "Demo lab: try to break it", "Each card provokes one database behaviour. First: two ambulances race for the only free ventilator bed at the same instant.")
        race = card("Race for the last bed")
        point(race, "Demo 1: race for the last bed", after=2400)
        click(db_tab("SQL log"), None, after=400)
        click(race.get_by_role("button", name="Start the race"), "Start the race", after=4200)
        cap("5/12", "Exactly one wins", "Row locks (FOR UPDATE SKIP LOCKED): A locks the bed, B skips the locked row instead of waiting and finds nothing. One live hold, every time.")
        point(race.locator(".versus"), "Both requests, side by side", after=3600)
        point(race.locator(".verdict"), "The database guarantees one hold", after=2400)
        cap("5/12", "Now remove the lock", "Switch to No lock. Both requests now see the bed as free. Watch what stops the double booking.")
        click(race.get_by_role("button", name="Free the bed for a rerun"), "Free the bed for a rerun", after=1400)
        click(race.get_by_role("radio", name="No lock (unsafe)"), "Turn the lock off", after=800)
        click(race.get_by_role("button", name="Start the race"), "Race again", after=5000)
        cap("5/12", "The database caught it", "Request B fails with MySQL error 1062: the UNIQUE index on live holds refuses a second hold on the same bed. The constraint is the last line of defence.")
        point(race.locator(".versus"), "Error 1062 from the UNIQUE index", after=4200)
        click(race.get_by_role("radio", name="Row lock (safe)"), "Back to row locks", after=900)

        # ------------------------------------------------------------ 6. expiry
        exp = card("Holds expire by themselves")
        cap("6/12", "Holds expire by themselves", "A hold lasts 30 minutes. Jump the simulated clock forward: a MySQL EVENT expires the hold and a trigger frees the bed. The app does nothing.")
        click(exp.get_by_role("button", name="Fast-forward 30 minutes"), "Fast-forward 30 minutes", after=1000)
        try:
            exp.locator(".verdict.ok").wait_for(timeout=12000)
        except Exception:
            pass
        point(exp.locator(".demo-out"), "Expired inside MySQL, no app code involved", after=3400)

        # ------------------------------------------------------------ 7. deadlock
        dl = card("Crossing transfers and deadlock")
        cap("7/12", "Deadlock", "Two wards move two patients into each other's beds at once. With locks taken in request order, each waits for the other.")
        click(dl.get_by_role("radio", name="Request order (deadlock-prone)"), "Lock in request order", after=700)
        click(db_tab("X-Ray"), "Open X-Ray", after=500)
        click(dl.get_by_role("button", name="Run both transfers"), "Run both transfers", after=600)
        cap("7/12", "Deadlock", "Watch X-Ray: active transactions and row locks appear while the transfers wait.")
        wait(5200)
        cap("7/12", "InnoDB detected the cycle", "MySQL found the cycle in the wait-for graph and rolled one transfer back with error 1213. The other completed. The graph shows who waited for whom.")
        point(dl.locator(".graph").first, "Wait-for graph: the cycle and the victim", after=4200)
        click(dl.get_by_role("radio", name="Ordered locks (prevention on)"), "Prevention: always lock the lower bed first", after=1200)

        # ------------------------------------------------------------ 8. crash
        cr = card("Kill the database in the middle of a transfer")
        cap("8/12", "Kill the database mid-transaction", "A transfer frees the old bed but has not taken the new one. Then the MySQL server is killed outright, like pulling the plug.")
        point(cr, "Demo 4: crash recovery", after=2200)
        click(cr.get_by_role("button", name="Start transfer, then kill MySQL"), "Start transfer, then kill MySQL", after=1500)
        cap("8/12", "Crash recovery", "MySQL goes down (red banner), restarts and runs crash recovery: committed work is replayed, the unfinished transaction is rolled back.")
        try:
            cr.get_by_text("After recovery").wait_for(timeout=120000)
        except Exception:
            pass
        wait(800)
        point(cr.locator(".demo-out"), "Before and after are identical: nothing half-moved", after=4200)
        try:
            point(cr.locator(".loglines"), "MySQL's own log: 'Rolling back trx ... rows to undo'", after=4200)
        except Exception:
            pass

        # ------------------------------------------------------------ 9. audit
        au = card("Bed blocking and the audit")
        cap("9/12", "Bed blocking and the audit", "A fake account tries to hoard 8 beds. A trigger refuses everything after 5. Then the audit query flags the account.")
        click(au.get_by_role("button", name="Spam 8 fake holds"), "Spam 8 fake holds", after=2600)
        click(au.get_by_role("button", name="Run audit query"), "Run audit query", after=2200)
        point(au.locator(".demo-out"), "5 held, 3 refused by the trigger, account flagged", after=4000)

        # ------------------------------------------------------------ 10. replication
        rp = card("Read replica and replication lag")
        cap("10/12", "A second MySQL server", "Every commit is copied to a read replica. Pause it, book a bed, and the two servers disagree until you resume.")
        click(rp.get_by_role("button", name="Pause replica"), "Pause replica", after=1200)
        click(rp.get_by_role("button", name="Book one bed on the primary"), "Book on the primary", after=2600)
        point(rp.locator(".versus"), "Primary has the hold, replica does not yet", after=3800)
        click(rp.get_by_role("button", name="Resume replica"), "Resume: the replica catches up", after=2400)

        # ------------------------------------------------------------ 11. query
        ck = card("Check it yourself")
        cap("11/12", "Check it yourself", "The Query tab runs your own SQL as a read-only MySQL user. Try to delete something: MySQL itself refuses.")
        click(ck.get_by_role("button", name="Try to DELETE (refused)"), "Try to DELETE", after=2400)
        point(page.locator(".console-body .verdict"), "Error 1142: the read-only user cannot write", after=3600)
        click(ck.get_by_role("button", name="EXPLAIN the booking query"), "EXPLAIN the booking query", after=2400)
        point(page.locator(".console-body .tbl-wrap").first, "The booking query uses the index idx_bed_search", after=3400)

        # ------------------------------------------------------------ 12. wrap up
        cap("12/12", "Where the live database is", "Always on the right of the control room. Pop it out into its own window with Pop out, or open localhost:8000/console. MySQL Workbench can connect to localhost:3307.")
        point(page.locator(".console-head a", has_text="Pop out"), "Pop out the live database", after=4200)
        rs = card("Reset demo data")
        cap("12/12", "Between runs", "Reset demo data puts everything back. To start the whole system, double-click Start ICU Bed System.bat. stop.bat stops it.")
        point(rs, "Reset demo data", after=4200)
        unring()
        wait(1500)

        video = page.video.path()
        ctx.close()
        browser.close()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], check=True)
    post("/settings", {"booking_mode": "safe", "lock_ordering": True})
    post("/demo/reset")
    for n, title, t in chapters:
        print(f"{int(t // 60)}:{int(t % 60):02d}  {n}  {title}")
    print("saved", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo.mp4")
