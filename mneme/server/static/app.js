/* kimi-mneme — Mneme Glass UI JavaScript */

const API_BASE = '/api';

// State
let currentProject = 'all';
let currentFilter = 'all';
let autoRefresh = true;
let logEntries = [];

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
  loadStats();
  loadObservations();
  startLogStream();
});

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

    // Token economics (demo calculations)
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
    const ease = 1 - Math.pow(1 - progress, 3); // ease-out cubic
    const current = Math.round(start + (target - start) * ease);
    el.textContent = current;

    if (progress < 1) {
      requestAnimationFrame(update);
    }
  }

  requestAnimationFrame(update);
}

// Load observations
async function loadObservations() {
  try {
    // Build query params
    const params = new URLSearchParams();
    params.append('limit', '20');
    if (currentProject && currentProject !== 'all') {
      params.append('project', currentProject);
    }

    const res = await fetch(`${API_BASE}/sessions?${params.toString()}`);
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

    container.innerHTML = data.sessions.map(s => renderSessionCard(s)).join('');

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

// Log stream
function startLogStream() {
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

  // Keep only last 100 entries
  while (stream.children.length > 100) {
    stream.removeChild(stream.lastChild);
  }

  logEntries.push({ level, message, time });
  document.getElementById('log-count').textContent = `${logEntries.length} entries`;
}

// Utilities
function formatDate(dateStr) {
  if (!dateStr) return 'Unknown';
  // SQLite returns ISO format or local time — ensure proper parsing
  const date = new Date(dateStr.replace(' ', 'T') + (dateStr.includes('T') || dateStr.includes('Z') ? '' : 'Z'));
  if (isNaN(date.getTime())) return dateStr;

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
  // If AI summary exists, use it (structured style)
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
  cleaned = cleaned.replace(/[▐▛███▜▌▝▜█████▛▘▘▘ ▝▝⎿─]/g, '');
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
  if (!dateStr) return '';
  // Ensure proper parsing of SQLite datetime
  const d = new Date(dateStr.replace(' ', 'T') + (dateStr.includes('T') || dateStr.includes('Z') ? '' : 'Z'));
  if (isNaN(d.getTime())) return dateStr;
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

// Auto-refresh observations
setInterval(() => {
  if (autoRefresh) {
    loadStats();
    const searchInput = document.getElementById('search-input');
    if (!searchInput.value.trim()) {
      loadObservations();
    }
  }
}, 30000);
