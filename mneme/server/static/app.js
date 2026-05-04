/* kimi-mneme — Mneme Glass UI JavaScript */

const API_BASE = '/api';

// State
let currentProject = 'all';
let currentFilter = 'all';
let autoRefresh = true;
let logEntries = [];
let wsConnection = null;
let wsReconnectTimer = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  // Remove any stale modals from cached old versions
  document.querySelectorAll('div').forEach(div => {
    const h3 = div.querySelector('h3');
    if (h3 && h3.textContent.includes('Session Timeline')) div.remove();
  });
  initHeatmap();
  initProjectTabs();
  initFilters();
  initSearch();
  initAutoRefresh();
  initWelcomeModal();
  loadStats();
  loadObservations();
  startLogStream();
  connectWebSocket();
  connectSSE();
  startQueuePoller();
});

// Welcome modal
function initWelcomeModal() {
  const modal = document.getElementById('welcome-modal');
  const startBtn = document.getElementById('welcome-start');
  const dontShow = document.getElementById('welcome-dont-show');

  if (!modal || !startBtn) return;

  // Show if not previously dismissed
  const dismissed = localStorage.getItem('mneme_welcome_shown');
  if (!dismissed) {
    modal.style.display = 'flex';
  }

  startBtn.addEventListener('click', () => {
    if (dontShow && dontShow.checked) {
      localStorage.setItem('mneme_welcome_shown', 'true');
    }
    modal.style.display = 'none';
  });

  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      modal.style.display = 'none';
    }
  });
}

// WebSocket for real-time wire updates
function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${proto}//${location.host}/ws`;

  try {
    wsConnection = new WebSocket(wsUrl);

    wsConnection.onopen = () => {
      addLog('info', 'WebSocket connected — real-time updates active');
      // Subscribe to all wire events
      wsConnection.send(JSON.stringify({action: 'subscribe', channel: 'all'}));
    };

    wsConnection.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'wire_update') {
          handleWireUpdate(msg.session_id, msg.counts);
        }
      } catch (e) {
        console.error('WS message parse error:', e);
      }
    };

    wsConnection.onclose = () => {
      addLog('info', 'WebSocket disconnected — reconnecting in 3s...');
      scheduleReconnect();
    };

    wsConnection.onerror = (err) => {
      console.error('WebSocket error:', err);
    };
  } catch (e) {
    console.error('Failed to create WebSocket:', e);
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (wsReconnectTimer) return;
  wsReconnectTimer = setTimeout(() => {
    wsReconnectTimer = null;
    connectWebSocket();
  }, 3000);
}

// SSE for structured observation updates + queue status
let sseConnection = null;

function connectSSE() {
  try {
    const evtSource = new EventSource('/api/stream');
    sseConnection = evtSource;

    evtSource.addEventListener('connected', (e) => {
      addLog('info', 'SSE connected — structured updates active');
    });

    evtSource.addEventListener('structured_update', (e) => {
      const data = JSON.parse(e.data);
      addLog('info', `Structured observation #${data.id} added (${data.type})`);
      // If structured filter is active, refresh
      if (currentFilter === 'structured') {
        loadStructuredObservations();
      }
      // Update stats
      loadStats();
    });

    evtSource.addEventListener('queue_status', (e) => {
      const data = JSON.parse(e.data);
      updateQueueIndicator(data);
    });

    evtSource.onerror = () => {
      console.error('SSE error, reconnecting...');
      evtSource.close();
      setTimeout(connectSSE, 5000);
    };
  } catch (e) {
    console.error('SSE not supported:', e);
  }
}

function updateQueueIndicator(data) {
  const indicator = document.getElementById('processing-indicator');
  const countEl = document.getElementById('queue-count');
  const statusDot = document.getElementById('status-dot');
  const queueStatus = document.getElementById('queue-status');

  const pending = data.pending || 0;
  const processing = data.processing || 0;

  if (countEl) countEl.textContent = pending + processing;
  if (queueStatus) queueStatus.textContent = `${pending} pending, ${processing} processing`;

  if (indicator) {
    indicator.style.display = (pending > 0 || processing > 0) ? 'flex' : 'none';
  }

  if (statusDot) {
    if (processing > 0) {
      statusDot.style.background = '#fbbf24'; // yellow
      statusDot.title = 'Processing';
    } else if (pending > 0) {
      statusDot.style.background = '#fbbf24'; // yellow
      statusDot.title = 'Pending';
    } else {
      statusDot.style.background = '#34d399'; // green
      statusDot.title = 'Idle';
    }
  }
}

// Poll queue status every 5s as SSE fallback
function startQueuePoller() {
  async function poll() {
    try {
      const res = await fetch('/api/queue_status');
      const data = await res.json();
      updateQueueIndicator(data);
    } catch (e) {
      // Ignore
    }
  }
  poll();
  setInterval(poll, 5000);
}

function handleWireUpdate(sessionId, counts) {
  // Always refresh stats (lightweight)
  loadStats();

  // Only refresh the main view if auto-refresh is on and user is not in timeline/search
  if (!autoRefresh) return;

  const timelineView = document.getElementById('timeline-view');
  const searchInput = document.getElementById('search-input');
  if (timelineView && timelineView.style.display !== 'none') return;
  if (searchInput && searchInput.value.trim()) return;

  // Show a subtle "new data" indicator instead of full reload?
  // For now: smart reload based on current filter
  if (currentFilter === 'all' || currentFilter === 'SessionStart') {
    loadObservations();
  } else if (currentFilter === 'thinking') {
    loadThinking();
  } else if (currentFilter === 'assistant') {
    loadAssistantMessages();
  } else {
    loadFilteredObservations();
  }
}

// Heatmap — unique visual element
function initHeatmap() {
  const container = document.getElementById('heatmap');
  for (let i = 0; i < 35; i++) {
    const cell = document.createElement('div');
    cell.className = 'heatmap-cell';
    // Random activity level for demo
    const level = Math.random() > 0.6 ? Math.floor(Math.random() * 4) + 1 : 0;
    if (level > 0) cell.classList.add(`level-${level}`);
    cell.title = `Day ${i + 1}: ${level} observations`;
    container.appendChild(cell);
  }
}

// Project tabs
async function initProjectTabs() {
  const container = document.getElementById('project-tabs');
  container.innerHTML = '';

  // Add "All" tab
  const allBtn = document.createElement('button');
  allBtn.className = 'project-tab active';
  allBtn.dataset.project = 'all';
  allBtn.textContent = 'All';
  allBtn.addEventListener('click', () => {
    document.querySelectorAll('.project-tab').forEach(t => t.classList.remove('active'));
    allBtn.classList.add('active');
    currentProject = 'all';
    loadObservations();
  });
  container.appendChild(allBtn);

  // Load projects from API
  try {
    const res = await fetch(`${API_BASE}/projects`);
    const data = await res.json();
    const projects = data.projects || [];

    projects.forEach(p => {
      const btn = document.createElement('button');
      btn.className = 'project-tab';
      btn.dataset.project = p.name || p;
      btn.textContent = p.name || p;
      btn.addEventListener('click', () => {
        document.querySelectorAll('.project-tab').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
        currentProject = p.name || p;
        loadObservations();
      });
      container.appendChild(btn);
    });
  } catch (err) {
    console.error('Failed to load projects:', err);
  }
}

// Filters
function initFilters() {
  document.querySelectorAll('.filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentFilter = pill.dataset.filter;
      showSessionList();
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
    const res = await fetch(`${API_BASE}/stats`);
    const data = await res.json();

    animateValue('stat-sessions', data.total_sessions);
    animateValue('stat-observations', data.total_observations);
    animateValue('stat-summaries', data.total_summaries);

    document.getElementById('db-size').textContent = `${data.db_size_mb} MB`;

    // Show structured filter pill if we have structured observations
    try {
      const structRes = await fetch(`${API_BASE}/structured_stats`);
      const structData = await structRes.json();
      if (structData.total > 0) {
        document.getElementById('filter-structured').style.display = '';
      }
    } catch (e) {
      // Ignore
    }

    // Token economics (B.4 — real data from compaction events)
    const econ = data.token_economics || {};
    const loaded = econ.tokens_loaded || 0;
    const invested = econ.tokens_invested || 0;
    const savings = econ.savings_percent || 0;
    const compactionCount = econ.compaction_count || 0;

    document.getElementById('tokens-loaded').textContent = loaded.toLocaleString();
    document.getElementById('tokens-invested').textContent = invested.toLocaleString();
    const savingsEl = document.getElementById('tokens-savings');
    savingsEl.textContent = `${savings}%`;
    savingsEl.className = 'economics-value economics-savings';
    if (savings >= 50) savingsEl.classList.add('high');
    else if (savings >= 20) savingsEl.classList.add('mid');
    else savingsEl.classList.add('low');

    // Update rightbar economics with real data
    const compressionStatus = document.getElementById('compression-status');
    if (compressionStatus) {
      compressionStatus.textContent = compactionCount > 0 ? `${compactionCount} events` : 'No data';
    }

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
    const ease = 1 - Math.pow(1 - progress, 3); // ease-out cubic
    const current = Math.round(start + (target - start) * ease);
    el.textContent = current;

    if (progress < 1) {
      requestAnimationFrame(update);
    }
  }

  requestAnimationFrame(update);
}

// Skeleton loader HTML
function getSkeletonLoader(count = 3) {
  const cards = Array.from({ length: count }, () => `
    <div class="skeleton-card">
      <div class="skeleton-header">
        <div class="skeleton-badge"></div>
        <div class="skeleton-meta"></div>
      </div>
      <div class="skeleton-title"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
      <div class="skeleton-footer">
        <div class="skeleton-action"></div>
        <div class="skeleton-action"></div>
      </div>
    </div>
  `).join('');
  return `<div class="skeleton-container">${cards}</div>`;
}

// Load observations
async function loadObservations() {
  try {
    // Show skeleton loader
    const container = document.getElementById('observations-stream');
    container.innerHTML = getSkeletonLoader(3);

    // Ensure we are in list view, not timeline
    container.style.display = 'block';
    document.getElementById('timeline-view').style.display = 'none';

    // If a type filter is active (not 'all' or 'SessionStart'), load observations directly
    if (currentFilter && currentFilter !== 'all' && currentFilter !== 'SessionStart') {
      if (currentFilter === 'thinking') {
        await loadThinking();
        return;
      }
      if (currentFilter === 'assistant') {
        await loadAssistantMessages();
        return;
      }
      if (currentFilter === 'structured') {
        await loadStructuredObservations();
        return;
      }
      await loadFilteredObservations();
      return;
    }

    // Build query params for sessions
    const params = new URLSearchParams();
    params.append('limit', '20');
    if (currentProject && currentProject !== 'all') {
      params.append('project', currentProject);
    }

    const res = await fetch(`${API_BASE}/sessions?${params.toString()}`);
    const data = await res.json();

    if (!data.sessions || data.sessions.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 4rem; color: var(--text-dim);">
          <div style="font-size: 3rem; margin-bottom: 1rem;">🌊</div>
          <p>No observations yet. Start a Kimi CLI session!</p>
        </div>
      `;
      return;
    }

    container.innerHTML = data.sessions.map(s => renderSessionCard(s)).join('');

  } catch (err) {
    addLog('error', `Failed to load observations: ${err.message}`);
  }
}

// Load observations filtered by event type
async function loadFilteredObservations() {
  try {
    // Ensure list view is visible
    document.getElementById('observations-stream').style.display = 'block';
    document.getElementById('timeline-view').style.display = 'none';

    const params = new URLSearchParams();
    params.append('limit', '50');
    params.append('event_type', currentFilter);
    if (currentProject && currentProject !== 'all') {
      params.append('project', currentProject);
    }

    const res = await fetch(`${API_BASE}/observations?${params.toString()}`);
    const data = await res.json();

    const container = document.getElementById('observations-stream');

    if (!data.observations || data.observations.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 4rem; color: var(--text-dim);">
          <div style="font-size: 3rem; margin-bottom: 1rem;">🌊</div>
          <p>No ${formatFilterName(currentFilter)} observations found.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = data.observations.map(o => renderObservationCard(o)).join('');

  } catch (err) {
    addLog('error', `Failed to load filtered observations: ${err.message}`);
  }
}

function formatFilterName(filter) {
  const names = {
    'UserPromptSubmit': 'prompt',
    'PostToolUse': 'tool',
    'PostToolUseFailure': 'error',
    'SessionStart': 'session',
    'thinking': 'thinking',
    'assistant': 'assistant',
    'structured': 'structured'
  };
  return names[filter] || filter;
}

// Load structured observations
async function loadStructuredObservations() {
  try {
    const container = document.getElementById('observations-stream');
    container.innerHTML = getSkeletonLoader(3);
    container.style.display = 'block';
    document.getElementById('timeline-view').style.display = 'none';

    const params = new URLSearchParams();
    params.append('limit', '50');
    if (currentProject && currentProject !== 'all') {
      params.append('project', currentProject);
    }

    const res = await fetch(`${API_BASE}/structured_observations?${params.toString()}`);
    const data = await res.json();

    if (!data.observations || data.observations.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 4rem; color: var(--text-dim);">
          <div style="font-size: 3rem; margin-bottom: 1rem;">📚</div>
          <p>No structured observations yet. They appear after background AI processing.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = data.observations.map(o => renderStructuredCard(o)).join('');

  } catch (err) {
    addLog('error', `Failed to load structured observations: ${err.message}`);
  }
}

// Load thinking blocks
async function loadThinking() {
  try {
    document.getElementById('observations-stream').style.display = 'block';
    document.getElementById('timeline-view').style.display = 'none';

    // We need a session to show thinking — for now show latest session's thinking
    const sessionsRes = await fetch(`${API_BASE}/sessions?limit=1`);
    const sessionsData = await sessionsRes.json();
    if (!sessionsData.sessions || sessionsData.sessions.length === 0) {
      document.getElementById('observations-stream').innerHTML = `<div style="text-align:center;padding:4rem;color:var(--text-dim)"><div style="font-size:3rem;margin-bottom:1rem">🧠</div><p>No thinking data yet.</p></div>`;
      return;
    }
    const sessionId = sessionsData.sessions[0].id;
    const res = await fetch(`${API_BASE}/thinking?session_id=${sessionId}&limit=50`);
    const data = await res.json();

    const container = document.getElementById('observations-stream');
    if (!data.thinking || data.thinking.length === 0) {
      container.innerHTML = `<div style="text-align:center;padding:4rem;color:var(--text-dim)"><div style="font-size:3rem;margin-bottom:1rem">🧠</div><p>No thinking blocks found.</p></div>`;
      return;
    }

    container.innerHTML = data.thinking.map(t => `
      <div class="observation-card" style="border-left: 3px solid #a78bfa;">
        <div class="card-header">
          <div class="card-badges">
            <span class="badge-pill" style="background: rgba(167,139,250,0.2); color: #a78bfa;">THINKING</span>
          </div>
          <span class="card-meta">${formatDate(t.timestamp)}</span>
        </div>
        <div class="card-body">
          <p style="color: var(--text-secondary); font-style: italic;">${escapeHtml(t.content)}</p>
        </div>
      </div>
    `).join('');
  } catch (err) {
    addLog('error', `Failed to load thinking: ${err.message}`);
  }
}

// Load assistant messages
async function loadAssistantMessages() {
  try {
    document.getElementById('observations-stream').style.display = 'block';
    document.getElementById('timeline-view').style.display = 'none';

    const sessionsRes = await fetch(`${API_BASE}/sessions?limit=1`);
    const sessionsData = await sessionsRes.json();
    if (!sessionsData.sessions || sessionsData.sessions.length === 0) {
      document.getElementById('observations-stream').innerHTML = `<div style="text-align:center;padding:4rem;color:var(--text-dim)"><div style="font-size:3rem;margin-bottom:1rem">🤖</div><p>No assistant messages yet.</p></div>`;
      return;
    }
    const sessionId = sessionsData.sessions[0].id;
    const res = await fetch(`${API_BASE}/assistant_messages?session_id=${sessionId}&limit=50`);
    const data = await res.json();

    const container = document.getElementById('observations-stream');
    if (!data.messages || data.messages.length === 0) {
      container.innerHTML = `<div style="text-align:center;padding:4rem;color:var(--text-dim)"><div style="font-size:3rem;margin-bottom:1rem">🤖</div><p>No assistant messages found.</p></div>`;
      return;
    }

    container.innerHTML = data.messages.map(m => `
      <div class="observation-card" style="border-left: 3px solid #38bdf8;">
        <div class="card-header">
          <div class="card-badges">
            <span class="badge-pill" style="background: rgba(56,189,248,0.2); color: #38bdf8;">ASSISTANT</span>
          </div>
          <span class="card-meta">${formatDate(m.timestamp)}</span>
        </div>
        <div class="card-body">
          <p>${escapeHtml(m.content)}</p>
        </div>
      </div>
    `).join('');
  } catch (err) {
    addLog('error', `Failed to load assistant messages: ${err.message}`);
  }
}

// Search observations
async function searchObservations(query) {
  try {
    // Try structured search first, fallback to regular search
    let results = [];
    try {
      const structuredRes = await fetch(`${API_BASE}/structured_search?q=${encodeURIComponent(query)}&limit=20`);
      const structuredData = await structuredRes.json();
      results = structuredData.results || [];
    } catch (e) {
      // Fallback to regular search
    }

    // If no structured results, try regular search
    if (results.length === 0) {
      const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}&limit=20`);
      const data = await res.json();
      results = data.results || [];
    }

    const container = document.getElementById('observations-stream');

    // Apply type filter to search results if active
    if (currentFilter && currentFilter !== 'all' && currentFilter !== 'SessionStart') {
      results = results.filter(r => (r.event_type || r.type) === currentFilter);
    }

    if (results.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 4rem; color: var(--text-dim);">
          <div style="font-size: 3rem; margin-bottom: 1rem;">🔍</div>
          <p>No results for "${escapeHtml(query)}"</p>
        </div>
      `;
      return;
    }

    // Render structured cards if results have 'type' field (structured), else regular
    const isStructured = results.length > 0 && results[0].hasOwnProperty('facts');
    container.innerHTML = results.map(r => isStructured ? renderStructuredCard(r) : renderObservationCard(r)).join('');

  } catch (err) {
    addLog('error', `Search failed: ${err.message}`);
  }
}

// Render session card
function renderSessionCard(session) {
  const date = formatDate(session.started_at);
  const isActive = !session.ended_at;

  return `
    <div class="observation-card">
      <div class="card-header">
        <div class="card-badges">
          <span class="badge-pill badge-success">Session</span>
          ${isActive ? '<span class="badge-pill" style="background: rgba(52, 211, 153, 0.2); color: #34d399;">● Active</span>' : ''}
        </div>
        <span class="card-meta">${session.id.substring(0, 8)} · ${date}</span>
      </div>
      <div class="card-body">
        <p><code>${escapeHtml(session.cwd)}</code></p>
        <p style="color: var(--text-secondary); margin-top: 0.5rem;">
          ${session.observation_count || 0} observations
        </p>
      </div>
      <div class="card-footer">
        <span class="card-action" onclick="viewTimeline('${session.id}')">📊 Timeline</span>
        <span class="card-action" onclick="viewDetails('${session.id}')">🔍 Details</span>
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

// Render structured observation card
function estimateTokens(text) {
  if (!text) return 0;
  return Math.ceil(text.length / 4);
}

function renderStructuredCard(obs, expanded = false) {
  const typeEmoji = {
    'bugfix': '🐛', 'feature': '✨', 'refactor': '♻️',
    'change': '📝', 'discovery': '🔍', 'decision': '🎯'
  }[obs.type] || '•';

  const sourceEmoji = {'ai': '🤖', 'heuristic': '⚡', 'manual': '✋'}[obs.source] || '•';
  const date = formatDate(obs.created_at);

  // Token economics estimate
  const contentText = [
    obs.title || '',
    obs.subtitle || '',
    obs.narrative || '',
    ...(obs.facts || []),
  ].join(' ');
  const tokenCount = estimateTokens(contentText);

  const factsHtml = (obs.facts || []).slice(0, 3).map(f =>
    `<li style="margin: 0.25rem 0; color: var(--text-secondary);">• ${escapeHtml(f)}</li>`
  ).join('');

  const filesHtml = (obs.files_modified || []).concat(obs.files_read || []).slice(0, 3).map(f =>
    `<code style="font-size: 0.75rem; margin-right: 0.5rem;">${escapeHtml(f)}</code>`
  ).join('');

  const compactClass = expanded ? '' : 'card-compact';
  const toggleIcon = expanded ? '▼' : '▶';

  return `
    <div class="observation-card ${compactClass}" data-obs-id="${obs.id}" style="border-left: 3px solid #f59e0b;">
      <div class="card-header">
        <div class="card-badges">
          <span class="badge-pill" style="background: rgba(245,158,11,0.2); color: #f59e0b;">${typeEmoji} ${obs.type}</span>
          <span class="badge-pill badge-tool">${sourceEmoji} ${obs.source}</span>
          <span class="token-badge" title="Estimated tokens to read this observation">~${tokenCount}t</span>
        </div>
        <div style="display: flex; align-items: center; gap: 0.5rem;">
          <span class="card-toggle" onclick="toggleCard(${obs.id})" title="${expanded ? 'Collapse' : 'Expand'}">${toggleIcon}</span>
          <span class="card-meta">#${obs.id} · ${date}</span>
        </div>
      </div>
      <div class="card-body">
        <p style="font-weight: 600; font-size: 1.05rem; margin-bottom: 0.5rem;">${escapeHtml(obs.title)}</p>
        <div class="card-body-details">
          ${obs.subtitle ? `<p style="color: var(--text-secondary); font-style: italic; margin-bottom: 0.5rem;">${escapeHtml(obs.subtitle)}</p>` : ''}
          ${obs.narrative ? `<p style="color: var(--text-secondary); margin-bottom: 0.5rem;">${escapeHtml(obs.narrative)}</p>` : ''}
          ${factsHtml ? `<ul style="list-style: none; padding: 0; margin: 0.5rem 0;">${factsHtml}</ul>` : ''}
          ${filesHtml ? `<div style="margin-top: 0.5rem;">${filesHtml}</div>` : ''}
        </div>
      </div>
      <div class="card-footer">
        <span class="card-action" onclick="viewStructured(${obs.id})">👁 View</span>
        <span class="card-action" onclick="copyId(${obs.id})">📋 Copy ID</span>
      </div>
    </div>
  `;
}

function toggleCard(obsId) {
  const card = document.querySelector(`.observation-card[data-obs-id="${obsId}"]`);
  if (!card) return;
  const isCompact = card.classList.contains('card-compact');
  if (isCompact) {
    card.classList.remove('card-compact');
    const toggle = card.querySelector('.card-toggle');
    if (toggle) { toggle.textContent = '▼'; toggle.title = 'Collapse'; }
  } else {
    card.classList.add('card-compact');
    const toggle = card.querySelector('.card-toggle');
    if (toggle) { toggle.textContent = '▶'; toggle.title = 'Expand'; }
  }
}

function viewStructured(id) {
  addLog('info', `Viewing structured observation #${id}`);
}

// Log drawer state
let logDrawerPaused = false;
let logDrawerFilter = 'all';
let logDrawerEntries = [];

// Log stream
function startLogStream() {
  initLogDrawer();
  addLog('info', 'kimi-mneme initialized');
  addLog('hook', 'SessionStart hook registered');
  addLog('info', 'Plugin tools loaded: mneme_search, mneme_timeline, mneme_get');

  // Simulate periodic logs
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

function initLogDrawer() {
  const drawer = document.getElementById('log-drawer');
  const header = drawer.querySelector('.log-drawer-header');
  const resize = document.getElementById('log-drawer-resize');
  const pauseBtn = document.getElementById('log-pause');
  const clearBtn = document.getElementById('log-clear');
  const sizeBtn = document.getElementById('log-toggle-size');

  // Toggle collapse on header click
  header.addEventListener('click', (e) => {
    if (e.target.closest('.log-drawer-controls')) return;
    drawer.classList.toggle('collapsed');
  });

  // Filters
  drawer.querySelectorAll('.log-drawer-filter').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      drawer.querySelectorAll('.log-drawer-filter').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      logDrawerFilter = btn.dataset.filter;
      renderLogDrawer();
    });
  });

  // Pause
  pauseBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    logDrawerPaused = !logDrawerPaused;
    pauseBtn.textContent = logDrawerPaused ? '▶' : '⏸';
    pauseBtn.title = logDrawerPaused ? 'Resume' : 'Pause';
  });

  // Clear
  clearBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    logDrawerEntries = [];
    renderLogDrawer();
    logEntries = [];
  });

  // Expand/collapse size
  sizeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    drawer.classList.toggle('expanded');
    sizeBtn.textContent = drawer.classList.contains('expanded') ? '▼' : '▲';
    sizeBtn.title = drawer.classList.contains('expanded') ? 'Collapse' : 'Expand';
  });

  // Resize handle
  let resizing = false;
  let startY, startHeight;
  resize.addEventListener('mousedown', (e) => {
    resizing = true;
    startY = e.clientY;
    startHeight = drawer.offsetHeight;
    document.body.style.cursor = 'ns-resize';
    e.preventDefault();
  });
  document.addEventListener('mousemove', (e) => {
    if (!resizing) return;
    const newHeight = startHeight - (e.clientY - startY);
    if (newHeight > 100 && newHeight < window.innerHeight * 0.7) {
      drawer.style.height = `${newHeight}px`;
      drawer.classList.remove('collapsed');
    }
  });
  document.addEventListener('mouseup', () => {
    resizing = false;
    document.body.style.cursor = '';
  });

  // Keyboard shortcut Ctrl+~ to toggle
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === '`') {
      e.preventDefault();
      drawer.classList.toggle('collapsed');
    }
  });
}

function renderLogDrawer() {
  const body = document.getElementById('log-drawer-body');
  const countEl = document.getElementById('log-drawer-count');

  const filtered = logDrawerFilter === 'all'
    ? logDrawerEntries
    : logDrawerEntries.filter(e => e.level === logDrawerFilter);

  body.innerHTML = filtered.slice(-200).map(e => `
    <div class="log-entry">
      <span class="log-time">${e.time}</span>
      <span class="log-level log-level-${e.level}">${e.level.toUpperCase()}</span>
      <span class="log-message">${escapeHtml(e.message)}</span>
    </div>
  `).join('');

  if (countEl) countEl.textContent = filtered.length;

  // Auto-scroll to bottom
  body.scrollTop = body.scrollHeight;
}

function addLog(level, message) {
  const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

  // Add to drawer
  if (!logDrawerPaused) {
    logDrawerEntries.push({ level, message, time });
    // Keep last 500
    if (logDrawerEntries.length > 500) {
      logDrawerEntries = logDrawerEntries.slice(-500);
    }
    renderLogDrawer();
  }

  logEntries.push({ level, message, time });
}

// Utilities
function parseDate(dateStr) {
  if (!dateStr) return null;
  // Already ISO-8601 (has T or Z) — parse directly
  if (dateStr.includes('T') || dateStr.includes('Z')) {
    const d = new Date(dateStr);
    return isNaN(d.getTime()) ? null : d;
  }
  // SQLite format "YYYY-MM-DD HH:MM:SS" — treat as UTC then convert to local
  const iso = dateStr.replace(' ', 'T') + 'Z';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

function formatDate(dateStr) {
  const date = parseDate(dateStr);
  if (!date) return dateStr || 'Unknown';

  const now = new Date();
  const diff = now - date;

  // Less than 1 hour
  if (diff < 3600000 && diff >= 0) {
    const mins = Math.floor(diff / 60000);
    return mins < 1 ? 'только что' : `${mins} мин назад`;
  }

  // Less than 24 hours
  if (diff < 86400000 && diff >= 0) {
    const hours = Math.floor(diff / 3600000);
    return `${hours} ч назад`;
  }

  // Format as localized date
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Timeline view
async function viewTimeline(sessionId) {
  addLog('info', `Loading timeline for ${sessionId}`);
  try {
    const res = await fetch(`${API_BASE}/session/${sessionId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderTimelineView(data);
  } catch (err) {
    addLog('error', `Failed to load timeline: ${err.message}`);
  }
}

function renderTimelineView(data) {
  const session = data.session;
  const observations = data.observations || [];
  const checkpoint = data.checkpoint;
  const pending = data.pending_messages || [];

  // Hide session list, show timeline
  document.getElementById('observations-stream').style.display = 'none';
  document.getElementById('timeline-view').style.display = 'block';

  // Header
  document.getElementById('timeline-title').textContent = session.project || session.cwd || 'Сессия';
  const started = formatDate(session.started_at);
  const ended = session.ended_at ? formatDate(session.ended_at) : 'активна';
  document.getElementById('timeline-meta').innerHTML = `
    <span>ID: ${session.id.substring(0, 8)}</span>
    <span>•</span>
    <span>${started} — ${ended}</span>
    <span>•</span>
    <span>${observations.length} событий</span>
  `;

  // Extract structured data from observations
  const prompts = observations.filter(o => o.event_type === 'UserPromptSubmit' && o.prompt);
  const errors = observations.filter(o => o.error);
  const fileChanges = [...new Set(observations.filter(o => o.file_path).map(o => o.file_path))];
  const toolsUsed = [...new Set(observations.filter(o => o.tool_name).map(o => o.tool_name))];

  // Build session summary card (AI-generated or heuristic)
  const summaryHtml = buildSessionSummary({
    session,
    prompts,
    errors,
    fileChanges,
    toolsUsed,
    checkpoint,
    pending,
    observations,
    aiSummary: data.ai_summary
  });

  // Build prompt cards — clean, truncated
  const promptCardsHtml = prompts.slice(-5).reverse().map((p, i) => {
    const cleanPrompt = cleanPromptText(p.prompt);
    return `
    <div class="prompt-card">
      <div class="prompt-card-badges">
        <span class="badge-pill badge-prompt">PROMPT</span>
        <span class="badge-pill badge-tool">KIMI</span>
        <span class="prompt-card-project">${escapeHtml(session.project || '')}</span>
      </div>
      <div class="prompt-card-text">${escapeHtml(cleanPrompt)}</div>
      <div class="prompt-card-meta">#${p.id || i} • ${formatDateTime(p.created_at)}</div>
    </div>
  `}).join('');

  // Timeline stream
  const stream = document.getElementById('timeline-stream');
  try {
    stream.innerHTML = `
      ${promptCardsHtml}
      ${summaryHtml}
      ${errors.length > 0 ? renderErrorsSection(errors) : ''}
    `;
  } catch (e) {
    console.error('Timeline render error:', e);
    stream.innerHTML = `<div class="timeline-empty">Ошибка рендеринга: ${escapeHtml(String(e))}</div>`;
  }
}

function buildSessionSummary({ session, prompts, errors, fileChanges, toolsUsed, checkpoint, pending, observations, aiSummary }) {
  // If AI summary exists, use it
  if (aiSummary) {
    return buildAISessionSummary({ session, aiSummary, toolsUsed, fileChanges, observations });
  }

  // Fallback to heuristic summary for active sessions
  return buildHeuristicSessionSummary({ session, prompts, errors, fileChanges, toolsUsed, checkpoint, pending, observations });
}

function buildAISessionSummary({ session, aiSummary, toolsUsed, fileChanges, observations }) {
  // Parse files arrays
  let filesRead = [];
  let filesEdited = [];
  try {
    filesRead = JSON.parse(aiSummary.files_read || '[]');
  } catch {}
  try {
    filesEdited = JSON.parse(aiSummary.files_edited || '[]');
  } catch {}

  const toolCount = toolsUsed.length;
  const fileCount = fileChanges.length;
  const obsCount = observations.length;

  return `
    <div class="session-summary-card">
      <div class="session-summary-badges">
        <span class="badge-pill badge-success">SESSION SUMMARY</span>
        <span class="badge-pill badge-tool">KIMI</span>
        <span class="session-summary-project">${escapeHtml(session.project || '')}</span>
      </div>
      <h3 class="session-summary-title">${escapeHtml(aiSummary.title || 'Сессия')}</h3>
      <div class="session-summary-subtitle">
        ${toolCount > 0 ? `<span>${toolCount} инструментов</span>` : ''}
        ${fileCount > 0 ? `<span>${fileCount} файлов</span>` : ''}
        <span>${obsCount} событий</span>
        ${aiSummary.model ? `<span>AI: ${escapeHtml(aiSummary.model)}</span>` : ''}
      </div>
      <div class="session-summary-divider"></div>

      ${aiSummary.investigated ? `
        <div class="summary-section">
          <div class="summary-section-icon">🔎</div>
          <div class="summary-section-content">
            <div class="summary-section-title">ИССЛЕДОВАНО</div>
            <div class="summary-section-text">${escapeHtml(aiSummary.investigated)}</div>
          </div>
        </div>
      ` : ''}

      ${aiSummary.learned ? `
        <div class="summary-section">
          <div class="summary-section-icon">💡</div>
          <div class="summary-section-content">
            <div class="summary-section-title">УЗНАНО</div>
            <div class="summary-section-text">${escapeHtml(aiSummary.learned)}</div>
          </div>
        </div>
      ` : ''}

      ${aiSummary.completed ? `
        <div class="summary-section">
          <div class="summary-section-icon">✅</div>
          <div class="summary-section-content">
            <div class="summary-section-title">ВЫПОЛНЕНО</div>
            <div class="summary-section-text">${escapeHtml(aiSummary.completed)}</div>
          </div>
        </div>
      ` : ''}

      ${aiSummary.next_steps ? `
        <div class="summary-section">
          <div class="summary-section-icon">➡️</div>
          <div class="summary-section-content">
            <div class="summary-section-title">СЛЕДУЮЩИЕ ШАГИ</div>
            <div class="summary-section-text">${escapeHtml(aiSummary.next_steps)}</div>
          </div>
        </div>
      ` : ''}

      ${(filesRead.length > 0 || filesEdited.length > 0) ? `
        <div class="summary-section">
          <div class="summary-section-icon">📁</div>
          <div class="summary-section-content">
            <div class="summary-section-title">ФАЙЛЫ</div>
            ${filesRead.length > 0 ? `<div class="summary-section-text">📖 ${filesRead.slice(0, 8).map(f => escapeHtml(f)).join(', ')}${filesRead.length > 8 ? '...' : ''}</div>` : ''}
            ${filesEdited.length > 0 ? `<div class="summary-section-text">✏️ ${filesEdited.slice(0, 8).map(f => escapeHtml(f)).join(', ')}${filesEdited.length > 8 ? '...' : ''}</div>` : ''}
          </div>
        </div>
      ` : ''}

      ${aiSummary.notes ? `
        <div class="summary-section">
          <div class="summary-section-icon">📝</div>
          <div class="summary-section-content">
            <div class="summary-section-title">ЗАМЕТКИ</div>
            <div class="summary-section-text">${escapeHtml(aiSummary.notes)}</div>
          </div>
        </div>
      ` : ''}
    </div>
  `;
}

function buildHeuristicSessionSummary({ session, prompts, errors, fileChanges, toolsUsed, checkpoint, pending, observations }) {
  // Generate a smart title from the most meaningful prompt
  const title = generateSessionTitle(prompts, session);

  // Extract "completed" items from observations (heuristic)
  const completedItems = extractCompletedItems(observations);

  // Extract "next steps" from pending or last prompt
  const nextSteps = checkpoint?.open_tasks || [];

  // Build "learned" as readable sentences, not raw lists
  const learnedItems = buildLearnedSummary(toolsUsed, fileChanges, observations);

  // Extract "investigated" from search queries
  const searches = observations.filter(o => o.tool_name === 'mneme_search' && o.tool_input);
  const investigatedItems = searches.map(s => {
    try {
      const input = JSON.parse(s.tool_input);
      return input.query || s.tool_input;
    } catch {
      return s.tool_input;
    }
  }).slice(0, 3);

  // Recent prompts for context (always show at least something)
  const recentPrompts = prompts.slice(-3).map(p => cleanPromptText(p.prompt)).filter(p => p.length > 5);

  // Count stats for subtitle
  const toolCount = toolsUsed.length;
  const fileCount = fileChanges.length;
  const obsCount = observations.length;
  const promptCount = prompts.length;

  // Build sections HTML — always show at least one section
  const sections = [];

  if (investigatedItems.length > 0) {
    sections.push(`
      <div class="summary-section">
        <div class="summary-section-icon">🔎</div>
        <div class="summary-section-content">
          <div class="summary-section-title">ИССЛЕДОВАНО</div>
          ${investigatedItems.map(item => `<div class="summary-section-text">${escapeHtml(item)}</div>`).join('')}
        </div>
      </div>
    `);
  }

  if (learnedItems.length > 0) {
    sections.push(`
      <div class="summary-section">
        <div class="summary-section-icon">💡</div>
        <div class="summary-section-content">
          <div class="summary-section-title">УЗНАНО</div>
          ${learnedItems.map(item => `<div class="summary-section-text">${escapeHtml(item)}</div>`).join('')}
        </div>
      </div>
    `);
  } else if (recentPrompts.length > 0) {
    // Fallback: show recent prompts as context
    sections.push(`
      <div class="summary-section">
        <div class="summary-section-icon">💬</div>
        <div class="summary-section-content">
          <div class="summary-section-title">ОБСУЖДЕНИЕ</div>
          ${recentPrompts.map(item => `<div class="summary-section-text">• ${escapeHtml(item)}</div>`).join('')}
        </div>
      </div>
    `);
  }

  if (completedItems.length > 0) {
    sections.push(`
      <div class="summary-section">
        <div class="summary-section-icon">✅</div>
        <div class="summary-section-content">
          <div class="summary-section-title">ВЫПОЛНЕНО</div>
          ${completedItems.map(item => `<div class="summary-section-text">${escapeHtml(item)}</div>`).join('')}
        </div>
      </div>
    `);
  }

  if (nextSteps.length > 0) {
    sections.push(`
      <div class="summary-section">
        <div class="summary-section-icon">➡️</div>
        <div class="summary-section-content">
          <div class="summary-section-title">СЛЕДУЮЩИЕ ШАГИ</div>
          ${nextSteps.map(item => `<div class="summary-section-text">${escapeHtml(item)}</div>`).join('')}
        </div>
      </div>
    `);
  }

  // If absolutely nothing to show, add a generic message
  if (sections.length === 0) {
    sections.push(`
      <div class="summary-section">
        <div class="summary-section-icon">📋</div>
        <div class="summary-section-content">
          <div class="summary-section-title">СЕССИЯ</div>
          <div class="summary-section-text">Активная сессия с ${promptCount} промптами и ${obsCount} событиями. AI-summary будет сгенерировано после завершения сессии.</div>
        </div>
      </div>
    `);
  }

  return `
    <div class="session-summary-card">
      <div class="session-summary-badges">
        <span class="badge-pill badge-success">SESSION SUMMARY</span>
        <span class="badge-pill badge-tool">KIMI</span>
        <span class="session-summary-project">${escapeHtml(session.project || '')}</span>
      </div>
      <h3 class="session-summary-title">${escapeHtml(title)}</h3>
      <div class="session-summary-subtitle">
        ${toolCount > 0 ? `<span>${toolCount} инструментов</span>` : ''}
        ${fileCount > 0 ? `<span>${fileCount} файлов</span>` : ''}
        ${promptCount > 0 ? `<span>${promptCount} промптов</span>` : ''}
        <span>${obsCount} событий</span>
      </div>
      <div class="session-summary-divider"></div>
      ${sections.join('')}
    </div>
  `;
}

function extractCompletedItems(observations) {
  const items = [];
  // Look for successful file writes
  const writes = observations.filter(o => o.tool_name === 'WriteFile' && !o.error);
  if (writes.length > 0) {
    const files = [...new Set(writes.map(o => o.file_path).filter(Boolean))];
    items.push(`Изменены файлы: ${files.slice(0, 5).join(', ')}${files.length > 5 ? ` и ещё ${files.length - 5}` : ''}`);
  }
  // Look for successful shell commands
  const shells = observations.filter(o => o.tool_name === 'Shell' && !o.error);
  if (shells.length > 0) items.push(`Выполнено ${shells.length} shell-команд`);
  // Look for git commits
  const git = observations.filter(o => o.tool_name === 'Shell' && o.tool_input && o.tool_input.includes('git commit'));
  if (git.length > 0) items.push(`Сделано ${git.length} git-коммитов`);
  return items;
}

function renderErrorsSection(errors) {
  return `
    <div class="session-summary-card session-summary-errors">
      <div class="session-summary-badges">
        <span class="badge-pill badge-error">ERRORS</span>
      </div>
      <h3 class="session-summary-title">Ошибки (${errors.length})</h3>
      <div class="session-summary-divider"></div>
      ${errors.slice(0, 5).map(e => `
        <div class="summary-section">
          <div class="summary-section-icon">❌</div>
          <div class="summary-section-content">
            <div class="summary-section-title">${escapeHtml(e.tool_name || 'Error')}</div>
            <div class="summary-section-text error-text">${escapeHtml(e.error.substring(0, 300))}${e.error.length > 300 ? '...' : ''}</div>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

// Clean prompt text: remove file paths, system output, truncate
function cleanPromptText(text) {
  if (!text) return '';

  // Skip system/output prompts entirely
  const systemPatterns = [
    /^PS\s+claude/i,
    /^SessionStart:/i,
    /^▐▛███▜▌/,
    /^▝▜█████▛▘/,
    /^⎿\s*SessionStart:/i,
    /^Legend:/i,
    /^Column Key/i,
    /^Context Index:/i,
    /^Context Economics/i,
    /^Loading:/i,
    /^Work investment:/i,
    /^Your savings:/i,
    /^May\s+\d+,/i,
    /^#S\d+/,
    /^Investigated:/i,
    /^Learned:/i,
    /^Completed:/i,
    /^Next Steps:/i,
    /^Access\s+\d+k?\s+tokens/i,
    /^View Observations Live/i,
  ];
  for (const pattern of systemPatterns) {
    if (pattern.test(text)) return '[системное сообщение]';
  }

  let cleaned = text;
  // Remove Windows file paths (C:\... or \Users\...)
  cleaned = cleaned.replace(/[A-Za-z]:[\\/][^\n]+/g, '');
  cleaned = cleaned.replace(/\\[A-Za-z][^\n]*/g, '');
  // Remove ANSI escape codes
  cleaned = cleaned.replace(/\x1b\[[0-9;]*m/g, '');
  // Remove box-drawing characters
  cleaned = cleaned.replace(/[▐▛▜▌▝▘⎿─]/g, '');
  // Remove excessive whitespace
  cleaned = cleaned.replace(/\s+/g, ' ').trim();
  // Truncate to reasonable length
  if (cleaned.length > 200) {
    cleaned = cleaned.substring(0, 200) + '...';
  }
  return cleaned || text.substring(0, 200);
}

// Generate a meaningful session title from prompts
function generateSessionTitle(prompts, session) {
  // Find the most meaningful prompt (not just a file path or short phrase)
  const meaningful = prompts.filter(p => {
    const text = p?.prompt || '';
    return text.length > 15 && !text.match(/^[A-Za-z]:[\\/]/);
  });

  const bestPrompt = meaningful.length > 0
    ? meaningful[meaningful.length - 1].prompt
    : (prompts[prompts.length - 1]?.prompt || '');

  const clean = cleanPromptText(bestPrompt);
  if (clean && clean.length > 100) {
    return clean.substring(0, 100) + '...';
  }
  return clean || ('Сессия ' + (session?.id || 'unknown').substring(0, 8));
}

// Build human-readable "learned" summary
function buildLearnedSummary(toolsUsed, fileChanges, observations) {
  const items = [];

  // Filter out null/undefined tools
  const validTools = toolsUsed.filter(t => t && typeof t === 'string');

  // Group tools by category
  const browserTools = validTools.filter(t => t.startsWith('browser_'));
  const mcpTools = validTools.filter(t => ['mneme_search', 'mneme_timeline', 'mneme_get'].includes(t));
  const codeTools = validTools.filter(t => ['WriteFile', 'StrReplaceFile', 'ReadFile', 'Shell'].includes(t));
  const otherTools = validTools.filter(t => !browserTools.includes(t) && !mcpTools.includes(t) && !codeTools.includes(t));

  if (browserTools.length > 0) {
    items.push(`Работа с браузером: ${browserTools.length} инструментов для веб-взаимодействия`);
  }
  if (mcpTools.length > 0) {
    items.push(`Поиск в памяти: использованы инструменты mneme для доступа к истории`);
  }
  if (codeTools.length > 0) {
    const actionNames = [];
    if (codeTools.includes('WriteFile')) actionNames.push('запись файлов');
    if (codeTools.includes('StrReplaceFile')) actionNames.push('редактирование');
    if (codeTools.includes('ReadFile')) actionNames.push('чтение');
    if (codeTools.includes('Shell')) actionNames.push('shell-команды');
    items.push(`Работа с кодом: ${actionNames.join(', ')}`);
  }
  if (otherTools.length > 0) {
    items.push(`Дополнительно: ${otherTools.join(', ')}`);
  }

  // File changes summary
  if (fileChanges.length > 0) {
    const uniqueDirs = [...new Set(fileChanges.map(f => {
      const parts = f.split(/[\\/]/);
      return parts.slice(0, -1).join('/') || 'root';
    }))];
    if (fileChanges.length <= 3) {
      items.push(`Изменённые файлы: ${fileChanges.map(f => f.split(/[\\/]/).pop()).join(', ')}`);
    } else {
      items.push(`Работа с ${fileChanges.length} файлами в ${uniqueDirs.length} директориях`);
    }
  }

  return items;
}

function formatDateTime(dateStr) {
  const d = parseDate(dateStr);
  if (!d) return dateStr || '';
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// Get observation type badge based on content heuristics
function getObservationBadge(obs) {
  const text = (obs.tool_input || obs.tool_output || obs.prompt || '').toLowerCase();
  const tool = (obs.tool_name || '').toLowerCase();
  const event = (obs.event_type || '').toLowerCase();

  // Error-related
  if (obs.error || text.includes('error') || text.includes('exception') || text.includes('failed')) {
    return { class: 'badge-bugfix', label: '🐛 bugfix' };
  }

  // Security
  if (text.includes('security') || text.includes('auth') || text.includes('password') || text.includes('token')) {
    return { class: 'badge-security', label: '🔒 security' };
  }

  // Feature / new functionality
  if (text.includes('add ') || text.includes('create ') || text.includes('implement ') || text.includes('new ')) {
    return { class: 'badge-feature', label: '✨ feature' };
  }

  // Refactor
  if (text.includes('refactor') || text.includes('rewrite') || text.includes('restructure')) {
    return { class: 'badge-refactor', label: '🏗️ refactor' };
  }

  // Discovery / research
  if (tool.includes('search') || tool.includes('grep') || tool.includes('find') || text.includes('investigate')) {
    return { class: 'badge-discovery', label: '🔍 discovery' };
  }

  // Decision
  if (text.includes('decide') || text.includes('choose') || text.includes('approach') || text.includes('solution')) {
    return { class: 'badge-decision', label: '⚖️ decision' };
  }

  // File changes
  if (tool === 'writefile' || tool === 'strreplacefile') {
    return { class: 'badge-change', label: '✅ change' };
  }

  // Default by event type
  if (event === 'userpromptsubmit') {
    return { class: 'badge-prompt', label: 'PROMPT' };
  }

  return { class: 'badge-tool', label: tool.toUpperCase() || 'OBS' };
}

function showSessionList() {
  document.getElementById('timeline-view').style.display = 'none';
  document.getElementById('observations-stream').style.display = 'block';
  loadObservations();
}

function viewDetails(sessionId) {
  // Details shows the same timeline view
  viewTimeline(sessionId);
}

function viewObservation(id) {
  addLog('info', `Viewing observation #${id}`);
}

function copyId(id) {
  navigator.clipboard.writeText(id.toString());
  addLog('info', `Copied ID ${id} to clipboard`);
}

function formatTime(dateStr) {
  if (!dateStr) return '--:--';
  const d = new Date(dateStr);
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// Fallback polling (every 10s) for stats only.
// Observations are pushed via WebSocket in real time.
setInterval(() => {
  if (autoRefresh) {
    loadStats();
  }
}, 10000);

// ============================================================
// SETTINGS MODAL (B.3)
// ============================================================

const SETTINGS_DEFAULTS = {
  structuring: true,
  injection: true,
  vector: true,
  projectmd: true,
  strip_system: true,
  redact_sensitive: true,
  compact_cards: false,
};

let settings = { ...SETTINGS_DEFAULTS };

function loadSettings() {
  try {
    const saved = localStorage.getItem('mneme_settings');
    if (saved) {
      settings = { ...SETTINGS_DEFAULTS, ...JSON.parse(saved) };
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
  applySettingsUI();
}

function saveSettings() {
  try {
    localStorage.setItem('mneme_settings', JSON.stringify(settings));
  } catch (e) {
    console.error('Failed to save settings:', e);
  }
}

function applySettingsUI() {
  const toggles = {
    'setting-structuring-toggle': 'structuring',
    'setting-injection-toggle': 'injection',
    'setting-vector-toggle': 'vector',
    'setting-projectmd-toggle': 'projectmd',
    'setting-strip-system-toggle': 'strip_system',
    'setting-redact-toggle': 'redact_sensitive',
    'setting-compact-toggle': 'compact_cards',
  };

  for (const [id, key] of Object.entries(toggles)) {
    const el = document.getElementById(id);
    if (el) {
      el.classList.toggle('active', settings[key]);
    }
  }

  document.body.classList.toggle('compact-mode', settings.compact_cards);
}

function initSettingsModal() {
  const modal = document.getElementById('settings-modal');
  const btn = document.getElementById('settings-btn');
  const closeBtn = document.getElementById('settings-modal-close');
  const cancelBtn = document.getElementById('settings-cancel');
  const saveBtn = document.getElementById('settings-save');

  btn.addEventListener('click', () => {
    loadSettings();
    modal.style.display = 'flex';
  });

  const closeModal = () => { modal.style.display = 'none'; };
  closeBtn.addEventListener('click', closeModal);
  cancelBtn.addEventListener('click', closeModal);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.style.display === 'flex') {
      closeModal();
    }
  });

  const toggles = {
    'setting-structuring-toggle': 'structuring',
    'setting-injection-toggle': 'injection',
    'setting-vector-toggle': 'vector',
    'setting-projectmd-toggle': 'projectmd',
    'setting-strip-system-toggle': 'strip_system',
    'setting-redact-toggle': 'redact_sensitive',
    'setting-compact-toggle': 'compact_cards',
  };

  for (const [id, key] of Object.entries(toggles)) {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('click', () => {
        settings[key] = !settings[key];
        el.classList.toggle('active', settings[key]);
      });
    }
  }

  saveBtn.addEventListener('click', async () => {
    saveSettings();
    try {
      await fetch(`${API_BASE}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      addLog('info', 'Settings saved');
    } catch (e) {
      addLog('warn', 'Settings saved locally only');
    }
    closeModal();
  });
}

const compactStyles = document.createElement('style');
compactStyles.textContent = `
  .compact-mode .observation-card {
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
  }
  .compact-mode .card-body {
    font-size: 0.8rem;
    line-height: 1.5;
  }
  .compact-mode .card-header {
    margin-bottom: 0.4rem;
  }
  .compact-mode .card-footer {
    margin-top: 0.4rem;
    padding-top: 0.4rem;
  }
`;
document.head.appendChild(compactStyles);

loadSettings();
initSettingsModal();
