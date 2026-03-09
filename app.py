from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import queue
import uuid
import json
import time
import atexit

from recorded import (
    check_single_court,
    check_all_courts_parallel,
    daterange,
)
from logger import get_logger

app = Flask(__name__)
logger = get_logger(__name__)

# =========================================================
# In-memory cache for background-fetched slot data
# =========================================================
# Structure: { "2026-03-10": { "1": [...], "2": [...], ... }, ... }
slot_cache = {}
cache_lock = threading.Lock()
cache_meta = {
    "last_updated": None,       # datetime of last successful full refresh
    "next_update": None,        # datetime of next scheduled refresh
    "is_running": False,        # whether a background job is currently running
    "last_error": None,         # last error message if any
    "courts_checked": 0,        # progress counter
    "courts_total": 0,          # total courts to check
}

# =========================================================
# In-memory job store for manual searches (unchanged)
# =========================================================
jobs = {}
jobs_lock = threading.Lock()

# ---- Tuning ----
MAX_PARALLEL_COURTS = 3
CACHE_DAYS_AHEAD = 3  # today + 2 more days
REFRESH_INTERVAL_MINUTES = 60


# =========================================================
# Background cache refresh logic
# =========================================================

def refresh_slot_cache():
    """Called by APScheduler every hour. Scrapes slots for next 3 days."""
    if cache_meta["is_running"]:
        logger.info("[Cache] Refresh already running, skipping.")
        return

    cache_meta["is_running"] = True
    cache_meta["courts_checked"] = 0
    cache_meta["last_error"] = None

    today = datetime.now().date()
    dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(CACHE_DAYS_AHEAD)]
    courts = list(range(1, 8))
    total = len(dates) * len(courts)
    cache_meta["courts_total"] = total

    logger.info(f"[Cache] Starting refresh for dates: {dates}")

    new_cache = {}
    checked = 0

    for date_str in dates:
        new_cache[date_str] = {}

        def on_progress(court, status, data):
            nonlocal checked
            checked += 1
            cache_meta["courts_checked"] = checked
            label = f"Wooden Court {court}"
            if status == "ok":
                logger.info(f"[Cache] {date_str} {label}: {len(data)} slots")
            else:
                logger.error(f"[Cache] {date_str} {label}: ERROR - {data}")

        try:
            results = check_all_courts_parallel(
                date_str,
                courts=courts,
                max_workers=MAX_PARALLEL_COURTS,
                progress_callback=on_progress,
            )
            new_cache[date_str] = results
        except Exception as e:
            logger.error(f"[Cache] Failed for {date_str}: {e}")
            cache_meta["last_error"] = str(e)
            # Keep partial results
            new_cache[date_str] = new_cache.get(date_str, {})

    # Swap cache atomically
    with cache_lock:
        slot_cache.clear()
        slot_cache.update(new_cache)

    now = datetime.now()
    cache_meta["last_updated"] = now.isoformat()
    cache_meta["next_update"] = (now + timedelta(minutes=REFRESH_INTERVAL_MINUTES)).isoformat()
    cache_meta["is_running"] = False
    cache_meta["courts_checked"] = total

    logger.info(f"[Cache] Refresh complete. {checked}/{total} courts checked.")


# =========================================================
# APScheduler setup
# =========================================================

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    refresh_slot_cache,
    "interval",
    minutes=REFRESH_INTERVAL_MINUTES,
    id="slot_cache_refresh",
    next_run_time=datetime.now() + timedelta(seconds=5),  # first run 5s after startup
)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))


# =========================================================
# Routes
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/cached_slots")
def cached_slots():
    """Return pre-fetched slot data instantly."""
    with cache_lock:
        data = dict(slot_cache)

    return jsonify({
        "slots": data,
        "meta": {
            "last_updated": cache_meta["last_updated"],
            "next_update": cache_meta["next_update"],
            "is_refreshing": cache_meta["is_running"],
            "courts_checked": cache_meta["courts_checked"],
            "courts_total": cache_meta["courts_total"],
            "last_error": cache_meta["last_error"],
        }
    })


@app.route("/api/refresh", methods=["POST"])
def trigger_refresh():
    """Manually trigger a cache refresh."""
    if cache_meta["is_running"]:
        return jsonify({"status": "already_running"}), 409

    thread = threading.Thread(target=refresh_slot_cache, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/check_slots", methods=["POST"])
def check_slots():
    """Manual custom date range search (existing flow, unchanged)."""
    data = request.get_json() or {}
    start_date = data.get("start_date")
    end_date = data.get("end_date") or start_date

    if not start_date:
        return jsonify({"error": "start_date is required"}), 400

    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "dates must be YYYY-MM-DD"}), 400

    if ed < sd:
        return jsonify({"error": "end_date must be same or after start_date"}), 400

    if (ed - sd).days > 2:
        return jsonify({"error": "Maximum allowed window is 3 days"}), 400

    job_id = uuid.uuid4().hex
    q = queue.Queue()
    job = {"queue": q, "results": {}, "finished": False}
    with jobs_lock:
        jobs[job_id] = job

    def run_job():
        results = {}

        for date_str in daterange(start_date, end_date):
            results[date_str] = {}
            q.put({"type": "log", "msg": f"{date_str}: Starting parallel check for 7 courts..."})

            courts = list(range(1, 8))

            def court_worker(court):
                label = f"Wooden Court {court}"
                q.put({"type": "log", "msg": f"{date_str} {label}: checking..."})
                logger.info(f"{date_str} {label}: checking...")
                try:
                    slots = check_single_court(court, date_str)
                    q.put({"type": "log", "msg": f"{date_str} {label}: OK ({len(slots)} slots)"})
                    q.put({"type": "result_partial", "date": date_str, "court": str(court), "value": slots})
                    logger.info(f"{date_str} {label}: OK ({len(slots)} slots)")
                    return (court, slots)
                except Exception as e:
                    q.put({"type": "log", "msg": f"{date_str} {label}: ERROR: {type(e).__name__}: {e}"})
                    q.put({"type": "result_partial", "date": date_str, "court": str(court), "value": "ERROR"})
                    logger.error(f"{date_str} {label}: ERROR: {type(e).__name__}: {e}")
                    return (court, "ERROR")

            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_COURTS) as executor:
                futures = {executor.submit(court_worker, c): c for c in courts}
                for future in as_completed(futures):
                    court, result = future.result()
                    results[date_str][str(court)] = result

            q.put({"type": "log", "msg": f"{date_str}: All courts checked."})

        q.put({"type": "done", "results": results})
        with jobs_lock:
            job_entry = jobs.get(job_id)
            if job_entry is not None:
                job_entry["results"] = results
                job_entry["finished"] = True

    thread = threading.Thread(target=run_job, daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@app.route('/events/<job_id>')
def events(job_id):
    def gen():
        with jobs_lock:
            job = jobs.get(job_id)
        if job is None:
            yield f"data: {json.dumps({'type':'error','msg':'unknown job_id'})}\n\n"
            return

        q = job['queue']
        while True:
            try:
                item = q.get(timeout=300)
            except Exception:
                try:
                    yield 'data: {}\n\n'
                except GeneratorExit:
                    break
                continue

            try:
                payload = json.dumps(item, default=str)
            except Exception:
                payload = json.dumps({'type': 'log', 'msg': '<unserializable>'})

            yield f"data: {payload}\n\n"

            if isinstance(item, dict) and item.get('type') == 'done':
                break

    return Response(stream_with_context(gen()), mimetype='text/event-stream')


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)