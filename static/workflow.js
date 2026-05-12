/* Workflow panel JS module */
let _workflowTasks = [];
let _currentTaskDetail = null;
let _workflowDetailMode = 'list'; // 'list' | 'detail'

async function loadWorkflowTasks() {
  try {
    const res = await api('/api/workflow/tasks');
    _workflowTasks = res.data || [];
    renderWorkflowPanel();
  } catch (e) {
    showToast('Failed to load workflows: ' + e.message);
  }
}

function renderWorkflowPanel() {
  const panel = document.getElementById('panelWorkflow');
  if (!panel) return;

  if (_workflowDetailMode === 'detail' && _currentTaskDetail) {
    renderWorkflowDetail(panel);
  } else {
    renderWorkflowList(panel);
  }
}

function renderWorkflowList(panel) {
  panel.innerHTML = `
    <div class="panel-header">
      <h3>Workflows</h3>
      <button class="btn btn-primary" onclick="showWorkflowCreateModal()">+ New</button>
    </div>
    <div class="workflow-list">
      ${_workflowTasks.length === 0 ? '<p class="empty-state">No workflows yet</p>' : ''}
      ${_workflowTasks.map(t => renderTaskCard(t)).join('')}
    </div>
  `;
}

function renderTaskCard(task) {
  const statusIcon = {'pending':'⏳','running':'🔄','completed':'✅','failed':'❌'}[task.status] || '📄';
  const timeAgo = formatTimeAgo(task.created_at);
  const callsCount = task.calls?.length || 0;
  const artifactsCount = task.artifacts?.length || 0;

  return `
    <div class="workflow-card" data-task-id="${escapeHtml(task.id)}" onclick="openWorkflowDetail(this.dataset.taskId)">
      <div class="workflow-card-header">
        <span class="workflow-card-icon">${statusIcon}</span>
        <span class="workflow-card-name">${escapeHtml(task.name)}</span>
        <span class="workflow-card-status">${task.status}</span>
      </div>
      <div class="workflow-card-meta">
        <span>${callsCount} calls</span> · <span>${artifactsCount} artifacts</span>
        <span class="workflow-card-time">${timeAgo}</span>
      </div>
    </div>
  `;
}

async function openWorkflowDetail(taskId) {
  try {
    const res = await api(`/api/workflow/tasks/${taskId}`);
    _currentTaskDetail = res.data;
    _workflowDetailMode = 'detail';
    renderWorkflowPanel();
  } catch (e) {
    showToast('Failed to load task: ' + e.message);
  }
}

function renderWorkflowDetail(panel) {
  const task = _currentTaskDetail;
  const statusIcon = {'pending':'⏳','running':'🔄','completed':'✅','failed':'❌'}[task.status] || '📄';

  panel.innerHTML = `
    <div class="panel-header">
      <button class="btn-back" onclick="closeWorkflowDetail()">← Back</button>
      <h3>${escapeHtml(task.name)}</h3>
      <span class="status-badge status-${task.status}">${statusIcon} ${task.status}</span>
    </div>
    <div class="workflow-detail">
      <section class="detail-section">
        <h4>Input</h4>
        <pre class="detail-code">${escapeHtml(JSON.stringify(task.input, null, 2))}</pre>
      </section>
      <section class="detail-section">
        <h4>Calls (${task.calls?.length || 0})</h4>
        <div class="calls-list">
          ${task.calls?.map((callId, i) => renderCallCard(callId, i)).join('') || '<p>No calls</p>'}
        </div>
      </section>
      <section class="detail-section">
        <h4>Artifacts (${task.artifacts?.length || 0})</h4>
        <div class="artifacts-list">
          ${task.artifacts?.map(artId => renderArtifactCard(artId)).join('') || '<p>No artifacts</p>'}
        </div>
      </section>
    </div>
  `;

  loadCallDetails(task.calls || []);
  loadArtifactDetails(task.artifacts || []);
}

async function loadCallDetails(callIds) {
  for (const callId of callIds) {
    try {
      const res = await api(`/api/workflow/tasks/${_currentTaskDetail.id}/calls`);
      const calls = res.data || [];
      calls.forEach(call => {
        const el = document.querySelector(`[data-call-id="${call.id}"]`);
        if (el) {
          el.innerHTML = renderCallCardContent(call);
        }
      });
    } catch (e) { console.warn('Failed to load call details:', e); }
  }
}

function renderCallCard(callId, index) {
  return `<div class="call-card" data-call-id="${callId}"><div class="call-card-loading">Loading...</div></div>`;
}

function renderCallCardContent(call) {
  return `
    <div class="call-card-content">
      <div class="call-header">
        <span class="call-index">#${call.agent_name}</span>
        <span class="call-status status-${call.status}">${call.status}</span>
      </div>
      <div class="call-body">
        <details>
          <summary>Input</summary>
          <pre class="detail-code">${escapeHtml(JSON.stringify(call.input, null, 2))}</pre>
        </details>
        ${call.output ? `<details><summary>Output</summary><pre class="detail-code">${escapeHtml(JSON.stringify(call.output, null, 2))}</pre></details>` : ''}
        ${call.error ? `<p class="call-error">Error: ${escapeHtml(call.error)}</p>` : ''}
      </div>
    </div>
  `;
}

async function loadArtifactDetails(artifactIds) {
  for (const artId of artifactIds) {
    try {
      const res = await api(`/api/workflow/artifacts/${artId}`);
      const el = document.querySelector(`[data-artifact-id="${artId}"]`);
      if (el && res.data) {
        el.innerHTML = renderArtifactCardContent(res.data);
      }
    } catch (e) { console.warn('Failed to load artifact details:', e); }
  }
}

function renderArtifactCard(artId) {
  return `<div class="artifact-card" data-artifact-id="${artId}"><div class="loading">Loading...</div></div>`;
}

function renderArtifactCardContent(artifact) {
  return `
    <div class="artifact-card-content">
      <span class="artifact-icon">${getArtifactIcon(artifact.type)}</span>
      <span class="artifact-name">${escapeHtml(artifact.name)}</span>
      <span class="artifact-size">${formatFileSize(artifact.size)}</span>
    </div>
  `;
}

function getArtifactIcon(type) {
  return {'document':'📄','code':'💻','image':'🖼️'}[type] || '📎';
}

function closeWorkflowDetail() {
  _currentTaskDetail = null;
  _workflowDetailMode = 'list';
  renderWorkflowPanel();
}

function showWorkflowCreateModal() {
  const name = prompt('Workflow name:');
  if (!name) return;
  createWorkflowTask(name);
}

async function createWorkflowTask(name) {
  try {
    const res = await api('/api/workflow/tasks', {
      method: 'POST',
      body: JSON.stringify({ name, input: {} })
    });
    if (res.data) {
      _workflowTasks.unshift(res.data);
      renderWorkflowPanel();
      showToast('Workflow created');
    }
  } catch (e) {
    showToast('Failed to create workflow: ' + e.message);
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function formatTimeAgo(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatFileSize(bytes) {
  if (!bytes) return '0B';
  if (bytes < 1024) return bytes + 'B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB';
  return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
}

// Export for panel integration
window.loadWorkflowTasks = loadWorkflowTasks;
window.renderWorkflowPanel = renderWorkflowPanel;
window.openWorkflowDetail = openWorkflowDetail;
window.closeWorkflowDetail = closeWorkflowDetail;
window.showWorkflowCreateModal = showWorkflowCreateModal;

/* Integration: trigger workflow from Skills panel */
async function triggerWorkflowFromSkill(skillName, params) {
  // Create task with skill as input
  const task = await api('/api/workflow/tasks', {
    method: 'POST',
    body: JSON.stringify({
      name: `Skill: ${skillName}`,
      input: { skill: skillName, params }
    })
  });

  if (task.data) {
    _workflowTasks.unshift(task.data);
    renderWorkflowPanel();
    openWorkflowDetail(task.data.id);
    showToast(`Started workflow: ${skillName}`);
  }
}

// Export for skills integration
window.triggerWorkflowFromSkill = triggerWorkflowFromSkill;