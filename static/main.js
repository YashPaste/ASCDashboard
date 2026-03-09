document.addEventListener('DOMContentLoaded', function () {
  // =============================================
  // DOM refs
  // =============================================
  const dateTabs = document.getElementById('date-tabs');
  const cachedGrid = document.getElementById('cached-grid');
  const skeleton = document.getElementById('skeleton');
  const statusDot = document.getElementById('status-dot');
  const statusLabel = document.getElementById('status-label');
  const statusTime = document.getElementById('status-time');
  const toggleBtn = document.getElementById('toggle-manual');
  const manualSection = document.getElementById('manual-section');
  const startInput = document.getElementById('start');
  const endInput = document.getElementById('end');
  const checkBtn = document.getElementById('check');
  const loader = document.getElementById('loader');
  const elapsedSpan = document.getElementById('elapsed');
  const logsPre = document.getElementById('logs');
  const resultsDiv = document.getElementById('results');

  // =============================================
  // State
  // =============================================
  let cachedData = {};      // { "2026-03-10": { "1": [...], ... }, ... }
  let cacheMeta = {};
  let activeDate = null;
  let timerId = null;
  let elapsed = 0;
  let pollInterval = null;

  // =============================================
  // Toggle manual section
  // =============================================
  toggleBtn.addEventListener('click', () => {
    const isCollapsed = manualSection.classList.contains('collapsed');
    if (isCollapsed) {
      manualSection.classList.remove('collapsed');
      manualSection.classList.add('expanded');
      toggleBtn.classList.add('open');
    } else {
      manualSection.classList.remove('expanded');
      manualSection.classList.add('collapsed');
      toggleBtn.classList.remove('open');
    }
  });

  // =============================================
  // Cached data: fetch + render
  // =============================================
  async function fetchCachedSlots() {
    try {
      const resp = await fetch('/api/cached_slots');
      if (!resp.ok) return;
      const data = await resp.json();
      cachedData = data.slots || {};
      cacheMeta = data.meta || {};
      updateStatus();
      renderDateTabs();
      if (activeDate && cachedData[activeDate]) {
        renderCachedGrid(activeDate);
      } else {
        // auto-select first date
        const dates = Object.keys(cachedData).sort();
        if (dates.length > 0) {
          activeDate = dates[0];
          renderCachedGrid(activeDate);
        }
      }
      // Hide skeleton once we have data
      if (Object.keys(cachedData).length > 0) {
        skeleton.classList.add('hidden');
        cachedGrid.classList.remove('hidden');
      }
    } catch (e) {
      console.warn('Failed to fetch cached slots:', e);
    }
  }

  function updateStatus() {
    const meta = cacheMeta;
    if (meta.is_refreshing) {
      statusDot.className = 'status-dot refreshing';
      const progress = meta.courts_total > 0
        ? `${meta.courts_checked}/${meta.courts_total} courts`
        : '';
      statusLabel.textContent = `Refreshing... ${progress}`;
      statusTime.textContent = '';
    } else if (meta.last_updated) {
      statusDot.className = 'status-dot live';
      statusLabel.textContent = 'Data available';
      statusTime.textContent = `Updated ${timeAgo(meta.last_updated)}`;
    } else {
      statusDot.className = 'status-dot stale';
      statusLabel.textContent = 'Waiting for first refresh...';
      statusTime.textContent = 'Auto-refresh runs every hour';
    }
  }

  function timeAgo(isoStr) {
    const then = new Date(isoStr);
    const now = new Date();
    const diffMs = now - then;
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m ago`;
  }

  function renderDateTabs() {
    const dates = Object.keys(cachedData).sort();
    dateTabs.innerHTML = '';

    dates.forEach((dateStr) => {
      const btn = document.createElement('button');
      btn.className = 'date-tab' + (dateStr === activeDate ? ' active' : '');

      const d = new Date(dateStr + 'T00:00:00');
      const dayName = d.toLocaleDateString('en-IN', { weekday: 'short' });
      const dayNum = d.getDate();
      const month = d.toLocaleDateString('en-IN', { month: 'short' });

      // Count total available slots for this date
      const courts = cachedData[dateStr] || {};
      let totalSlots = 0;
      Object.values(courts).forEach(v => {
        if (Array.isArray(v)) totalSlots += v.length;
      });

      // Check if it's today
      const today = new Date();
      const isToday = d.toDateString() === today.toDateString();
      const isTomorrow = d.toDateString() === new Date(today.getTime() + 86400000).toDateString();

      let label = `${dayName}`;
      if (isToday) label = 'Today';
      else if (isTomorrow) label = 'Tomorrow';

      btn.innerHTML = `
        <span>
          <span class="tab-label">${label}</span><br>
          <span class="tab-day">${dayNum} ${month}</span>
        </span>
        <span class="tab-count">${totalSlots}</span>
      `;

      btn.addEventListener('click', () => {
        activeDate = dateStr;
        document.querySelectorAll('.date-tab').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
        renderCachedGrid(dateStr);
      });

      dateTabs.appendChild(btn);
    });
  }

  function renderCachedGrid(dateStr) {
    const courts = cachedData[dateStr] || {};
    cachedGrid.innerHTML = '';

    for (let i = 1; i <= 7; i++) {
      const courtNo = String(i);
      const value = courts[courtNo];

      const card = document.createElement('div');
      card.className = 'court-card';

      // Header
      const header = document.createElement('div');
      header.className = 'court-card-header';

      const name = document.createElement('span');
      name.className = 'court-name';
      name.textContent = `Court ${i}`;

      const badge = document.createElement('span');
      badge.className = 'court-badge';

      if (value === undefined || value === null) {
        badge.classList.add('pending');
        badge.textContent = 'Pending';
      } else if (value === 'ERROR') {
        badge.classList.add('error');
        badge.textContent = 'Error';
      } else if (Array.isArray(value) && value.length === 0) {
        badge.classList.add('none');
        badge.textContent = 'No slots';
      } else if (Array.isArray(value)) {
        badge.classList.add('available');
        badge.textContent = `${value.length} slot${value.length > 1 ? 's' : ''}`;
      }

      header.appendChild(name);
      header.appendChild(badge);
      card.appendChild(header);

      // Body
      const body = document.createElement('div');

      if (value === undefined || value === null) {
        body.className = 'court-card-body empty-body';
        body.textContent = 'Waiting for data...';
      } else if (value === 'ERROR') {
        body.className = 'court-card-body empty-body';
        body.textContent = 'Failed to check this court';
      } else if (Array.isArray(value) && value.length === 0) {
        body.className = 'court-card-body empty-body';
        body.textContent = 'No available slots';
      } else if (Array.isArray(value)) {
        body.className = 'court-card-body';
        value.forEach(slot => {
          const row = document.createElement('div');
          row.className = 'slot-row';

          // Parse slot text like "05:00 am\n06:00 am\n₹750"
          const parts = slot.split('\n').map(s => s.trim()).filter(Boolean);
          const timeText = parts.filter(p => /am|pm/i.test(p)).join(' – ');
          const priceText = parts.find(p => /₹/.test(p)) || '';

          const time = document.createElement('span');
          time.className = 'slot-time';
          time.textContent = timeText || slot;

          const price = document.createElement('span');
          price.className = 'slot-price';
          price.textContent = priceText;

          const btn = document.createElement('button');
          btn.className = 'btn-book';
          btn.textContent = 'Book';
          btn.addEventListener('click', () => {
            window.open(
              'https://reczone.mcgm.gov.in/sports-complex/book-your-sport',
              '_blank'
            );
          });

          row.appendChild(time);
          if (priceText) row.appendChild(price);
          row.appendChild(btn);
          body.appendChild(row);
        });
      }

      card.appendChild(body);
      cachedGrid.appendChild(card);
    }
  }

  // =============================================
  // Poll for cache updates (every 30s)
  // =============================================
  function startPolling() {
    fetchCachedSlots();
    pollInterval = setInterval(fetchCachedSlots, 30000);
  }

  // =============================================
  // Manual Search (existing SSE flow)
  // =============================================
  function startTimer() {
    elapsed = 0;
    elapsedSpan.textContent = '0s';
    timerId = setInterval(() => {
      elapsed += 1;
      elapsedSpan.textContent = `${elapsed}s`;
    }, 1000);
  }

  function stopTimer() {
    if (timerId) { clearInterval(timerId); timerId = null; }
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
    if (v) { alert(v); return; }

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

      const es = new EventSource(`/events/${jobId}`);
      const results = {};

      es.onmessage = (e) => {
        if (!e.data) return;
        let msg = null;
        try { msg = JSON.parse(e.data); } catch { return; }

        if (msg.type === 'log') {
          logsPre.textContent += (logsPre.textContent ? '\n' : '') + msg.msg;
          logsPre.scrollTop = logsPre.scrollHeight;
        } else if (msg.type === 'result_partial') {
          if (!results[msg.date]) results[msg.date] = {};
          results[msg.date][msg.court] = msg.value;
          renderManualResults(results);
        } else if (msg.type === 'done') {
          if (msg.results) renderManualResults(msg.results);
          es.close();
          stopTimer();
          loader.classList.add('hidden');
          checkBtn.disabled = false;
        } else if (msg.type === 'error') {
          logsPre.textContent += (logsPre.textContent ? '\n' : '') + `ERROR: ${msg.msg}`;
        }
      };

      es.onerror = () => console.warn('EventSource error');
    } catch (err) {
      logsPre.textContent = `Error: ${err.message}`;
      stopTimer();
      loader.classList.add('hidden');
      checkBtn.disabled = false;
    }
  });

  function renderManualResults(results) {
    resultsDiv.innerHTML = '';
    for (const [date, courts] of Object.entries(results)) {
      const dateSection = document.createElement('div');
      dateSection.className = 'date-section';
      const h = document.createElement('h3');
      h.textContent = date;
      dateSection.appendChild(h);

      const grid = document.createElement('div');
      grid.className = 'court-grid';

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
        const value = courts[courtNo] !== undefined ? courts[courtNo] : null;

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
              window.open('https://reczone.mcgm.gov.in/sports-complex/book-your-sport', '_blank');
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
        grid.appendChild(cell);
      }

      dateSection.appendChild(grid);
      resultsDiv.appendChild(dateSection);
    }
  }

  // =============================================
  // Init
  // =============================================
  const today = new Date().toISOString().slice(0, 10);
  startInput.value = today;
  endInput.value = today;

  // Start polling for cached data
  startPolling();
});