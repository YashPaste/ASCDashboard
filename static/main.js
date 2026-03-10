document.addEventListener('DOMContentLoaded', function () {
  const startInput = document.getElementById('start');
  const endInput = document.getElementById('end');
  const checkBtn = document.getElementById('check');
  const loader = document.getElementById('loader');
  const elapsedSpan = document.getElementById('elapsed');
  const logsPre = document.getElementById('logs');
  const resultsDiv = document.getElementById('results');

  let timerId = null;
  let elapsed = 0;

  function startTimer() {
    elapsed = 0;
    elapsedSpan.textContent = `Elapsed: ${elapsed}s`;
    timerId = setInterval(() => {
      elapsed += 1;
      elapsedSpan.textContent = `Elapsed: ${elapsed}s`;
    }, 1000);
  }

  function stopTimer() {
    if (timerId) {
      clearInterval(timerId);
      timerId = null;
    }
  }

  function validateClient(start, end) {
    if (!start) return 'Start date is required';
    const sd = new Date(start);
    const ed = end ? new Date(end) : sd;
    if (ed < sd) return 'End date must be same or after start date';
    const diff = (ed - sd) / (1000 * 60 * 60 * 24);
    if (diff > 2) return 'Maximum allowed window is 3 days';
    return null;
  }

  checkBtn.addEventListener('click', async () => {
    const start = startInput.value;
    const end = endInput.value || start;

    const v = validateClient(start, end);
    if (v) {
      alert(v);
      return;
    }

    // UI
    checkBtn.disabled = true;
    loader.classList.remove('hidden');
    logsPre.textContent = '';
    resultsDiv.innerHTML = '';
    startTimer();

    try {
      const resp = await fetch('/check_slots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_date: start, end_date: end }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        throw new Error(err && err.error ? err.error : 'Request failed');
      }

      const data = await resp.json();
      const jobId = data.job_id;
      if (!jobId) throw new Error('No job_id returned');

      // Open SSE connection for realtime logs/results
      const eventsUrl = `/events/${jobId}`;
      const es = new EventSource(eventsUrl);

      // Keep an in-memory results structure to update incrementally
      const results = {};

      es.onmessage = (e) => {
        if (!e.data) return;
        let msg = null;
        try {
          msg = JSON.parse(e.data);
        } catch (err) {
          // ignore parse errors
          return;
        }

        if (msg.type === 'log') {
          logsPre.textContent += (logsPre.textContent ? '\n' : '') + msg.msg;
          logsPre.scrollTop = logsPre.scrollHeight;
        } else if (msg.type === 'result_partial') {
          // update results partial
          const dateStr = msg.date;
          const courtNo = msg.court;
          const value = msg.value;
          if (!results[dateStr]) results[dateStr] = {};
          results[dateStr][courtNo] = value;
          renderResults(results);
        } else if (msg.type === 'done') {
          // final results
          if (msg.results) {
            renderResults(msg.results);
          }
          es.close();
          stopTimer();
          loader.classList.add('hidden');
          checkBtn.disabled = false;
        } else if (msg.type === 'error') {
          logsPre.textContent += (logsPre.textContent ? '\n' : '') + `ERROR: ${msg.msg}`;
        }
      };

      es.onerror = (err) => {
        // Show connection error but keep trying until done
        console.warn('EventSource error', err);
      };

    } catch (err) {
      logsPre.textContent = `Error: ${err.message}`;
      stopTimer();
      loader.classList.add('hidden');
      checkBtn.disabled = false;
    }
  });

  // Set default to today
  const today = new Date().toISOString().slice(0, 10);
  startInput.value = today;
  endInput.value = today;

  // Expose renderResults on the window to ensure it's available to event handlers
  window.renderResults = function renderResults(results) {
    resultsDiv.innerHTML = '';
    for (const [date, courts] of Object.entries(results)) {
      const dateSection = document.createElement('div');
      dateSection.className = 'date-section';
      const h = document.createElement('h3');
      h.textContent = date;
      dateSection.appendChild(h);

      const table = document.createElement('div');
      table.className = 'court-grid';

      for (let i = 1; i <= 7; i++) {
        const courtNo = String(i);
        const cell = document.createElement('div');
        cell.className = 'court-cell';
        const title = document.createElement('div');
        title.className = 'court-title';
        title.textContent = `Court ${courtNo}`;
        cell.appendChild(title);

        const body = document.createElement('div');
        body.className = 'court-body';
        const value = (courts && courts[courtNo]) !== undefined ? courts[courtNo] : null;
        if (value === 'ERROR') {
          body.textContent = 'ERROR while checking';
        } else if (Array.isArray(value) && value.length === 0) {
          body.textContent = 'No available slots';
        } else if (Array.isArray(value)) {
          for (const slot of value) {
            const line = document.createElement('div');
            line.className = 'slot-line';
            const span = document.createElement('span');
            span.textContent = slot;
            const btn = document.createElement('button');
            btn.className = 'btn-small';
            btn.textContent = 'Book';
            btn.addEventListener('click', () => {
              console.log('Book clicked:', { date, court: courtNo, slot });
            });
            line.appendChild(span);
            line.appendChild(btn);
            body.appendChild(line);
          }
        } else if (value === null) {
          body.textContent = 'Pending...';
        } else {
          body.textContent = JSON.stringify(value);
        }

        cell.appendChild(body);
        table.appendChild(cell);
      }

      dateSection.appendChild(table);
      resultsDiv.appendChild(dateSection);
    }
  }
});
