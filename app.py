from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from datetime import datetime
from playwright.sync_api import sync_playwright
import threading
import queue
import uuid
import json
import time

from recorded import get_available_slots_for_court, daterange
from logger import get_logger

app = Flask(__name__)

logger = get_logger(__name__)

# In-memory job store: job_id -> {queue, results, finished}
jobs = {}
jobs_lock = threading.Lock()


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
        logs_print = logger.info
        results = {}
        with sync_playwright() as p:
            # Monkeypatch the chromium.launch to force headless mode (only here)
            original_launch = p.chromium.launch

            def launch_override(*args, **kwargs):
                kwargs["headless"] = True
                kwargs["slow_mo"] = kwargs.get("slow_mo", 0)
                return original_launch(*args, **kwargs)

            p.chromium.launch = launch_override

            try:
                for date_str in daterange(start_date, end_date):
                    results[date_str] = {}
                    for court in range(1, 8):
                        label = f"Wooden Court {court}"
                        try:
                            q.put({"type": "log", "msg": f"{date_str} {label}: checking..."})
                            logs_print(f"{date_str} {label}: checking...")
                            slots = get_available_slots_for_court(p, court, date_str)
                            results[date_str][str(court)] = slots
                            q.put({"type": "log", "msg": f"{date_str} {label}: OK ({len(slots)} slots)"})
                            q.put({"type": "result_partial", "date": date_str, "court": str(court), "value": slots})
                            logs_print(f"{date_str} {label}: OK ({len(slots)} slots)")
                        except Exception as e:
                            results[date_str][str(court)] = "ERROR"
                            q.put({"type": "log", "msg": f"{date_str} {label}: ERROR: {type(e).__name__}: {e}"})
                            q.put({"type": "result_partial", "date": date_str, "court": str(court), "value": "ERROR"})
                            logger.error(f"{date_str} {label}: ERROR: {type(e).__name__}: {e}")
            finally:
                try:
                    p.chromium.launch = original_launch
                except Exception:
                    pass

        # mark done and send final results
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
        # Stream until we get a done message
        while True:
            try:
                item = q.get(timeout=300)
            except Exception:
                # keep-alive ping to prevent client timeouts
                try:
                    yield 'data: {}\n\n'
                except GeneratorExit:
                    break
                continue

            try:
                payload = json.dumps(item, default=str)
            except Exception:
                payload = json.dumps({'type':'log','msg':'<unserializable>'})

            yield f"data: {payload}\n\n"

            if isinstance(item, dict) and item.get('type') == 'done':
                break

    return Response(stream_with_context(gen()), mimetype='text/event-stream')


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
