# Court Booking Checker

A small Flask web app that uses Playwright to scrape badminton court availability from the RecZone site and present results in a simple frontend.

This repo contains:

- `recorded.py` — the Playwright scraper functions (do not modify unless you know what you're doing).
- `app.py` — Flask backend that calls the scraper and streams logs/results via Server-Sent Events (SSE).
- `templates/index.html`, `static/main.js`, `static/styles.css` — the frontend UI.

## Quick start (Windows PowerShell)

1. Create and activate a virtual environment:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
```

2. Upgrade pip and install dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

3. Install Playwright browsers (required once):

```powershell
python -m playwright install chromium
```

4. Run the Flask app:

```powershell
python app.py

# or with flask CLI (optional):
$env:FLASK_APP = 'app.py'
flask run --host=0.0.0.0 --port=5000
```

5. Open the UI in your browser:

```
http://127.0.0.1:5000
```

## Development notes & best practices

- The scraper logic lives in `recorded.py`. The Flask app imports its functions — do not change the Playwright launch options inside `recorded.py`; any headless overrides are applied in `app.py` so the scraper file remains reusable for debugging.
- The app streams logs and partial results via SSE (`/events/<job_id>`). The frontend connects automatically after you POST to `/check_slots`.
- Keep secrets (if any) in an `.env` file (not committed). Use `python-dotenv` if you want to load env vars automatically.
- Use a virtual environment and pin dependency versions in `requirements.txt`.

## Production

- This project uses the Flask development server by default. For production, run the app under a WSGI server (Gunicorn / Uvicorn) behind a reverse proxy.
- Ensure Playwright browsers are installed on the host environment and that the service account running the app has the necessary permissions.
- If you expect concurrent scraping jobs or horizontal scaling, move job state out of memory into a broker (Redis/RQ, Celery, etc.).

## Recommended repository files

- `.gitignore` (included) to avoid committing virtual environments, caches, and secrets.
- Add a LICENSE if you plan to open-source the repo.

## Troubleshooting

- If Playwright raises errors about missing browsers, run `python -m playwright install`.
- First request may be slow as Playwright spins up Chromium — the frontend shows live logs while the scrape runs.
- If the site structure changes, `recorded.py` selectors may need updates.

## Example commands (copy-paste)

```powershell
# create venv and install
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

---
Happy scraping — file issues if you want CI, Docker, or a production-ready deployment workflow added.
