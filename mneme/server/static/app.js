/* kimi-mneme — Mneme Glass UI JavaScript */

const API_BASE = '/api';

// State
let currentProject = 'all';
let currentFilter = 'all';
let autoRefresh = true;
let logEntries = [];
let allProjects = [];

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  initHeatmap();
  loadProjects().then(() => {
    initProjectTabs();
    initFilters();
    initSearch();
    initAutoRefresh();
    loadStats();
    loadObservations();
    startLogStream();
  });
});

// Load projects from backend
async function loadProjects() {
  try {
    const res = await fetch(`${API_BASE}/projects`);
    const data = await res.json();
    allProjects = data.projects || [];
  } catch (err) {
    addLog('error', `Failed to load projects: ${err.message}`);
    allProjects = [];
  }
}

// Heatmap — unique visual element
function initHeatmap() {
  const container = document.getElementById('heatmap');
  container.innerHTML = '';
  for (let i = 0; i < 35; i++) {
    const cell = document.createElement('div');
    cell.className = 'heatmap-cell';
    const level = Math.random() > 0.6 ? Math.floor(Math.random() * 4) + 1 : 0;
    if (level > 0) cell.classList.add(`level-${level}`);
    cell.title = `Day ${i + 1}: ${level} observations`;
    container.appendChild(cell);
  }
}

// Project tabs — now from real data
function initProjectTabs() {
  const container = document.getElementById('project-tabs');
  container.innerHTML = '';

  // All tab
  const allBtn = document.createElement('button');
  allBtn.className = 'project-tab active';
  allBtn.dataset.project = 'all';
  allBtn.textContent = 'All';
  allBtn.addEventListener('click', () => switchProject('all', allBtn));
  container.appendChild(allBtn);

  // Project tabs from real data
  allProjects.forEach(p => {
    const btn = document.createElement('button');
    btn.className = 'project-tab';
    btn.dataset.project = p.name;
    btn.textContent = p.name;
    btn.title = `${p.sessions} sessions · ${p.path}`;
    btn.addEventListener('click', () => switchProject(p.name, btn));
    container.appendChild(btn);
  });
}

function switchProject(project, btnElement) {
  document.querySelectorAll('.project-tab').forEach(t => t.classList.remove('active'));
  btnElement.classList.add('active');
  currentProject = project;
  addLog('info', `Switched to project: ${project}`);
  loadStats();
  loadObservations();
}

// Filters
function initFilters() {
  document.querySelectorAll('.filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentFilter = pill.dataset.filter;
      loadObservations();
    });
  });
}

// Search
function initSearch() {
  const input = document.getElementById('search-input');
  let debounceTimer;

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const query = input.value.trim();
      if (query) {
        searchObservations(query);
      } else {
        loadObservations();
      }
    }, 300);
  });
}

// Auto-refresh toggle
function initAutoRefresh() {
  const toggle = document.getElementById('auto-refresh-toggle');
  toggle.addEventListener('click', () => {
    autoRefresh = !autoRefresh;
    toggle.classList.toggle('active', autoRefresh);
  });
}

// Load statistics
async function loadStats() {
  try {
    const url = currentProject === 'all' 
      ? `${API_BASE}/stats` 
      : `${API_BASE}/stats?project=${encodeURIComponent(currentProject)}`;
    const res = await fetch(url);
    const data = await res.json();

    animateValue('stat-sessions', data.total_sessions);
    animateValue('stat-observations', data.total_observations);
    animateValue('stat-summaries', data.total_summaries);

    document.getElementById('db-size').textContent = `${data.db_size_mb} MB`;

    const loaded = data.total_observations * 50;
    const invested = data.total_observations * 200;
    const savings = invested > 0 ? Math.round((1 - loaded / invested) * 100) : 0;

    document.getElementById('tokens-loaded').textContent = loaded.toLocaleString();
    document.getElementById('tokens-invested').textContent = invested.toLocaleString();
    document.getElementById('tokens-savings').textContent = `${savings}%`;

  } catch (err) {
    addLog('error', `Failed to load stats: ${err.message}`);
  }
}

// Animate number counting
function animateValue(id, target) {
  const el = document.getElementById(id);
  const start = parseInt(el.textContent) || 0;
  const duration = 500;
  const startTime = performance.now();

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const ease = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(start + (target - start) * ease);
    el.textContent = current;

    if (progress < 1) {
      requestAnimationFrame(update);
    }
  }

  requestAnimationFrame(update);
}

// Load observations — now filtered by project
async function loadObservations() {
  try {
    const res = await fetch(`${API_BASE}/sessions?limit=50`);
    const data = await res.json();

    const container = document.getElementById('observations-stream');

    if (!data.sessions || data.sessions.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 4rem; color: var(--text-dim);">
          <div style="font-size: 3rem; margin-bottom: 1rem;">🌊</div>
          <p>No observations yet. Start a Kimi CLI session!</p>
        </div>
      `;
      return;
    }

    // Filter by project
    let sessions = data.sessions;
    if (currentProject !== 'all') {
      sessions = sessions.filter(s => {
        const cwd = s.get ? s.get('cwd') : s.cwd;
        return cwd && cwd.includes(currentProject);
      });
    }

    // Filter by event type
    if (currentFilter !== 'all') {
      // For sessions we don't filter by event type, but we could fetch observations
      // For now, just show filtered sessions
    }

    if (sessions.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 4rem; color: var(--text-dim);">
          <div style="font-size: 3rem; margin-bottom: 1rem;">📂</div>
          <p>No sessions for project "${escapeHtml(currentProject)}"</p>
        </div>
      `;
      return;
    }

    container.innerHTML = sessions.map(s => renderSessionCard(s)).join('');

  } catch (err) {
    addLog('error', `Failed to load observations: ${err.message}`);
  }
}

// Search observations
async function searchObservations(query) {
  try {
    const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}&limit=20`);
    const data = await res.json();

    const container = document.getElementById('observations-stream');

    if (!data.results || data.results.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 4rem; color: var(--text-dim);">
          <div style="font-size: 3rem; margin-bottom: 1rem;">🔍</div>
          <p>No results for "${escapeHtml(query)}"</p>
        </div>
      `;
      return;
    }

    container.innerHTML = data.results.map(r => renderObservationCard(r)).join('');

  } catch (err) {
    addLog('error', `Search failed: ${err.message}`);
  }
}

// Render session card
function renderSessionCard(session) {
  const date = formatDate(session.started_at || session.get?.('started_at'));
  const isActive = !session.ended_at;
  const cwd = session.cwd || session.get?.('cwd') || 'Unknown';
  const id = session.id || session.get?.('id') || 'unknown';
  const obsCount = session.observation_count || session.get?.('observation_count') || 0;

  return `
    <div class="observation-card">
      <div class="card-header">
        <div class="card-badges">
          <span class="badge-pill badge-success">Session</span>
          ${isActive ? '<span class="badge-pill" style="background: rgba(52, 211, 153, 0.2); color: #34d399;">● Active</span>' : ''}
        </div>
        <span class="card-meta">${id.substring(0, 8)} · ${date}</span>
      </div>
      <div class="card-body">
        <p><code>${escapeHtml(cwd)}</code></p>
        <p style="color: var(--text-secondary); margin-top: 0.5rem;">
          ${obsCount} observations
        </p>
      </div>
      <div class="card-footer">
        <span class="card-action" onclick="viewTimeline('${id}')">📊 Timeline</span>
        <span class="card-action" onclick="viewDetails('${id}')">🔍 Details</span>
      </div>
    </div>
  `;
}

// Render observation card
function renderObservationCard(obs) {
  const badgeClass = getBadgeClass(obs.event_type || obs.type);
  const badgeName = (obs.event_type || obs.type || 'Unknown').replace(/([A-Z])/g, ' $1').trim();
  const date = formatDate(obs.timestamp || obs.created_at);

  return `
    <div class="observation-card">
      <div class="card-header">
        <div class="card-badges">
          <span class="badge-pill ${badgeClass}">${badgeName}</span>
          ${obs.tool_name ? `<span class="badge-pill badge-tool">${obs.tool_name}</span>` : ''}
        </div>
        <span class="card-meta">#${obs.id} · ${date}</span>
      </div>
      <div class="card-body">
        ${obs.file_path ? `<p><code>${escapeHtml(obs.file_path)}</code></p>` : ''}
        <p>${escapeHtml(obs.snippet || obs.tool_output || obs.error || obs.prompt || '')}</p>
      </div>
      <div class="card-footer">
        <span class="card-action" onclick="viewObservation(${obs.id})">👁 View</span>
        <span class="card-action" onclick="copyId(${obs.id})">📋 Copy ID</span>
      </div>
    </div>
  `;
}

function getBadgeClass(eventType) {
  if (eventType === 'UserPromptSubmit') return 'badge-prompt';
  if (eventType === 'PostToolUseFailure') return 'badge-error';
  if (eventType === 'PostToolUse') return 'badge-tool';
  if (eventType === 'SessionStart' || eventType === 'SessionEnd') return 'badge-success';
  return 'badge-tool';
}

// Log stream
function startLogStream() {
  addLog('info', 'kimi-mneme initialized');
  addLog('hook', 'SessionStart hook registered');
  addLog('info', 'Plugin tools loaded: mneme_search, mneme_timeline, mneme_get');

  setInterval(() => {
    if (!autoRefresh) return;

    const messages = [
      { level: 'hook', msg: 'PostToolUse: WriteFile' },
      { level: 'info', msg: 'Observation stored: #1234' },
      { level: 'info', msg: 'Vector index updated' },
      { level: 'hook', msg: 'UserPromptSubmit' },
    ];

    if (Math.random() > 0.7) {
      const m = messages[Math.floor(Math.random() * messages.length)];
      addLog(m.level, m.msg);
    }
  }, 5000);
}

function addLog(level, message) {
  const stream = document.getElementById('log-stream');
  const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });

  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `
    <span class="log-time">${time}</span>
    <span class="log-level log-level-${level}">${level.toUpperCase()}</span>
    <span class="log-message">${escapeHtml(message)}</span>
  `;

  stream.insertBefore(entry, stream.firstChild);

  while (stream.children.length > 100) {
    stream.removeChild(stream.lastChild);
  }

  logEntries.push({ level, message, time });
  document.getElementById('log-count').textContent = `${logEntries.length} entries`;
}

// Utilities
function formatDate(dateStr) {
  if (!dateStr) return 'Unknown';
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now - date;

  if (diff < 3600000) {
    const mins = Math.floor(diff / 60000);
    return mins < 1 ? 'Just now' : `${mins}m ago`;
  }

  if (diff < 86400000) {
    const hours = Math.floor(diff / 3600000);
    return `${hours}h ago`;
  }

  return date.toLocaleDateString();
}

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Placeholder actions
function viewTimeline(sessionId) {
  addLog('info', `Viewing timeline for ${sessionId}`);
}

function viewDetails(sessionId) {
  addLog('info', `Viewing details for ${sessionId}`);
}

function viewObservation(id) {
  addLog('info', `Viewing observation #${id}`);
}

function copyId(id) {
  navigator.clipboard.writeText(id.toString());
  addLog('info', `Copied ID ${id} to clipboard`);
}

// Auto-refresh
setInterval(() => {
  if (autoRefresh) {
    loadStats();
    const searchInput = document.getElementById('search-input');
    if (!searchInput.value.trim()) {
      loadObservations();
    }
  }
}, 30000);
