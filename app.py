from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import queue
import uuid
import json
import time

from recorded import (
    check_single_court,
    check_all_courts_parallel,
    daterange,
)
from logger import get_logger

app = Flask(__name__)

logger = get_logger(__name__)

# In-memory job store: job_id -> {queue, results, finished}
jobs = {}
jobs_lock = threading.Lock()

# ---- Tuning ----
# Max parallel browsers. On Render Free (512MB), 3 is safe.
# On Render Starter (2GB), you can push to 5-7.
# Locally with 8GB+, try 4-7.
MAX_PARALLEL_COURTS = 2


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/check_slots", methods=["POST"])
def check_slots():
    data = request.get_json() or {}
    start_date = data.get("start_date")
    end_date = data.get("end_date") or start_date

    if not start_date:
        return jsonify({"error": "start_date is required"}), 400

    # Validate date format
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"error": "dates must be YYYY-MM-DD"}), 400

    if ed < sd:
        return jsonify({"error": "end_date must be same or after start_date"}), 400

    if (ed - sd).days > 2:
        return jsonify({"error": "Maximum allowed window is 3 days"}), 400

    # Create job
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
                """Runs in a thread. Returns (court, slots_or_error)."""
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

            # Run courts in parallel
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_COURTS) as executor:
                futures = {executor.submit(court_worker, c): c for c in courts}
                for future in as_completed(futures):
                    court, result = future.result()
                    results[date_str][str(court)] = result

            q.put({"type": "log", "msg": f"{date_str}: All courts checked."})

        # Mark done
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