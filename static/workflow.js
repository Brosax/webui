/* Workflow builder + trace panel.
 *
 * V1 model:
 * - Sidebar lists workflow definitions (not runs).
 * - Main view defaults to definition editor and a runs tab.
 * - Run trace remains available as evidence drill-down.
 */
let _workflowDefinitions = [];
let _workflowCurrentDef = null;
let _workflowRuns = [];
let _workflowVersions = [];
let _workflowMode = 'list'; // list | definition | run_detail | trace
let _workflowTab = 'canvas'; // canvas | source | runs | trace
let _workflowRunDetail = null;
let _workflowLegacyMode = false;
let _workflowLegacyRuns = [];
let _workflowSource = null;
let _workflowSourceChecksum = null;
let _workflowSourcePath = null;
let _workflowSourceCompatibility = false;
let _workflowFilterQuery = '';
let _workflowActionMenu = null;
let _workflowActionAnchor = null;
let _workflowActionWorkflowId = null;
let _workflowRenamingId = null;

const WORKFLOW_ICONS = {
  more: '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" stroke="none"><circle cx="8" cy="3" r="1.25"/><circle cx="8" cy="8" r="1.25"/><circle cx="8" cy="13" r="1.25"/></svg>',
  edit: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M11.5 2.5l2 2L5 13H3v-2z"/><path d="M10 4l2 2"/></svg>',
  trash: '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3"><path d="M3.5 4.5h9M6.5 4.5V3h3v1.5M4.5 4.5v8.5h7v-8.5"/><line x1="7" y1="7" x2="7" y2="11"/><line x1="9" y1="7" x2="9" y2="11"/></svg>',
};

let _currentTrace = null;
let _traceTimeline = [];
let _traceArtifactCache = {};
let _traceTimelineCollapsed = false;
let _workflowTracePollTimer = null;

// ── Load & Navigation ───────────────────────────────────────────────────────

async function loadWorkflowTasks() {
  const refreshBtn = document.getElementById('workflowRefreshBtn');
  try {
    if (refreshBtn) { refreshBtn.style.opacity = '0.5'; refreshBtn.disabled = true; }
    _workflowLegacyMode = false;
    _stopWorkflowTracePolling();
    const res = await api('/api/workflow/definitions');
    _workflowDefinitions = (res && res.data) ? res.data : [];
    _workflowMode = 'list';
    _workflowTab = 'canvas';
    _workflowRunDetail = null;
    _currentTrace = null;
    renderWorkflowPanel();
  } catch (e) {
    const msg = String(e && e.message ? e.message : '');
    if (msg.toLowerCase().includes('not found')) {
      try {
        const fallback = await api('/api/workflow/runs');
        _workflowLegacyMode = true;
        _workflowLegacyRuns = (fallback && fallback.data) ? fallback.data : [];
        _workflowMode = 'list';
        _workflowRunDetail = null;
        _currentTrace = null;
        renderWorkflowPanel();
        showToast('Workflow definitions API unavailable; using legacy run list.');
        return;
      } catch (fallbackErr) {
        showToast('Failed to load workflows: ' + fallbackErr.message);
        return;
      }
    }
    showToast('Failed to load workflows: ' + msg);
  } finally {
    if (refreshBtn) { refreshBtn.style.opacity = ''; refreshBtn.disabled = false; }
  }
}

function renderWorkflowPanel() {
  const panel = document.getElementById('panelWorkflow');
  const mainView = document.getElementById('mainWorkflow');
  if (!panel) return;

  if (_workflowMode === 'list') {
    if (mainView) mainView.style.display = 'none';
    panel.classList.add('active');
    renderDefinitionList();
    _setWorkflowHeaderButtons('list');
    return;
  }

  _showWorkflowDetail();
  if (_workflowMode === 'definition') {
    _setWorkflowHeaderButtons('definition');
  } else if (_workflowMode === 'run_detail') {
    _setWorkflowHeaderButtons('run_detail');
  } else {
    _setWorkflowHeaderButtons('trace');
  }
}

function _showWorkflowDetail() {
  const panel = document.getElementById('panelWorkflow');
  if (panel) {
    panel.classList.add('active');
    renderDefinitionList();
  }
  const mainView = document.getElementById('mainWorkflow');
  if (mainView) mainView.style.display = '';
}

function _setWorkflowHeaderButtons(mode) {
  const backBtn = document.getElementById('btnWorkflowBack');
  const traceBtn = document.getElementById('btnWorkflowTrace');
  const cancelBtn = document.getElementById('btnWorkflowCancel');
  const collapseBtn = document.getElementById('workflowCollapseBtn');
  const title = document.getElementById('workflowDetailTitle');
  const body = document.getElementById('workflowDetailBody');
  const empty = document.getElementById('workflowDetailEmpty');
  const mainView = document.getElementById('mainWorkflow');
  if (mainView) mainView.classList.toggle('workflow-canvas-mode', mode === 'definition');

  if (mode === 'list') {
    if (backBtn) backBtn.style.display = 'none';
    if (traceBtn) traceBtn.style.display = 'none';
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (collapseBtn) collapseBtn.style.display = 'none';
    if (title) title.textContent = '';
    if (body) { body.style.display = 'none'; body.innerHTML = ''; }
    if (empty) empty.style.display = '';
    return;
  }

  if (backBtn) backBtn.style.display = '';
  if (body) body.style.display = '';
  if (empty) empty.style.display = 'none';

    if (mode === 'definition') {
    if (traceBtn) traceBtn.style.display = 'none';
    if (cancelBtn) cancelBtn.style.display = 'none';
    if (collapseBtn) collapseBtn.style.display = 'none';
    if (title) title.textContent = _workflowCurrentDef?.name || '';
    if (body) {
      body.innerHTML = _renderWorkflowDefinitionContent();
      if (_workflowTab === 'canvas') setTimeout(_initWorkflowDefinitionCanvas, 0);
    }
    return;
  }

  if (mode === 'run_detail') {
    if (traceBtn) traceBtn.style.display = '';
    if (collapseBtn) collapseBtn.style.display = 'none';
    const run = _workflowRunDetail;
    if (cancelBtn && run?.status === 'running') cancelBtn.style.display = '';
    else if (cancelBtn) cancelBtn.style.display = 'none';
    if (title) title.textContent = run?.name || 'Workflow run';
    if (body) body.innerHTML = _renderRunDetailContent(run);
    return;
  }

  const run = _currentTrace?.run;
  if (traceBtn) traceBtn.style.display = 'none';
  if (collapseBtn) collapseBtn.style.display = '';
  if (cancelBtn && run?.status === 'running') cancelBtn.style.display = '';
  else if (cancelBtn) cancelBtn.style.display = 'none';
  if (title) title.textContent = run?.name || 'Trace';
  if (body) body.innerHTML = _renderTraceViewContent();
}

function closeTraceDetail() {
  _stopWorkflowTracePolling();
  if (_workflowMode === 'trace' || _workflowMode === 'run_detail') {
    if (_workflowCurrentDef) {
      _workflowMode = 'definition';
    } else {
      _workflowMode = 'list';
    }
  } else {
    _workflowMode = 'list';
  }
  _workflowRunDetail = null;
  _currentTrace = null;
  renderWorkflowPanel();
}

// ── Definitions ─────────────────────────────────────────────────────────────

function renderDefinitionList() {
  const list = document.getElementById('workflowList');
  if (!list) return;
  if (_workflowActionAnchor && !_workflowActionAnchor.isConnected) closeWorkflowActionMenu();
  if (_workflowLegacyMode) {
    renderLegacyRunList(list);
    return;
  }
  const defs = _getFilteredWorkflowDefinitions();
  if (!_workflowDefinitions.length) {
    list.innerHTML = '<p style="padding:12px;color:var(--muted);font-size:12px">No workflows yet</p>';
    return;
  }
  if (!defs.length) {
    list.innerHTML = '<div class="workflow-list-empty">No workflows match your search.</div>';
    return;
  }
  list.innerHTML = defs.map(renderDefinitionRow).join('');
  _bindWorkflowDefinitionRowHandlers(list, defs);
}

function renderLegacyRunList(list) {
  if (!_workflowLegacyRuns.length) {
    list.innerHTML = '<p style="padding:12px;color:var(--muted);font-size:12px">No workflow runs yet</p>';
    return;
  }
  list.innerHTML = _workflowLegacyRuns.map(renderLegacyRunCard).join('');
}

function renderLegacyRunCard(run) {
  const statusIcon = {'running':'🔄','completed':'✅','failed':'❌','cancelled':'⏹️','pending_approval':'⏳'}[run.status] || '📄';
  const timeAgo = formatTimeAgo(run.created_at);
  const nodeCount = run.node_count || 0;
  const eventCount = run.event_count || 0;
  const artifactCount = run.artifact_count || 0;
  return `
    <div class="workflow-card trace-run-card" data-run-id="${escapeHtml(run.run_id)}" onclick="openRunDetail('${escapeHtml(run.run_id)}')">
      <div class="workflow-card-header">
        <span class="workflow-card-icon">${statusIcon}</span>
        <span class="workflow-card-name">${escapeHtml(run.name || run.run_id)}</span>
        <span class="workflow-status ${escapeHtml(run.status || 'running')}">${escapeHtml(run.status || 'running')}</span>
      </div>
      <div class="workflow-card-meta">
        <span>${nodeCount} nodes</span> · <span>${eventCount} events</span> · <span>${artifactCount} artifacts</span>
        <span class="workflow-card-time">${timeAgo}</span>
      </div>
      <div class="workflow-card-actions">
        <button class="btn btn-sm btn-accent" onclick="event.stopPropagation(); openTraceView('${escapeHtml(run.run_id)}')">Trace</button>
        ${run.status === 'running' ? `<button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); cancelRun('${escapeHtml(run.run_id)}')">Cancel</button>` : ''}
      </div>
    </div>
  `;
}

function renderDefinitionRow(definition) {
  const selected = _workflowCurrentDef && _workflowCurrentDef.workflow_id === definition.workflow_id;
  const workflowId = escapeHtml(definition.workflow_id);
  const workflowName = escapeHtml(definition.name || 'Untitled Workflow');
  const meta = `${definition.status || 'draft'} • ${formatTimeAgo(definition.updated_at)}`;
  return `
    <div class="session-item workflow-session-item${selected ? ' active' : ''}" data-workflow-id="${workflowId}" tabindex="0">
      <div class="session-text workflow-session-text">
        <div class="session-title-row">
          <div class="session-title workflow-session-title">${workflowName}</div>
        </div>
        <div class="session-meta workflow-session-meta">${escapeHtml(meta)}</div>
      </div>
      <div class="session-actions workflow-session-actions">
        <button type="button" class="session-actions-trigger workflow-actions-trigger" data-workflow-actions="${workflowId}" aria-haspopup="menu" aria-label="Workflow actions" title="Workflow actions">
          ${WORKFLOW_ICONS.more}
        </button>
      </div>
    </div>
  `;
}

function filterWorkflowDefinitions() {
  _workflowFilterQuery = (document.getElementById('workflowSearch')?.value || '').trim();
  renderDefinitionList();
}

function _getFilteredWorkflowDefinitions() {
  const query = _workflowFilterQuery.trim().toLowerCase();
  if (!query) return _workflowDefinitions;
  return _workflowDefinitions.filter((definition) => {
    return [
      definition?.name || '',
      definition?.project_id || '',
      definition?.workflow_id || '',
    ].some((value) => String(value).toLowerCase().includes(query));
  });
}

function _bindWorkflowDefinitionRowHandlers(list, definitions) {
  list.querySelectorAll('.workflow-session-item').forEach((row) => {
    const workflowId = row.dataset.workflowId;
    const definition = definitions.find((item) => item.workflow_id === workflowId);
    if (!definition) return;
    row.addEventListener('click', (event) => {
      if (event.target.closest('.workflow-session-actions')) return;
      openWorkflowDefinition(workflowId);
    });
    row.addEventListener('keydown', (event) => {
      if (event.target.closest('.workflow-session-actions')) return;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openWorkflowDefinition(workflowId);
      }
    });
    row._startRename = () => _startWorkflowInlineRename(definition, row);
  });
  list.querySelectorAll('.workflow-actions-trigger').forEach((btn) => {
    btn.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      const workflowId = btn.dataset.workflowActions;
      const definition = definitions.find((item) => item.workflow_id === workflowId);
      if (definition) _openWorkflowActionMenu(definition, btn);
    });
  });
}

function _startWorkflowInlineRename(definition, row) {
  if (!definition || !row || _workflowRenamingId === definition.workflow_id) return;
  closeWorkflowActionMenu();
  _workflowRenamingId = definition.workflow_id;
  row.classList.add('menu-open');
  const title = row.querySelector('.workflow-session-title');
  if (!title) {
    _workflowRenamingId = null;
    row.classList.remove('menu-open');
    return;
  }
  const oldName = definition.name || 'Untitled Workflow';
  const input = document.createElement('input');
  input.className = 'session-title-input workflow-title-input';
  input.value = oldName;
  ['click', 'mousedown', 'dblclick', 'pointerdown'].forEach((type) => {
    input.addEventListener(type, (event) => event.stopPropagation());
  });
  let finishDone = false;
  const releaseRename = () => {
    _workflowRenamingId = null;
    row.classList.remove('menu-open');
    if (input.isConnected) input.replaceWith(title);
  };
  const applyName = (nextName, updateDom = true) => {
    definition.name = nextName;
    const cached = _workflowDefinitions.find((item) => item && item.workflow_id === definition.workflow_id);
    if (cached) cached.name = nextName;
    if (_workflowCurrentDef && _workflowCurrentDef.workflow_id === definition.workflow_id) {
      _workflowCurrentDef.name = nextName;
      const detailTitle = document.getElementById('workflowDetailTitle');
      if (detailTitle && _workflowMode === 'definition') detailTitle.textContent = nextName;
    }
    if (updateDom) title.textContent = nextName;
  };
  const finish = async(save) => {
    if (finishDone) return;
    finishDone = true;
    if (!save) {
      applyName(oldName, false);
      releaseRename();
      return;
    }
    const newName = input.value.trim() || 'Untitled Workflow';
    try {
      if (newName !== oldName) {
        const res = await api(`/api/workflow/definitions/${definition.workflow_id}`, {
          method: 'PATCH',
          body: JSON.stringify({ name: newName }),
        });
        const updated = res.data || {};
        Object.assign(definition, updated);
        const cached = _workflowDefinitions.find((item) => item && item.workflow_id === definition.workflow_id);
        if (cached) Object.assign(cached, updated);
        if (_workflowCurrentDef && _workflowCurrentDef.workflow_id === definition.workflow_id) {
          _workflowCurrentDef = Object.assign(_workflowCurrentDef, updated);
        }
      }
      applyName(newName);
      renderDefinitionList();
    } catch (err) {
      applyName(oldName, false);
      showToast('Failed to rename workflow: ' + (err?.message || err));
    } finally {
      releaseRename();
    }
  };
  input.onkeydown = (event) => {
    if (event.key === 'Enter') {
      if (window._isImeEnter && window._isImeEnter(event)) return;
      event.preventDefault();
      event.stopPropagation();
      finish(true);
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      finish(false);
    }
  };
  input.onblur = () => {
    if (_workflowRenamingId === definition.workflow_id) finish(false);
  };
  title.replaceWith(input);
  setTimeout(() => {
    input.focus();
    input.select();
  }, 10);
}

function _buildWorkflowAction(label, meta, icon, onSelect, extraClass = '') {
  const opt = document.createElement('button');
  opt.type = 'button';
  opt.className = 'ws-opt session-action-opt' + (extraClass ? ` ${extraClass}` : '');
  opt.innerHTML =
    `<span class="ws-opt-action">`
      + `<span class="ws-opt-icon">${icon}</span>`
      + `<span class="session-action-copy">`
        + `<span class="ws-opt-name">${escapeHtml(label)}</span>`
        + (meta ? `<span class="session-action-meta">${escapeHtml(meta)}</span>` : '')
      + `</span>`
    + `</span>`;
  opt.onclick = async(event) => {
    event.preventDefault();
    event.stopPropagation();
    await onSelect();
  };
  return opt;
}

function _positionWorkflowActionMenu(anchorEl) {
  if (!_workflowActionMenu || !anchorEl) return;
  const rect = anchorEl.getBoundingClientRect();
  const menuW = Math.min(280, Math.max(220, _workflowActionMenu.scrollWidth || 220));
  let left = rect.right - menuW;
  if (left < 8) left = 8;
  if (left + menuW > window.innerWidth - 8) left = window.innerWidth - menuW - 8;
  _workflowActionMenu.style.left = left + 'px';
  _workflowActionMenu.style.top = '8px';
  const menuH = _workflowActionMenu.offsetHeight || 0;
  let top = rect.bottom + 6;
  if (top + menuH > window.innerHeight - 8 && rect.top > menuH + 12) top = rect.top - menuH - 6;
  if (top < 8) top = 8;
  _workflowActionMenu.style.top = top + 'px';
}

function closeWorkflowActionMenu() {
  if (_workflowActionMenu) {
    _workflowActionMenu.remove();
    _workflowActionMenu = null;
  }
  if (_workflowActionAnchor) {
    _workflowActionAnchor.classList.remove('active');
    const row = _workflowActionAnchor.closest('.workflow-session-item');
    if (row) row.classList.remove('menu-open');
    _workflowActionAnchor = null;
  }
  _workflowActionWorkflowId = null;
}

function _openWorkflowActionMenu(definition, anchorEl) {
  if (_workflowActionMenu && _workflowActionWorkflowId === definition.workflow_id && _workflowActionAnchor === anchorEl) {
    closeWorkflowActionMenu();
    return;
  }
  closeWorkflowActionMenu();
  const menu = document.createElement('div');
  menu.className = 'session-action-menu open workflow-action-menu';
  menu.appendChild(_buildWorkflowAction(
    'Rename',
    'Edit this workflow name inline',
    WORKFLOW_ICONS.edit,
    () => {
      closeWorkflowActionMenu();
      const row = document.querySelector('.workflow-session-item[data-workflow-id="' + definition.workflow_id + '"]');
      if (row && typeof row._startRename === 'function') row._startRename();
    }
  ));
  menu.appendChild(_buildWorkflowAction(
    'Delete',
    'Remove this workflow definition',
    WORKFLOW_ICONS.trash,
    async() => {
      closeWorkflowActionMenu();
      await deleteWorkflowDefinition(definition.workflow_id);
    },
    'danger'
  ));
  document.body.appendChild(menu);
  _workflowActionMenu = menu;
  _workflowActionAnchor = anchorEl;
  _workflowActionWorkflowId = definition.workflow_id;
  anchorEl.classList.add('active');
  const row = anchorEl.closest('.workflow-session-item');
  if (row) row.classList.add('menu-open');
  _positionWorkflowActionMenu(anchorEl);
}

async function openWorkflowDefinition(workflowId) {
  try {
    const [defRes, runsRes, versionsRes, sourceRes] = await Promise.all([
      api(`/api/workflow/definitions/${workflowId}`),
      api(`/api/workflow/definitions/${workflowId}/runs`),
      api(`/api/workflow/definitions/${workflowId}/versions`),
      api(`/api/workflow/definitions/${workflowId}/source`).catch(() => ({ data: null })),
    ]);
    _workflowCurrentDef = defRes.data || null;
    _workflowRuns = runsRes.data || [];
    _workflowVersions = versionsRes.data || [];
    _workflowSource = sourceRes.data?.source || null;
    _workflowSourceChecksum = sourceRes.data?.checksum || null;
    _workflowSourcePath = sourceRes.data?.source_path || _workflowCurrentDef?.metadata?.source_path || null;
    _workflowSourceCompatibility = !!sourceRes.data?.compatibility_mode;
    _workflowMode = 'definition';
    _workflowTab = 'canvas';
    _workflowRunDetail = null;
    _currentTrace = null;
    renderWorkflowPanel();
  } catch (e) {
    showToast('Failed to load workflow definition: ' + e.message);
  }
}

function _renderWorkflowDefinitionContent() {
  const def = _workflowCurrentDef;
  if (!def) return '';
  if (_workflowTab !== 'canvas') _workflowTab = 'canvas';
  return `
    <div class="workflow-builder">
      ${_renderWorkflowCanvasEditor(def)}
    </div>
  `;
}

function _renderWorkflowCanvasEditor(def) {
  const categories = (window.WorkflowNodeRegistry?.categories || []).map(category => {
    const nodes = window.WorkflowNodeRegistry.list().filter(node => node.category === category);
    return `
      <div class="workflow-palette-category">
        <div class="workflow-palette-heading"><span>${escapeHtml(category)}</span><span>${nodes.length}</span></div>
        ${nodes.map(node => `<button class="workflow-palette-node" draggable="true" data-node-type="${escapeHtml(node.type)}" onclick="addCanvasNode('${escapeHtml(node.type)}')"><span style="color:${escapeHtml(node.accent || '#888')}">${_workflowNodeGlyph(node.type)}</span><strong>${escapeHtml(node.label)}</strong></button>`).join('')}
      </div>
    `;
  }).join('');
  const templates = (window.WorkflowNodeRegistry?.templates || []).map(t => `<button type="button" onclick="applyWorkflowTemplate('${escapeHtml(t.id)}')">${escapeHtml(t.label)}</button>`).join('');
  return `
    <div class="workflow-integrated-editor workflow-gui-editor">
      <div class="canvas-toolbar workflow-editor-toolbar">
        <div class="workflow-editor-brand">
          <span class="workflow-editor-mark"></span>
          <span>Node Editor</span>
          <em>${escapeHtml(def.status || 'draft')}</em>
        </div>
        <details class="workflow-template-menu">
          <summary class="btn btn-sm">Templates</summary>
          <div class="workflow-template-menu-list">${templates || '<span>No templates</span>'}</div>
        </details>
        <button class="btn btn-sm" onclick="undoWorkflowCanvas()" title="Undo">Undo</button>
        <button class="btn btn-sm" onclick="redoWorkflowCanvas()" title="Redo">Redo</button>
        <button class="btn btn-sm" onclick="copyWorkflowSelection()" title="Copy">Copy</button>
        <button class="btn btn-sm" onclick="pasteWorkflowSelection()" title="Paste">Paste</button>
        <button class="btn btn-sm" onclick="deleteWorkflowSelection()" title="Delete">Delete</button>
        <span class="toolbar-sep"></span>
        <button class="btn btn-sm" onclick="validateWorkflowCanvas()">Validate</button>
        <span class="workflow-editor-toolbar-spacer"></span>
        <button class="btn btn-sm" onclick="saveWorkflowDefinition()">Save</button>
        <button class="btn btn-sm" onclick="publishWorkflowDefinition()">Deploy</button>
        <button class="btn btn-sm btn-accent" onclick="runWorkflowDefinition(true)">Execute</button>
      </div>
      <div class="workflow-editor-split workflow-gui-shell">
        <aside class="workflow-node-palette">
          <div class="workflow-palette-top"><span>Nodes</span><input class="workflow-palette-search" id="workflowPaletteSearch" placeholder="Search nodes..." oninput="filterWorkflowPalette()"></div>
          <div id="workflowPaletteList">${categories}</div>
        </aside>
        <section class="workflow-canvas-stage">
          <svg id="workflow-definition-canvas-svg" class="workflow-canvas-svg"></svg>
          <div class="workflow-canvas-controls" aria-label="Canvas view controls">
            <div class="workflow-canvas-controls-group" role="group">
              <button type="button" class="workflow-canvas-control-btn" onclick="zoomWorkflowCanvasIn()" title="Zoom In" aria-label="Zoom In">
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="M11 8v6M8 11h6M16.5 16.5 21 21"></path></svg>
              </button>
              <button type="button" class="workflow-canvas-control-btn" onclick="zoomWorkflowCanvasOut()" title="Zoom Out" aria-label="Zoom Out">
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="M8 11h6M16.5 16.5 21 21"></path></svg>
              </button>
              <button type="button" class="workflow-canvas-control-btn" onclick="fitWorkflowCanvasView()" title="Fit View" aria-label="Fit View">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3"></path><path d="M9 9h6v6H9z"></path></svg>
              </button>
              <button type="button" class="workflow-canvas-control-btn" onclick="resetWorkflowCanvasZoom()" title="Reset 100%" aria-label="Reset 100%">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7V4h3M20 17v3h-3M5 19l14-14"></path><path d="M9 5h10v10"></path><path d="M15 19H5V9"></path></svg>
              </button>
              <button type="button" id="workflowCanvasLockButton" class="workflow-canvas-control-btn workflow-canvas-lock-btn" onclick="toggleWorkflowCanvasLock()" title="Lock Nodes" aria-label="Lock Nodes" aria-pressed="false">
                <svg class="workflow-canvas-lock-icon workflow-canvas-lock-icon--unlocked" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 7.6-1.8"></path></svg>
                <svg class="workflow-canvas-lock-icon workflow-canvas-lock-icon--locked" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path></svg>
              </button>
            </div>
          </div>
          <svg id="workflow-minimap" class="workflow-minimap" viewBox="0 0 200 150"></svg>
        </section>
        <aside class="canvas-config-panel workflow-properties-panel" id="workflow-properties-panel"><div class="canvas-config-empty">Select a node to configure</div></aside>
      </div>
      <div class="workflow-results-drawer" id="workflow-results-drawer"></div>
      <div id="workflowCanvasMessage" class="detail-form-hint"></div>
      ${_workflowSourceCompatibility ? '<div class="detail-form-warning">Compatibility mode: saving will convert this definition to workspace Markdown.</div>' : ''}
    </div>
  `;
}

function _workflowNodeGlyph(type) {
  if (String(type).startsWith('trigger.')) return 'T';
  if (String(type).startsWith('agent.')) return 'A';
  if (String(type).startsWith('control.')) return 'C';
  if (String(type).startsWith('output.')) return 'O';
  if (String(type).startsWith('utility.')) return 'U';
  if (String(type).startsWith('file.')) return 'F';
  if (String(type).startsWith('mcp.')) return 'M';
  return 'N';
}

function _renderSourceEditor() {
  return `
    <div class="workflow-editor">
      <div class="detail-form-row">
        <label for="wfSourcePath">Source path</label>
        <input id="wfSourcePath" type="text" value="${escapeHtml(_workflowSourcePath || '')}" placeholder="workflows/example.workflow.md">
      </div>
      <div class="detail-form-row">
        <label for="wfMarkdownSource">Markdown source</label>
        <textarea id="wfMarkdownSource" rows="26">${escapeHtml(_workflowSource || '')}</textarea>
      </div>
      <div class="detail-form-hint">The fenced hermes-workflow JSON block is generated. Notes outside it are preserved.</div>
    </div>
  `;
}

function _renderDefinitionTrace() {
  if (_currentTrace) return _renderTraceViewContent();
  const latest = (_workflowRuns || [])[0];
  if (!latest) return '<div class="workflow-runs-empty">No trace yet. Run a preview to generate trace.</div>';
  return `<div class="workflow-runs-empty"><button class="btn btn-sm btn-accent" onclick="openLatestDefinitionTrace()">Open latest trace</button></div>`;
}

function _renderDefinitionEditor(def) {
  const inputSchemaText = escapeHtml(JSON.stringify(def.input_schema || [], null, 2));
  const stepsText = escapeHtml(JSON.stringify(def.draft_steps || [], null, 2));
  return `
    <div class="workflow-editor">
      <div class="detail-form-row">
        <label for="wfName">Name</label>
        <input id="wfName" type="text" value="${escapeHtml(def.name || '')}">
      </div>
      <div class="detail-form-row">
        <label for="wfDescription">Description</label>
        <textarea id="wfDescription" rows="3">${escapeHtml(def.description || '')}</textarea>
      </div>
      <div class="detail-form-row">
        <label for="wfDefaultProfile">Default Profile</label>
        <input id="wfDefaultProfile" type="text" value="${escapeHtml(def.default_profile || '')}" placeholder="optional">
      </div>
      <div class="detail-form-row">
        <label for="wfInputSchema">Input Schema (JSON array)</label>
        <textarea id="wfInputSchema" rows="8">${inputSchemaText}</textarea>
      </div>
      <div class="detail-form-row">
        <label for="wfDraftSteps">Draft Steps (JSON array)</label>
        <textarea id="wfDraftSteps" rows="14">${stepsText}</textarea>
      </div>
      <div class="detail-form-hint">
        Step types: <code>skill_call</code>, <code>agent_instruction</code>, <code>approval</code>, <code>output</code>.
      </div>
    </div>
  `;
}

function _renderDefinitionRuns() {
  if (!_workflowRuns.length) {
    return '<div class="workflow-runs-empty">No runs yet.</div>';
  }
  return `
    <div class="workflow-runs-list">
      ${_workflowRuns.map(r => `
        <div class="workflow-run-row">
          <div>
            <div class="workflow-run-row-name">${escapeHtml(r.name || r.run_id)}</div>
            <div class="workflow-run-row-meta">${escapeHtml(r.status || '')} · ${formatTimeAgo(r.created_at)}</div>
          </div>
          <div class="workflow-run-row-actions">
            <button class="btn btn-sm" onclick="openRunDetail('${escapeHtml(r.run_id)}')">Detail</button>
            <button class="btn btn-sm btn-accent" onclick="openTraceView('${escapeHtml(r.run_id)}')">Trace</button>
            ${r.status === 'running' ? `<button class="btn btn-sm btn-danger" onclick="cancelRun('${escapeHtml(r.run_id)}')">Cancel</button>` : ''}
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function toggleWorkflowTab(tab) {
  _workflowTab = ['canvas', 'source', 'runs', 'trace'].includes(tab) ? tab : 'canvas';
  if (_workflowMode === 'definition') renderWorkflowPanel();
}

async function saveWorkflowDefinition() {
  if (!_workflowCurrentDef) return;
  try {
    let res;
    if (_workflowTab === 'source') {
      res = await _saveWorkflowSourceFromEditor();
      _workflowCurrentDef = res.data?.definition || _workflowCurrentDef;
    } else if (_workflowTab === 'canvas') {
      res = await _saveWorkflowSourceFromCanvas();
      _workflowCurrentDef = res.data?.definition || _workflowCurrentDef;
    } else {
      const payload = _collectDefinitionPatch();
      res = await api(`/api/workflow/definitions/${_workflowCurrentDef.workflow_id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      _workflowCurrentDef = res.data || _workflowCurrentDef;
    }
    _workflowDefinitions = _workflowDefinitions.map(d => d.workflow_id === _workflowCurrentDef.workflow_id ? _workflowCurrentDef : d);
    showToast('Draft saved');
    await _reloadWorkflowSource();
    renderWorkflowPanel();
  } catch (e) {
    showToast('Failed to save draft: ' + e.message);
  }
}

async function _saveWorkflowSourceFromEditor() {
  const source = document.getElementById('wfMarkdownSource')?.value || '';
  const sourcePath = (document.getElementById('wfSourcePath')?.value || '').trim() || _workflowSourcePath;
  return api(`/api/workflow/definitions/${_workflowCurrentDef.workflow_id}/source`, {
    method: 'PATCH',
    body: JSON.stringify({ source, source_path: sourcePath, checksum: _workflowSourceChecksum }),
  });
}

async function _saveWorkflowSourceFromCanvas() {
  const sourcePath = _workflowSourcePath || `workflows/${_slugifyWorkflow(_workflowCurrentDef.name || 'workflow')}.workflow.md`;
  const doc = _workflowDocumentFromCanvas(sourcePath);
  const source = _renderWorkflowSourceDocument(doc, _workflowSource || `# ${doc.name}\n\n`);
  return api(`/api/workflow/definitions/${_workflowCurrentDef.workflow_id}/source`, {
    method: 'PATCH',
    body: JSON.stringify({ source, source_path: sourcePath, checksum: _workflowSourceChecksum }),
  });
}

async function _reloadWorkflowSource() {
  if (!_workflowCurrentDef?.workflow_id) return;
  try {
    const sourceRes = await api(`/api/workflow/definitions/${_workflowCurrentDef.workflow_id}/source`);
    _workflowSource = sourceRes.data?.source || _workflowSource;
    _workflowSourceChecksum = sourceRes.data?.checksum || _workflowSourceChecksum;
    _workflowSourcePath = sourceRes.data?.source_path || _workflowSourcePath;
    _workflowSourceCompatibility = !!sourceRes.data?.compatibility_mode;
  } catch (_) {}
}

function _collectDefinitionPatch() {
  const name = (document.getElementById('wfName')?.value || '').trim();
  const description = document.getElementById('wfDescription')?.value || '';
  const defaultProfile = (document.getElementById('wfDefaultProfile')?.value || '').trim();
  const inputSchemaRaw = document.getElementById('wfInputSchema')?.value || '[]';
  const stepsRaw = document.getElementById('wfDraftSteps')?.value || '[]';
  let inputSchema;
  let draftSteps;
  try {
    inputSchema = JSON.parse(inputSchemaRaw);
    if (!Array.isArray(inputSchema)) throw new Error('Input schema must be a JSON array');
  } catch (err) {
    throw new Error('Invalid input schema JSON: ' + err.message);
  }
  try {
    draftSteps = JSON.parse(stepsRaw);
    if (!Array.isArray(draftSteps)) throw new Error('Draft steps must be a JSON array');
  } catch (err) {
    throw new Error('Invalid draft steps JSON: ' + err.message);
  }
  return {
    name: name || 'Untitled Workflow',
    description,
    default_profile: defaultProfile || null,
    input_schema: inputSchema,
    draft_steps: draftSteps,
  };
}

async function publishWorkflowDefinition() {
  if (!_workflowCurrentDef) return;
  try {
    const res = await api(`/api/workflow/definitions/${_workflowCurrentDef.workflow_id}/publish`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
    showToast(`Published v${res.data?.version_number || '?'}`);
    await openWorkflowDefinition(_workflowCurrentDef.workflow_id);
  } catch (e) {
    showToast('Failed to publish workflow: ' + e.message);
  }
}

async function runWorkflowDefinition(isTestRun) {
  if (!_workflowCurrentDef) return;
  let inputs = {};
  const defaultInputs = {
    file_path: 'README.md',
    file_type: 'markdown',
    topic: 'summarize this file'
  };
  const raw = window.prompt('Run inputs (JSON object)', JSON.stringify(defaultInputs, null, 2));
  if (raw === null) return;
  try {
    const parsed = JSON.parse(raw || '{}');
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) inputs = parsed;
    else throw new Error('inputs must be JSON object');
  } catch (e) {
    showToast('Invalid run inputs JSON: ' + e.message);
    return;
  }
  try {
    let res;
    if (isTestRun && _workflowTab === 'canvas') {
      const state = window.getWorkflowEditorState ? window.getWorkflowEditorState() : { nodes: _canvasNodes || [], edges: _canvasEdges || [] };
      res = await api('/api/workflow/canvas/run', {
        method: 'POST',
        body: JSON.stringify({
          workflow_id: _workflowCurrentDef.workflow_id,
          inputs,
          nodes: state.nodes || [],
          edges: state.edges || [],
        }),
      });
    } else {
      const endpoint = isTestRun ? 'test-run' : 'run';
      res = await api(`/api/workflow/definitions/${_workflowCurrentDef.workflow_id}/${endpoint}`, {
        method: 'POST',
        body: JSON.stringify({ inputs }),
      });
    }
    const run = res.data;
    showToast(isTestRun ? 'Test run started' : 'Run started');
    if (run && run.run_id) {
      await openWorkflowDefinition(_workflowCurrentDef.workflow_id);
      openTraceView(run.run_id);
    }
  } catch (e) {
    showToast('Failed to start run: ' + e.message);
  }
}

function openWorkflowCreate() {
  const name = window.prompt('New blank workflow name:');
  if (!name || !name.trim()) return;
  const sourcePath = window.prompt('Workspace source path:', `workflows/${_slugifyWorkflow(name)}.workflow.md`);
  if (!sourcePath) return;
  createWorkflowDefinitionImpl(name.trim(), sourcePath, 'blank');
}

function openWorkflowCreateMenu(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const anchor = event?.currentTarget;
  const existing = document.getElementById('workflowCreateMenu');
  if (existing) existing.remove();

  const menu = document.createElement('div');
  menu.id = 'workflowCreateMenu';
  menu.className = 'workflow-create-menu';
  menu.innerHTML = `
    <button type="button" class="workflow-create-menu-item" data-action="blank">New blank</button>
    <button type="button" class="workflow-create-menu-item" data-action="template">New from template</button>
    <button type="button" class="workflow-create-menu-item" data-action="import">Import Markdown</button>
  `;
  document.body.appendChild(menu);

  const close = () => {
    document.removeEventListener('mousedown', onOutsideClick);
    document.removeEventListener('keydown', onEscape);
    menu.remove();
  };
  const onOutsideClick = (evt) => {
    if (!menu.contains(evt.target) && evt.target !== anchor) close();
  };
  const onEscape = (evt) => {
    if (evt.key === 'Escape') close();
  };
  document.addEventListener('mousedown', onOutsideClick);
  document.addEventListener('keydown', onEscape);

  menu.querySelectorAll('.workflow-create-menu-item').forEach((btn) => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      close();
      if (action === 'blank') openWorkflowCreate();
      else if (action === 'template') openWorkflowCreateTemplate();
      else if (action === 'import') openWorkflowImport();
    });
  });

  if (anchor) {
    const rect = anchor.getBoundingClientRect();
    let left = rect.left;
    let top = rect.bottom + 6;
    const width = 182;
    if (left + width > window.innerWidth - 8) left = window.innerWidth - width - 8;
    if (left < 8) left = 8;
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }
}

function openWorkflowCreateTemplate() {
  const name = window.prompt('New workflow name:', 'Template workflow');
  if (!name || !name.trim()) return;
  const sourcePath = window.prompt('Workspace source path:', `workflows/${_slugifyWorkflow(name)}.workflow.md`);
  if (!sourcePath) return;
  createWorkflowDefinitionImpl(name.trim(), sourcePath, 'basic');
}

function openWorkflowImport() {
  const sourcePath = window.prompt('Import workspace Markdown path:', 'workflows/example.workflow.md');
  if (!sourcePath) return;
  importWorkflowDefinitionImpl(sourcePath.trim());
}

async function createWorkflowDefinitionImpl(name, sourcePath, template) {
  try {
    const res = await api('/api/workflow/definitions/source', {
      method: 'POST',
      body: JSON.stringify({
        action: 'create',
        name,
        source_path: sourcePath,
        template,
      }),
    });
    showToast('Workflow created');
    const created = res.data;
    await loadWorkflowTasks();
    if (created && created.workflow_id) {
      openWorkflowDefinition(created.workflow_id);
    }
  } catch (e) {
    showToast('Failed to create workflow: ' + e.message);
  }
}

async function importWorkflowDefinitionImpl(sourcePath) {
  try {
    const res = await api('/api/workflow/definitions/source', {
      method: 'POST',
      body: JSON.stringify({ action: 'import', source_path: sourcePath }),
    });
    showToast('Workflow imported');
    const created = res.data;
    await loadWorkflowTasks();
    if (created && created.workflow_id) openWorkflowDefinition(created.workflow_id);
  } catch (e) {
    showToast('Failed to import workflow: ' + e.message);
  }
}

async function deleteWorkflowDefinition(workflowId) {
  if (!workflowId) return;
  const definition = _workflowDefinitions.find(d => d.workflow_id === workflowId) || _workflowCurrentDef;
  const name = definition?.name || 'this workflow';
  if (!window.confirm(`Delete "${name}"?`)) return;
  try {
    await api(`/api/workflow/definitions/${workflowId}`, { method: 'DELETE' });
    showToast('Workflow deleted');
    if (_workflowCurrentDef?.workflow_id === workflowId) {
      _workflowCurrentDef = null;
      _workflowRuns = [];
      _workflowVersions = [];
      _workflowSource = null;
      _workflowSourceChecksum = null;
      _workflowSourcePath = null;
      _workflowSourceCompatibility = false;
      _workflowMode = 'list';
      _workflowRunDetail = null;
      _currentTrace = null;
    }
    await loadWorkflowTasks();
  } catch (e) {
    showToast('Failed to delete workflow: ' + e.message);
  }
}

document.addEventListener('click', (event) => {
  if (!_workflowActionMenu) return;
  if (_workflowActionMenu.contains(event.target)) return;
  if (_workflowActionAnchor && _workflowActionAnchor.contains(event.target)) return;
  closeWorkflowActionMenu();
});
document.addEventListener('scroll', (event) => {
  if (!_workflowActionMenu) return;
  if (_workflowActionMenu.contains(event.target)) return;
  closeWorkflowActionMenu();
}, true);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && _workflowActionMenu) closeWorkflowActionMenu();
});
window.addEventListener('resize', () => {
  if (_workflowActionMenu && _workflowActionAnchor) _positionWorkflowActionMenu(_workflowActionAnchor);
});

function openLatestDefinitionTrace() {
  const latest = (_workflowRuns || [])[0];
  if (latest?.run_id) openTraceView(latest.run_id);
}

function _initWorkflowDefinitionCanvas() {
  const svg = document.getElementById('workflow-definition-canvas-svg');
  if (!svg || !_workflowCurrentDef) return;
  const sourceDoc = _parseWorkflowSourceDocument(_workflowSource);
  const state = window.deserializeWorkflowEditor
    ? window.deserializeWorkflowEditor(_workflowCurrentDef, sourceDoc)
    : { nodes: (_workflowCurrentDef.draft_steps || []).map((step, idx) => _canvasNodeFromStep(step, idx)), edges: ((_workflowCurrentDef.metadata || {})._canvas_edges || []) };
  if (window.setWorkflowEditorState) window.setWorkflowEditorState(state);
  initCanvas(svg, true);
  _bindWorkflowPaletteDrag();
}

function _canvasNodeFromStep(step, idx) {
  const typeMap = { agent_instruction: 'agent.run', agent: 'agent.run', input: 'file.input', file_input: 'file.input', file_output: 'file.output', output: 'output.results_display' };
  const type = typeMap[step.type] || step.type || 'agent';
  const cfg = Object.assign({}, step.config || {});
  if (type === 'agent.run' && !cfg.instruction) cfg.instruction = step.prompt || step.instruction || '';
  if (type === 'prompt' && !cfg.template) cfg.template = step.template || '';
  if (type === 'output.results_display' && cfg.value === undefined) cfg.value = step.value || '';
  return {
    id: step.step_id || step.id || `node_${idx + 1}`,
    type,
    name: step.name || step.step_id || `Node ${idx + 1}`,
    x: step.x || 80 + (idx * 190),
    y: step.y || 120,
    config: cfg,
  };
}

function validateWorkflowCanvas() {
  const message = document.getElementById('workflowCanvasMessage');
  const errors = _validateCanvasDag(_canvasNodes || [], _canvasEdges || []);
  if (message) message.textContent = errors.length ? errors.join(' ') : 'Canvas is a valid DAG.';
  if (errors.length) showToast(errors[0]);
  return errors.length === 0;
}

function _validateCanvasDag(nodes, edges) {
  const ids = new Set(nodes.map(n => n.id));
  const incoming = {};
  const outgoing = {};
  nodes.forEach(n => { incoming[n.id] = 0; outgoing[n.id] = []; });
  for (const edge of edges) {
    const from = edge.from || edge.source;
    const to = edge.to || edge.target;
    if (!ids.has(from) || !ids.has(to)) return ['Edges must connect existing nodes.'];
    if (from === to) return ['A node cannot connect to itself.'];
    outgoing[from].push(to);
    incoming[to] += 1;
  }
  const ready = Object.keys(incoming).filter(id => incoming[id] === 0);
  let visited = 0;
  while (ready.length) {
    const id = ready.shift();
    visited += 1;
    outgoing[id].forEach(next => {
      incoming[next] -= 1;
      if (incoming[next] === 0) ready.push(next);
    });
  }
  return visited === nodes.length ? [] : ['Workflow graph contains a cycle.'];
}

function _workflowDocumentFromCanvas(sourcePath) {
  const existing = _parseWorkflowSourceDocument(_workflowSource);
  const state = window.getWorkflowEditorState ? window.getWorkflowEditorState() : { nodes: _canvasNodes || [], edges: _canvasEdges || [] };
  const serialized = window.serializeWorkflowEditor ? window.serializeWorkflowEditor(state, existing) : existing;
  return Object.assign({}, existing, {
    ...serialized,
    schema_version: 1,
    id: _workflowCurrentDef.workflow_id,
    name: _workflowCurrentDef.name || 'Untitled Workflow',
    description: _workflowCurrentDef.description || '',
    default_profile: _workflowCurrentDef.default_profile || null,
    inputs: _workflowCurrentDef.input_schema || existing.inputs || [],
    nodes: serialized.nodes || [],
    edges: serialized.edges || [],
    outputs: existing.outputs || [],
    canvas: Object.assign({}, serialized.canvas || {}, { source_path: sourcePath }),
  });
}

function filterWorkflowPalette() {
  const query = (document.getElementById('workflowPaletteSearch')?.value || '').toLowerCase();
  document.querySelectorAll('.workflow-palette-node').forEach(btn => {
    btn.style.display = btn.textContent.toLowerCase().includes(query) || btn.dataset.nodeType.toLowerCase().includes(query) ? '' : 'none';
  });
}

function _bindWorkflowPaletteDrag() {
  document.querySelectorAll('.workflow-palette-node').forEach(btn => {
    btn.addEventListener('dragstart', ev => ev.dataTransfer?.setData('text/workflow-node-type', btn.dataset.nodeType || 'core.set'));
  });
  const stage = document.querySelector('.workflow-canvas-stage');
  const svg = document.getElementById('workflow-definition-canvas-svg');
  if (!stage || !svg) return;
  stage.addEventListener('dragover', ev => ev.preventDefault());
  stage.addEventListener('drop', ev => {
    ev.preventDefault();
    const type = ev.dataTransfer?.getData('text/workflow-node-type');
    if (!type) return;
    const rect = svg.getBoundingClientRect();
    addCanvasNode(type, { x: ev.clientX - rect.left - 110, y: ev.clientY - rect.top - 40 });
  });
}

function applyWorkflowTemplate(templateId) {
  const template = (window.WorkflowNodeRegistry?.templates || []).find(t => t.id === templateId);
  if (!template || !window.setWorkflowEditorState) return;
  const nodes = (template.nodes || []).map((type, idx) => {
    const def = window.WorkflowNodeRegistry.get(type);
    return {
      id: `${String(type).replace(/[^a-z0-9]+/gi, '_')}_${idx + 1}`,
      type,
      name: def?.label || type,
      typeVersion: 1,
      position: { x: 80 + idx * 280, y: 140 },
      parameters: window.WorkflowNodeRegistry.defaultParameters(type),
      disabled: false,
      continueOnFail: false,
    };
  });
  const edges = nodes.slice(1).map((node, idx) => ({
    id: `edge_${idx + 1}`,
    source: nodes[idx].id,
    target: node.id,
    sourceHandle: (window.WorkflowNodeRegistry.get(nodes[idx].type)?.outputs || [{ id: 'out' }])[0]?.id || 'out',
    targetHandle: 'in',
  }));
  window.setWorkflowEditorState({ nodes, edges, canvas: { zoom: 1, scroll: { x: 0, y: 0 }, selectedNodeIds: [] } });
  initCanvas(document.getElementById('workflow-definition-canvas-svg'), true);
}

function _parseWorkflowSourceDocument(source) {
  if (!source) return {};
  const match = source.match(/<!-- hermes-workflow:start -->\s*```(?:json)?\s*([\s\S]*?)\s*```\s*<!-- hermes-workflow:end -->/);
  if (!match) return {};
  try { return JSON.parse(match[1]); } catch (_) { return {}; }
}

function _renderWorkflowSourceDocument(doc, existing) {
  const block = `<!-- hermes-workflow:start -->\n\`\`\`json\n${JSON.stringify(doc, null, 2)}\n\`\`\`\n<!-- hermes-workflow:end -->`;
  if (existing && existing.match(/<!-- hermes-workflow:start -->[\s\S]*<!-- hermes-workflow:end -->/)) {
    return existing.replace(/<!-- hermes-workflow:start -->[\s\S]*<!-- hermes-workflow:end -->/, block);
  }
  return `${(existing || '').trim()}\n\n${block}\n`;
}

function _slugifyWorkflow(value) {
  return String(value || 'workflow').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'workflow';
}

// ── Run Detail + Trace ──────────────────────────────────────────────────────

async function openRunDetail(runId) {
  try {
    const res = await api(`/api/workflow/runs/${runId}`);
    _workflowRunDetail = res.data || null;
    _workflowMode = 'run_detail';
    renderWorkflowPanel();
  } catch (e) {
    showToast('Failed to load run: ' + e.message);
  }
}

function _renderRunDetailContent(run) {
  if (!run) return '<div class="muted">Run not found.</div>';
  const statusIcon = {'running':'🔄','completed':'✅','failed':'❌','cancelled':'⏹️','pending_approval':'⏳'}[run.status] || '📄';
  return `
    <div class="workflow-detail">
      <div class="detail-card">
        <div class="detail-card-title">Run Info</div>
        <div class="detail-row"><div class="detail-row-label">Run ID</div><div class="detail-row-value"><code>${escapeHtml(run.run_id)}</code></div></div>
        <div class="detail-row"><div class="detail-row-label">Status</div><div class="detail-row-value"><span class="workflow-status ${escapeHtml(run.status || '')}">${statusIcon} ${escapeHtml(run.status || '')}</span></div></div>
        <div class="detail-row"><div class="detail-row-label">Created</div><div class="detail-row-value">${run.created_at ? formatTimeAgo(run.created_at) : '—'}</div></div>
        <div class="detail-row"><div class="detail-row-label">By</div><div class="detail-row-value">${escapeHtml(run.created_by || 'unknown')}</div></div>
        ${run.error ? `<div class="detail-row"><div class="detail-row-label">Error</div><div class="detail-row-value error-text">${escapeHtml(run.error)}</div></div>` : ''}
      </div>
      <div class="detail-actions">
        <button class="btn btn-accent" onclick="openTraceViewFromDetail()">View Full Trace</button>
        ${run.status === 'running' ? `<button class="btn btn-danger" onclick="cancelWorkflowFromDetail()">Cancel Run</button>` : ''}
      </div>
    </div>
  `;
}

async function openTraceView(runId) {
  _stopWorkflowTracePolling();
  try {
    const res = await api(`/api/workflow/runs/${runId}/trace`);
    _currentTrace = res.data || null;
    _workflowMode = 'trace';
    _buildTimeline();
    renderWorkflowPanel();
    if (_currentTrace?.run?.status === 'running') _startWorkflowTracePolling(runId);
  } catch (e) {
    showToast('Failed to load trace: ' + e.message);
  }
}

function _startWorkflowTracePolling(runId) {
  _stopWorkflowTracePolling();
  _workflowTracePollTimer = setInterval(async () => {
    try {
      const res = await api(`/api/workflow/runs/${runId}/trace`);
      _currentTrace = res.data || null;
      _buildTimeline();
      if (_workflowMode === 'trace') renderWorkflowPanel();
      const status = _currentTrace?.run?.status;
      if (!['running', 'pending_approval'].includes(status)) _stopWorkflowTracePolling();
    } catch (e) {
      _stopWorkflowTracePolling();
      showToast('Trace polling stopped: ' + e.message);
    }
  }, 800);
}

function _stopWorkflowTracePolling() {
  if (_workflowTracePollTimer) {
    clearInterval(_workflowTracePollTimer);
    _workflowTracePollTimer = null;
  }
}

function _buildTimeline() {
  _traceTimeline = [];
  _traceArtifactCache = {};
  if (!_currentTrace) return;
  const run = _currentTrace.run;
  const nodes = _currentTrace.nodes || [];
  const events = _currentTrace.events || [];
  const artifacts = _currentTrace.artifacts || [];

  for (const art of artifacts) {
    _traceArtifactCache[art.artifact_id] = art;
  }

  const nodeMap = {};
  for (const node of nodes) nodeMap[node.node_id] = node;

  for (const event of events) {
    _traceTimeline.push({ type: 'event', event, node: nodeMap[event.node_id] || null, run });
  }
  for (const node of nodes) {
    if (node.status === 'completed' || node.status === 'failed' || node.ended_at) {
      _traceTimeline.push({
        type: 'node_done',
        node,
        run,
        _seq: node.ended_at ? new Date(node.ended_at).getTime() : Infinity,
      });
    }
  }
  _traceTimeline.sort((a, b) => {
    const aSeq = a.event ? Number(a.event.event_id || 0) : Number(a._seq || 0);
    const bSeq = b.event ? Number(b.event.event_id || 0) : Number(b._seq || 0);
    if (aSeq !== bSeq) return aSeq - bSeq;
    if (a.type === 'node_done' && b.type === 'event') return 1;
    if (a.type === 'event' && b.type === 'node_done') return -1;
    return 0;
  });
}

function _renderTraceViewContent() {
  const run = _currentTrace?.run;
  if (!run) return '';
  const nodes = _currentTrace.nodes || [];
  const events = _currentTrace.events || [];
  const artifacts = _currentTrace.artifacts || [];
  const currentNode = nodes.find(node => node.status === 'running');
  const finalOutput = _findFinalTraceOutput(nodes);
  return `
    <div class="trace-timeline" id="traceTimeline">
      <div class="trace-summary">
        <div class="trace-stat"><span class="trace-stat-num">${nodes.length}</span><span class="trace-stat-label">Nodes</span></div>
        <div class="trace-stat"><span class="trace-stat-num">${events.length}</span><span class="trace-stat-label">Events</span></div>
        <div class="trace-stat"><span class="trace-stat-num">${artifacts.length}</span><span class="trace-stat-label">Artifacts</span></div>
        <div class="trace-run-state">
          <span class="workflow-status ${escapeHtml(run.status || '')}">${escapeHtml(run.status || '')}</span>
          <strong>${currentNode ? `Now running: ${escapeHtml(currentNode.name || currentNode.agent_name || currentNode.node_id)}` : _traceRunStatusLabel(run)}</strong>
        </div>
      </div>
      <div class="trace-node-list">
        ${nodes.length ? nodes.map((node, idx) => renderTraceNodeCard(node, idx)).join('') : '<p style="padding:12px;color:var(--muted);font-size:12px">No nodes recorded yet.</p>'}
      </div>
      ${finalOutput ? `<div class="trace-final-output"><h4>Result</h4><pre class="detail-code">${escapeHtml(finalOutput)}</pre></div>` : ''}
      <details class="trace-raw-events" ${_traceTimelineCollapsed ? '' : 'open'}>
        <summary>Raw events</summary>
      <div class="trace-events">
        ${_traceTimeline.length ? _traceTimeline.map(item => renderTimelineItem(item)).join('') : '<p style="padding:12px;color:var(--muted);font-size:12px">No events recorded yet.</p>'}
      </div>
      </details>
    </div>
  `;
}

function _traceRunStatusLabel(run) {
  if (run.status === 'completed') return 'Workflow completed';
  if (run.status === 'failed') return run.error ? `Failed: ${escapeHtml(run.error)}` : 'Workflow failed';
  if (run.status === 'cancelled') return 'Workflow cancelled';
  return 'Waiting for workflow progress';
}

function _findFinalTraceOutput(nodes) {
  const completed = (nodes || []).filter(node => node.status === 'completed' && node.structured_result);
  const outputNode = completed.slice().reverse().find(node => String(node.agent_name || '').includes('output'));
  const node = outputNode || completed[completed.length - 1];
  if (!node) return '';
  const result = node.structured_result;
  if (result && Object.prototype.hasOwnProperty.call(result, 'value')) {
    return typeof result.value === 'string' ? result.value : JSON.stringify(result.value, null, 2);
  }
  if (result && result.message) return result.message;
  return JSON.stringify(result, null, 2);
}

function renderTraceNodeCard(node, index) {
  const status = node.status || 'pending';
  const icon = {'pending':'○','running':'●','completed':'✓','failed':'!','skipped':'-','cancelled':'×'}[status] || '•';
  const result = node.structured_result;
  const summary = node.summary || node.error || '';
  return `
    <article class="trace-node-card trace-node-card-${escapeHtml(status)}" data-node-id="${escapeHtml(node.node_id)}">
      <div class="trace-node-index">${index + 1}</div>
      <div class="trace-node-main">
        <div class="trace-node-card-head">
          <span class="trace-node-status-dot">${icon}</span>
          <strong>${escapeHtml(node.name || node.agent_name || node.node_id)}</strong>
          <span class="workflow-status ${escapeHtml(status)}">${escapeHtml(status)}</span>
        </div>
        <div class="trace-node-type">${escapeHtml(node.agent_name || '')}</div>
        ${summary ? `<p class="trace-node-summary">${escapeHtml(summary)}</p>` : ''}
        ${result ? `<details class="trace-node-output"><summary>Output preview</summary><pre class="detail-code">${escapeHtml(_compactPayload(result, 1200))}</pre></details>` : ''}
        ${node.artifacts && node.artifacts.length > 0 ? `<div class="node-artifacts-list">${node.artifacts.map(artId => renderArtifactChip(artId)).join('')}</div>` : ''}
      </div>
    </article>
  `;
}

function renderTraceView(panel) {
  return _renderTraceViewContent();
}

function renderTimelineItem(item) {
  if (item.type === 'event') return renderEventCard(item.event, item.node);
  return renderNodeDoneMarker(item.node);
}

function renderEventCard(event, node) {
  const eventIcon = _getEventIcon(event.event_type);
  const nodeLabel = node ? `<span class="event-node-label">${escapeHtml(node.agent_name || node.node_id || 'unknown')}</span>` : '';
  const actorLabel = event.actor ? `<span class="event-actor">${escapeHtml(event.actor)}</span>` : '';
  const redactedMark = event.redacted ? '<span class="redacted-mark" title="This event was redacted">🔒</span>' : '';
  const truncatedMark = event.truncated ? '<span class="truncated-mark" title="This event was truncated">📄↕</span>' : '';
  return `
    <div class="trace-event" data-event-id="${escapeHtml(event.event_id)}">
      <div class="trace-event-header" onclick="toggleEventBody(this)">
        <span class="trace-event-icon">${eventIcon}</span>
        <span class="trace-event-type">${escapeHtml(event.event_type)}</span>
        ${nodeLabel}
        ${actorLabel}
        <span class="trace-event-time">${formatTimeAgo(event.created_at)}</span>
        ${redactedMark}${truncatedMark}
        <span class="trace-event-chevron">▸</span>
      </div>
      <div class="trace-event-body">${_renderEventPayload(event)}</div>
    </div>
  `;
}

function _getEventIcon(eventType) {
  const icons = {
    token: '💬',
    tool: '🔧',
    approval: '✅',
    approval_request: '⏳',
    error: '❌',
    done: '🏁',
    skill_invocation: '🎯',
    node_start: '▶️',
    node_end: '⏹️',
  };
  return icons[eventType] || '📌';
}

function _renderEventPayload(event) {
  const payload = event.payload || {};
  const eventType = event.event_type;
  if (!['token', 'tool', 'approval', 'approval_request', 'error', 'done', 'skill_invocation', 'node_start', 'node_end'].includes(eventType)) {
    // Generic fallback card for unknown event types.
    return `<div class="event-payload-generic"><pre class="detail-code">${escapeHtml(JSON.stringify(payload, null, 2))}</pre></div>`;
  }
  if (eventType === 'token') {
    return `<div class="token-text">${escapeHtml(_compactPayload(payload))}</div>`;
  }
  if (eventType === 'tool') {
    return `<dl class="detail-dl">
      <dt>Tool</dt><dd>${escapeHtml(payload.tool_name || payload.name || 'unknown')}</dd>
      ${payload.input ? `<dt>Input</dt><dd><pre class="detail-code">${escapeHtml(JSON.stringify(payload.input, null, 2))}</pre></dd>` : ''}
      ${payload.output ? `<dt>Output</dt><dd><pre class="detail-code">${escapeHtml(_compactPayload(payload.output))}</pre></dd>` : ''}
      ${payload.error ? `<dt class="error-text">Error</dt><dd class="error-text">${escapeHtml(payload.error)}</dd>` : ''}
    </dl>`;
  }
  if (eventType === 'approval' || eventType === 'approval_request') {
    return `<dl class="detail-dl">
      <dt>Patterns</dt><dd>${(payload.pattern_keys || []).map(k => `<code>${escapeHtml(k)}</code>`).join(', ') || '—'}</dd>
      ${payload.status ? `<dt>Status</dt><dd>${escapeHtml(payload.status)}</dd>` : ''}
      ${payload.approved !== undefined ? `<dt>Approved</dt><dd>${payload.approved ? 'Yes' : 'No'}</dd>` : ''}
      ${payload.message ? `<dt>Message</dt><dd>${escapeHtml(payload.message)}</dd>` : ''}
    </dl>`;
  }
  if (eventType === 'error') {
    return `<p class="error-text">${escapeHtml(payload.message || 'Unknown error')}</p>${payload.stack ? `<pre class="detail-code">${escapeHtml(payload.stack)}</pre>` : ''}`;
  }
  if (eventType === 'skill_invocation') {
    return `<dl class="detail-dl">
      <dt>Skill</dt><dd>${escapeHtml(payload.skill_name || 'unknown')}</dd>
      ${payload.snapshot ? `<dt>Snapshot</dt><dd><pre class="detail-code">${escapeHtml(JSON.stringify(payload.snapshot, null, 2))}</pre></dd>` : ''}
    </dl>`;
  }
  if (eventType === 'done') {
    return payload.summary ? `<p>${escapeHtml(payload.summary)}</p>` : '<p>Done</p>';
  }
  return `<pre class="detail-code">${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
}

function _compactPayload(payload, maxLen = 500) {
  if (payload === undefined || payload === null) return '';
  const text = typeof payload === 'string' ? payload : JSON.stringify(payload);
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '...';
}

function renderNodeDoneMarker(node) {
  const statusIcon = {'completed':'✅','failed':'❌','cancelled':'⏹️','pending':'⏳'}[node.status] || '⏹️';
  return `
    <div class="trace-node-done" data-node-id="${escapeHtml(node.node_id)}">
      <div class="trace-node-done-header" onclick="toggleNodeDoneBody(this)">
        <span class="trace-node-done-icon">${statusIcon}</span>
        <span class="trace-node-done-name">${escapeHtml(node.agent_name || node.node_id || 'Unknown Node')}</span>
        <span class="trace-node-done-status status-${escapeHtml(node.status || 'pending')}">${escapeHtml(node.status || '')}</span>
        <span class="trace-node-done-time">${node.ended_at ? formatTimeAgo(node.ended_at) : ''}</span>
        <span class="trace-event-chevron">▸</span>
      </div>
      ${(node.structured_result || node.summary || (node.artifacts && node.artifacts.length > 0)) ? `
      <div class="trace-node-done-body">
        ${node.structured_result ? `<div class="node-output-section"><h5>Structured Result</h5><pre class="detail-code">${escapeHtml(JSON.stringify(node.structured_result, null, 2))}</pre></div>` : ''}
        ${node.summary ? `<div class="node-output-section"><h5>Summary</h5><p>${escapeHtml(node.summary)}</p></div>` : ''}
        ${node.artifacts && node.artifacts.length > 0 ? `<div class="node-output-section"><h5>Artifacts</h5><div class="node-artifacts-list">${node.artifacts.map(artId => renderArtifactChip(artId)).join('')}</div></div>` : ''}
      </div>` : ''}
    </div>
  `;
}

// ── Artifact Display ────────────────────────────────────────────────────────

function renderArtifactChip(artifactId) {
  const artifact = _traceArtifactCache[artifactId];
  if (!artifact) {
    return `<span class="artifact-chip artifact-chip-loading" data-artifact-id="${escapeHtml(artifactId)}"><span class="artifact-chip-icon">📎</span><span class="artifact-chip-name">${escapeHtml(String(artifactId).slice(0, 8))}…</span><span class="artifact-chip-loading-text">Loading…</span></span>`;
  }
  const icon = _getArtifactIcon(artifact.type);
  const size = formatFileSize(artifact.size);
  return `<span class="artifact-chip" data-artifact-id="${escapeHtml(artifactId)}" onclick="showArtifactDetail('${escapeHtml(artifactId)}')"><span class="artifact-chip-icon">${icon}</span><span class="artifact-chip-name">${escapeHtml(artifact.name)}</span><span class="artifact-chip-size">${size}</span></span>`;
}

function _getArtifactIcon(type) {
  return {'document':'📄','code':'💻','image':'🖼️','data':'📊'}[type] || '📎';
}

async function showArtifactDetail(artifactId) {
  try {
    const res = await api(`/api/workflow/trace-artifacts/${artifactId}`);
    const artifact = res.data;
    const detail = `
      <div class="artifact-detail-modal">
        <div class="artifact-detail-header">
          <h4>${escapeHtml(artifact.name)}</h4>
          <span class="artifact-detail-size">${formatFileSize(artifact.size)}</span>
          <span class="artifact-detail-type">${escapeHtml(artifact.type)}</span>
        </div>
        <div class="artifact-detail-meta">
          <dl class="detail-dl">
            <dt>ID</dt><dd><code>${escapeHtml(artifact.artifact_id)}</code></dd>
            <dt>Created</dt><dd>${artifact.created_at ? formatTimeAgo(artifact.created_at) : '—'}</dd>
            ${artifact.hash_sha256 ? `<dt>SHA256</dt><dd><code class="hash-code">${escapeHtml(artifact.hash_sha256)}</code></dd>` : ''}
          </dl>
        </div>
        <div class="artifact-detail-actions">
          <button class="btn btn-sm" onclick="downloadArtifact('${escapeHtml(artifactId)}')">Download</button>
          <button class="btn btn-sm" onclick="viewArtifactContent('${escapeHtml(artifactId)}')">View Content</button>
        </div>
        <div class="artifact-detail-content" id="artifactDetailContent"><p class="muted">Click "View Content" to load.</p></div>
      </div>
    `;
    _showArtifactModal(detail);
  } catch (e) {
    showToast('Failed to load artifact: ' + e.message);
  }
}

function _showArtifactModal(content) {
  const existing = document.getElementById('artifactModal');
  if (existing) existing.remove();
  const overlay = document.createElement('div');
  overlay.id = 'artifactModal';
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `<div class="modal-content artifact-modal">${content}<button class="modal-close" onclick="closeArtifactModal()">×</button></div>`;
  overlay.onclick = (e) => { if (e.target === overlay) closeArtifactModal(); };
  document.body.appendChild(overlay);
}

function closeArtifactModal() {
  const modal = document.getElementById('artifactModal');
  if (modal) modal.remove();
}

async function viewArtifactContent(artifactId) {
  const contentEl = document.getElementById('artifactDetailContent');
  if (!contentEl) return;
  contentEl.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const content = await api(`/api/workflow/trace-artifacts/${artifactId}/content`);
    const text = (content && typeof content === 'string') ? content : '';
    contentEl.innerHTML = `<pre class="detail-code artifact-content-preview">${escapeHtml(text.slice(0, 5000))}</pre>${text.length > 5000 ? '<p class="muted">…truncated</p>' : ''}`;
  } catch (e) {
    contentEl.innerHTML = `<p class="error-text">Failed to load content: ${escapeHtml(e.message)}</p>`;
  }
}

function downloadArtifact(artifactId) {
  window.open(`/api/workflow/trace-artifacts/${artifactId}/content`, '_blank');
}

// ── Run Actions ─────────────────────────────────────────────────────────────

async function cancelRun(runId) {
  if (!confirm('Cancel this workflow run?')) return;
  try {
    await api(`/api/workflow/runs/${runId}/cancel`, { method: 'POST', body: JSON.stringify({}) });
    showToast('Run cancelled');
    if (_workflowCurrentDef) await openWorkflowDefinition(_workflowCurrentDef.workflow_id);
    if (_workflowMode === 'trace') openTraceView(runId);
  } catch (e) {
    showToast('Failed to cancel run: ' + e.message);
  }
}

function openTraceViewFromDetail() {
  if (_workflowRunDetail && _workflowRunDetail.run_id) {
    openTraceView(_workflowRunDetail.run_id);
    return;
  }
  if (_currentTrace?.run?.run_id) {
    openTraceView(_currentTrace.run.run_id);
  }
}

function cancelWorkflowFromDetail() {
  if (_workflowRunDetail && _workflowRunDetail.run_id) {
    cancelRun(_workflowRunDetail.run_id);
    return;
  }
  if (_currentTrace?.run?.run_id) cancelRun(_currentTrace.run.run_id);
}

function toggleTraceTimeline() {
  _traceTimelineCollapsed = !_traceTimelineCollapsed;
  document.querySelectorAll('.trace-event-body').forEach(el => {
    el.classList.toggle('trace-event-body_open', !_traceTimelineCollapsed);
  });
  document.querySelectorAll('.trace-node-done-body').forEach(el => {
    el.classList.toggle('trace-node-done-body_open', !_traceTimelineCollapsed);
  });
}

function toggleEventBody(headerEl) {
  const card = headerEl.closest('.trace-event');
  if (!card) return;
  const body = card.querySelector('.trace-event-body');
  if (!body) return;
  const chevron = headerEl.querySelector('.trace-event-chevron');
  const isHidden = !body.classList.contains('trace-event-body_open');
  body.classList.toggle('trace-event-body_open', isHidden);
  if (chevron) chevron.textContent = isHidden ? '▾' : '▸';
}

function toggleNodeDoneBody(headerEl) {
  const card = headerEl.closest('.trace-node-done');
  if (!card) return;
  const body = card.querySelector('.trace-node-done-body');
  if (!body) return;
  body.classList.toggle('trace-node-done-body_open');
}

// ── Utilities ───────────────────────────────────────────────────────────────

function escapeHtml(str) {
  if (str === undefined || str === null) return '';
  return String(str).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function formatTimeAgo(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatFileSize(bytes) {
  if (!bytes) return '0B';
  const n = parseInt(bytes, 10);
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / (1024 * 1024)).toFixed(1)}MB`;
}

// Back-compat alias (previous feature created trace runs directly).
const createTraceRun = openWorkflowCreate;

// ── Exports ─────────────────────────────────────────────────────────────────
window.loadWorkflowTasks = loadWorkflowTasks;
window.renderWorkflowPanel = renderWorkflowPanel;
window.openWorkflowDefinition = openWorkflowDefinition;
window.openWorkflowCreate = openWorkflowCreate;
window.openWorkflowCreateMenu = openWorkflowCreateMenu;
window.openWorkflowCreateTemplate = openWorkflowCreateTemplate;
window.openWorkflowImport = openWorkflowImport;
window.deleteWorkflowDefinition = deleteWorkflowDefinition;
window.saveWorkflowDefinition = saveWorkflowDefinition;
window.publishWorkflowDefinition = publishWorkflowDefinition;
window.runWorkflowDefinition = runWorkflowDefinition;
window.toggleWorkflowTab = toggleWorkflowTab;
window.validateWorkflowCanvas = validateWorkflowCanvas;
window.filterWorkflowPalette = filterWorkflowPalette;
window.applyWorkflowTemplate = applyWorkflowTemplate;
window.openLatestDefinitionTrace = openLatestDefinitionTrace;

window.openRunDetail = openRunDetail;
window.openTraceView = openTraceView;
window.renderTraceView = renderTraceView;
window.closeTraceDetail = closeTraceDetail;
window.cancelRun = cancelRun;
window.createTraceRun = createTraceRun;
window.showArtifactDetail = showArtifactDetail;
window.viewArtifactContent = viewArtifactContent;
window.downloadArtifact = downloadArtifact;
window.toggleTraceTimeline = toggleTraceTimeline;
window.toggleEventBody = toggleEventBody;
window.toggleNodeDoneBody = toggleNodeDoneBody;
window.closeArtifactModal = closeArtifactModal;
window.openTraceViewFromDetail = openTraceViewFromDetail;
window.cancelWorkflowFromDetail = cancelWorkflowFromDetail;
