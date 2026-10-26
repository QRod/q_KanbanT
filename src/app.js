import { STORAGE_KEY, priorities, validBoard, duration, activeDuration, localInput, dayKey, dayOrdinal, taskOnDay, timeline, dependencyOrder, dependencyLinks } from './board.js';

const $ = selector => document.querySelector(selector);
const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };
const btn = (text, cls, fn, label) => { const b = el('button', cls, text); b.type = 'button'; b.addEventListener('click', fn); if (label) b.setAttribute('aria-label', label); return b; };
const responsibleName = task => task.assigneeGroupId ? `Grupo: ${state.groups.find(g => g.id === task.assigneeGroupId)?.name || 'Sin grupo'}` : state.users.find(u => u.id === task.assigneeId)?.name || 'Sin responsable';
const dateText = value => value ? new Date(value).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' }) : 'Sin definir';
const names = { users: 'usuario', groups: 'grupo', projects: 'proyecto', tasks: 'tarea', columns: 'columna' };
let state = null, page = 'board', projectId = '', editor = null, needsSetup = false, toastTimer, loading = false;
let editorSnapshot = '';
let month = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
function notify(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 6500); }
async function api(path, body) {
  const response = await fetch(`/api/${path}`, { credentials: 'same-origin', cache: 'no-store', ...(body !== undefined ? { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-QKT-Request': '1' }, body: JSON.stringify(body) } : {}) });
  let result;
  try { result = await response.json(); } catch { throw new Error('El servidor no ofrece la API. Inícialo con «npm run dev» usando la nueva versión.'); }
  if (!response.ok) { if (response.status === 401 && !['login', 'setup'].includes(path)) showAuth(); throw new Error(result.error || 'No se pudo completar la solicitud.'); }
  return result;
}
function showAuth() { state = null; $('#app').hidden = true; $('#sidebar').hidden = true; $('#auth').hidden = false; if ($('#editor').open) $('#editor').close(); }
async function start() {
  try {
    const session = await api('session'); needsSetup = session.needsSetup;
    $('#setup-name').hidden = !needsSetup; $('#auth-form').elements.name.required = needsSetup;
    $('#auth-form').elements.password.autocomplete = needsSetup ? 'new-password' : 'current-password';
    $('#auth-title').textContent = needsSetup ? 'Crea tu espacio' : 'Iniciar sesión';
    $('#auth-description').textContent = needsSetup ? 'Registra al primer administrador para comenzar.' : 'Accede a tus proyectos y tareas.';
    $('#auth-submit').textContent = needsSetup ? 'Crear administrador' : 'Entrar';
    if (session.me) await refresh(); else showAuth();
  } catch (error) { showAuth(); $('#auth-error').textContent = error.message; }
}
async function refresh() {
  state = await api('state');
  if (!state.projects.some(p => p.id === projectId)) projectId = state.projects[0]?.id || '';
  $('#auth').hidden = true; $('#app').hidden = false; $('#sidebar').hidden = false;
  $('#me-name').textContent = state.me.name; $('#me-avatar').textContent = state.me.name.slice(0, 1).toUpperCase();
  $('#me-role').textContent = state.me.role === 'admin' ? 'Administrador' : 'Integrante';
  $('#sync-time').textContent = `Actualizado ${new Date().toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' })}`;
  $('#connection').textContent = '● Base de datos local';
  $('#import-legacy').hidden = true;
  try { const raw = localStorage.getItem(STORAGE_KEY); if (state.me.role === 'admin' && !state.legacyImported && raw && validBoard(JSON.parse(raw))) $('#import-legacy').hidden = false; } catch { /* Los datos del navegador permanecen intactos. */ }
  render();
}
async function command(kind, action, data) { await api('command', { kind, action, data }); await refresh(); }
function run(fn) { return async (...args) => { try { await fn(...args); } catch (error) { notify(error.message); } }; }
const currentProject = () => state?.projects.find(p => p.id === projectId);
const columns = () => state.columns.filter(c => c.projectId === projectId).sort((a, b) => a.position - b.position);
function memberIds(project = currentProject()) { return new Set([...(project?.userIds || []), ...state.groups.filter(g => project?.groupIds.includes(g.id)).flatMap(g => g.userIds)]); }
function projectUsers() {
  // Los integrantes reciben del servidor solo el directorio de sus proyectos.
  return state.me.role === 'admin' ? state.users.filter(u => memberIds().has(u.id)) : state.users.filter(u => currentProject()?.memberIds?.includes(u.id));
}
function visibleTasks() {
  const query = $('#search').value.trim().toLocaleLowerCase('es');
  return state.tasks.filter(t => t.projectId === projectId && (!$('#type-filter').value || t.type === $('#type-filter').value) && (!$('#priority-filter').value || t.priority === $('#priority-filter').value) && (!$('#only-mine').checked || t.assigneeId === state.me.id || state.groups.some(g => g.id === t.assigneeGroupId && g.userIds.includes(state.me.id))) && `${t.folio} ${t.title} ${t.description}`.toLocaleLowerCase('es').includes(query));
}
function render() {
  const title = page === 'board' ? 'Mi tablero' : page === 'users' ? 'Usuarios' : 'Grupos';
  $('#breadcrumb').textContent = title; $('#page-title').textContent = title;
  $('#page-subtitle').textContent = page === 'board' ? 'Tu equipo, conectado con lo que sigue.' : page === 'users' ? 'Personas, accesos y responsabilidades.' : 'Equipos que trabajan hacia un mismo objetivo.';
  document.querySelectorAll('[data-page]').forEach(n => n.classList.toggle('nav-active', n.dataset.page === page));
  $('#board-page').hidden = page !== 'board'; $('#management-page').hidden = page === 'board';
  $('#create-main').textContent = page === 'board' ? '＋ Nuevo registro' : page === 'users' ? '＋ Nuevo usuario' : '＋ Nuevo grupo';
  $('#create-main').hidden = page !== 'board' && state.me.role !== 'admin';
  $('#create-main').disabled = page === 'board' && !columns().length;
  if (page !== 'board') return renderManagement();
  $('#project-select').replaceChildren(...state.projects.map(p => new Option(p.name, p.id)));
  if (!state.projects.length) $('#project-select').add(new Option('Sin proyectos asignados', ''));
  $('#project-select').value = projectId;
  $('#project-actions').hidden = state.me.role !== 'admin';
  $('#edit-project').disabled = !projectId; $('#delete-project').disabled = !projectId; $('#new-column').disabled = !projectId;
  $('#project-members').textContent = currentProject() ? `${projectUsers().length} integrantes` : 'Solicita acceso a un administrador.';
  const selectedType = $('#type-filter').value;
  $('#type-filter').replaceChildren(new Option('Todos los tipos', ''), ...Object.entries(state.types).map(([key, value]) => new Option(value.label, key)));
  $('#type-filter').value = selectedType;
  renderBoard(); renderSchedule(); renderActivity($('#project-activity-list'), state.activity.filter(e => e.projectId === projectId));
}
function incompleteDependencies(task) {
  return (task.dependencyIds || []).map(id => state.tasks.find(t => t.id === id)).filter(t => t && state.columns.find(c => c.id === t.columnId)?.stage !== 'done');
}
function approvalLabel(task) { return {pending: 'Pendiente', approved: 'Aprobado', rejected: 'Rechazado'}[task.approval?.status] || 'Pendiente'; }
function transitionReason(task, column) {
  const source = state.columns.find(c => c.id === task.columnId), from = source?.stage, to = column.stage;
  if (from !== to && !state.types[task.type].transitions[from]?.includes(to)) return 'El flujo de este tipo no permite esta transición.';
  const execution = task.type === 'request' ? ['progress', 'done'] : ['progress', 'review', 'done'];
  if (task.type === 'change' && execution.includes(to) && task.approval?.status !== 'approved') return 'Requiere aprobación de un administrador.';
  if (execution.includes(to) && incompleteDependencies(task).length) return 'Primero deben terminar sus dependencias.';
  if (from === 'done' && to !== 'done' && state.tasks.some(t => t.dependencyIds.includes(task.id) && (t.type === 'request' ? ['progress', 'done'] : ['progress', 'review', 'done']).includes(state.columns.find(c => c.id === t.columnId)?.stage))) return 'Tiene registros sucesores en ejecución o terminados.';
  return '';
}
function renderActivity(container, events) {
  container.replaceChildren();
  if (!events.length) { container.append(el('p', 'view-note', 'Todavía no hay actividad registrada.')); return; }
  const labels = { created: 'creó el registro', updated: 'actualizó el registro', deleted: 'eliminó el registro', commented: 'publicó un comentario', approve: 'aprobó el cambio', reject: 'rechazó el cambio', migrated: 'migró el registro; la actividad anterior no estaba registrada' };
  for (const event of [...events].sort((a, b) => b.createdAt.localeCompare(a.createdAt))) {
    const item = el('article', 'activity-item');
    const heading = el('p'); heading.append(el('strong', '', event.actorName), document.createTextNode(` ${labels[event.action] || event.action} · ${event.folio}`));
    item.append(heading, el('small', '', dateText(event.createdAt)));
    for (const change of event.changes || []) item.append(el('p', 'activity-change', `${change.label}: ${change.before} → ${change.after}`));
    const task = state.tasks.find(t => t.id === event.taskId);
    if (task && container.id === 'project-activity-list') item.append(btn(event.title, 'undated-task', () => openEditor('tasks', task)));
    container.append(item);
  }
}
function renderDiscussion() {
  if (editor?.kind !== 'tasks' || !editor.record) return;
  const task = state.tasks.find(t => t.id === editor.record.id);
  if (!task) return;
  const list = $('#comments-list'); list.replaceChildren();
  for (const comment of state.comments.filter(c => c.taskId === task.id)) {
    const article = el('article', 'comment'); article.append(el('strong', '', comment.authorName), el('small', '', dateText(comment.createdAt)), el('p', '', comment.body)); list.append(article);
  }
  if (!list.children.length) list.append(el('p', 'view-note', 'Añade el primer comentario.'));
  renderActivity($('#record-activity'), state.activity.filter(e => e.taskId === task.id));
  const panel = $('#approval-panel'); panel.replaceChildren();
  if (task.type !== 'change') return;
  panel.append(el('h3', '', `Aprobación · ${approvalLabel(task)}`));
  if (task.approval?.decidedAt) panel.append(el('p', 'view-note', `${task.approval.actorName} · ${dateText(task.approval.decidedAt)} · ${task.approval.reason}`));
  if (state.columns.find(c => c.id === task.columnId)?.stage === 'approval' && task.approval?.status === 'pending') {
    if (state.me.role !== 'admin') { panel.append(el('p', 'view-note', 'En espera de la decisión de un administrador.')); return; }
    const label = el('label', '', 'Motivo de la decisión'); const reason = el('textarea'); reason.id = 'approval-reason'; reason.rows = 2; reason.maxLength = 2000; label.append(reason); panel.append(label);
    const actions = el('div', 'approval-actions');
    for (const [action, title] of [['approve', 'Aprobar cambio'], ['reject', 'Rechazar cambio']]) actions.append(btn(title, action === 'approve' ? 'primary' : 'secondary', run(async () => {
      if (editorSnapshot !== JSON.stringify([...new FormData($('#editor-form'))])) return notify('Guarda los cambios del formulario antes de registrar una decisión.');
      if (!reason.value.trim()) return notify('Escribe el motivo de la decisión.');
      await command('tasks', action, {id: task.id, reason: reason.value, expectedUpdatedAt: editor.record.updatedAt});
      openEditor('tasks', state.tasks.find(t => t.id === task.id)); notify('Decisión registrada.');
    })));
    panel.append(actions);
  }
}
async function move(task, columnId) { if (task.columnId === columnId) return; await command('tasks', 'move', { id: task.id, columnId }); notify('Tarea movida.'); }
function taskMetrics(task) {
  const container = el('div', 'task-metrics');
  container.append(el('small', '', `Creada: ${dateText(task.createdAt)}`), el('small', '', `Inicio: ${dateText(task.startAt)}`), el('small', '', `Fin: ${dateText(task.endAt)}`));
  const active = el('small', 'live-active', `Activa: ${activeDuration(task)}`); active.dataset.task = task.id;
  const status = el('small', 'live-status', `En estatus: ${duration(task.statusSince)}`); status.dataset.task = task.id;
  container.append(active, status); return container;
}
function renderBoard() {
  const tasks = visibleTasks(); $('#board').replaceChildren();
  const total = state.tasks.filter(t => t.projectId === projectId).length;
  $('#total-count').textContent = total; $('#summary').textContent = `${columns().length} columnas · ${total} tareas · ${tasks.length} visibles`;
  columns().forEach((column, index) => {
    const section = el('section', `column color-${index % 4}`); section.setAttribute('aria-label', column.name);
    const items = tasks.filter(t => t.columnId === column.id);
    const header = el('div', 'column-heading'), heading = el('h2'), actions = el('div', 'column-actions');
    heading.append(el('span', 'status-dot'), document.createTextNode(column.name), el('span', 'count', items.length));
    actions.append(btn('✎', 'icon-button', () => openEditor('columns', column), `Renombrar ${column.name}`), btn('×', 'icon-button', run(() => deleteRecord('columns', column)), `Eliminar ${column.name}`));
    header.append(heading, actions); section.append(header, el('p', 'column-stage', state.stages[column.stage]));
    const list = el('div', 'task-list');
    for (const task of items) {
      const card = el('article', 'task-card'); card.draggable = true;
      card.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', task.id); e.dataTransfer.effectAllowed = 'move'; card.classList.add('dragging'); });
      card.addEventListener('dragend', () => { card.classList.remove('dragging'); document.querySelectorAll('.drag-over').forEach(n => n.classList.remove('drag-over')); });
      const meta = el('div', 'card-meta'); meta.append(el('span', `priority ${task.priority}`, priorities[task.priority]), btn('↗', 'icon-button', () => openEditor('tasks', task), `Editar ${task.title}`));
      card.append(meta, el('span', `record-folio type-${task.type}`, `${task.folio} · ${state.types[task.type].label}`), btn(task.title, 'task-title', () => openEditor('tasks', task)));
      const blockers = incompleteDependencies(task);
      if (blockers.length) card.append(el('p', 'blocked-note', `⛓ Pendiente de ${blockers.map(t => t.folio).join(', ')}`));
      if (task.type === 'change') card.append(el('p', 'approval-badge', `Aprobación: ${approvalLabel(task)}`));
      if (task.description) card.append(el('p', 'task-description', task.description));
      card.append(el('p', 'assignee', responsibleName(task)), taskMetrics(task));
      const bottom = el('div', 'card-bottom'), select = el('select', 'move-select');
      select.setAttribute('aria-label', `Mover ${task.title}`); columns().forEach(c => { const reason = transitionReason(task, c); const option = new Option(`${c.name}${reason ? ' · no disponible' : ''}`, c.id); option.disabled = !!reason; option.title = reason; select.add(option); }); select.value = task.columnId;
      select.addEventListener('change', run(async () => { try { await move(task, select.value); } finally { select.value = task.columnId; } }));
      bottom.append(el('span', 'task-type', state.types[task.type].label.toUpperCase()), select); card.append(bottom); list.append(card);
    }
    if (!items.length) { const empty = el('div', 'empty-column'); empty.append(el('span', 'empty-icon', '▤'), el('p', '', 'Espacio para lo que sigue'), el('small', '', 'Añade una tarea o arrástrala aquí.')); list.append(empty); }
    section.append(list, btn('＋ Nuevo registro', 'add-task', () => openEditor('tasks', null, { columnId: column.stage === 'pending' ? column.id : columns().find(c => c.stage === 'pending')?.id })));
    section.addEventListener('dragover', e => { e.preventDefault(); section.classList.add('drag-over'); });
    section.addEventListener('dragleave', e => { if (!section.contains(e.relatedTarget)) section.classList.remove('drag-over'); });
    section.addEventListener('drop', run(async e => { e.preventDefault(); section.classList.remove('drag-over'); const task = state.tasks.find(t => t.id === e.dataTransfer.getData('text/plain') && t.projectId === projectId); if (task) await move(task, column.id); }));
    $('#board').append(section);
  });
  if (projectId) $('#board').append(btn('＋ Nueva columna', 'add-column', () => openEditor('columns')));
  else $('#board').append(el('p', 'view-note', state.me.role === 'admin' ? 'Crea un proyecto para comenzar.' : 'Aún no tienes proyectos asignados.'));
}
function renderManagement() {
  const admin = state.me.role === 'admin';
  $('#management-note').textContent = admin ? 'Crea, edita y organiza los integrantes de tu espacio.' : 'La gestión de usuarios y grupos está disponible para administradores.';
  $('#management-list').replaceChildren();
  if (!admin) return;
  const table = el('table', 'records-table'), thead = el('thead'), header = el('tr');
  for (const label of page === 'users' ? ['Nombre', 'Correo', 'Rol', 'Grupos', 'Acciones'] : ['Grupo', 'Descripción', 'Integrantes', 'Acciones']) header.append(el('th', '', label));
  thead.append(header); table.append(thead); const tbody = el('tbody');
  for (const record of state[page]) {
    const row = el('tr');
    const values = page === 'users' ? [record.name, record.email, record.role === 'admin' ? 'Administrador' : 'Integrante', (record.groupIds || []).map(id => state.groups.find(g => g.id === id)?.name).filter(Boolean).join(', ') || 'Sin grupo'] : [record.name, record.description || '—', record.userIds.map(id => state.users.find(u => u.id === id)?.name).filter(Boolean).join(', ') || 'Sin integrantes'];
    values.forEach(value => row.append(el('td', '', value)));
    const actions = el('td', 'table-actions'); actions.append(btn('Editar', 'secondary', () => openEditor(page, record)), btn('Eliminar', 'danger', run(() => deleteRecord(page, record)))); row.append(actions); tbody.append(row);
  }
  table.append(tbody); $('#management-list').append(table);
  if (!state[page].length) $('#management-list').append(el('p', 'view-note', 'Todavía no hay registros. Crea el primero para comenzar.'));
}
function field(name, label, type = 'text', value = '', options = null, required = false) {
  const wrapper = el('label', '', label); let input;
  if (type === 'select') { input = el('select'); options.forEach(([id, text]) => input.add(new Option(text, id))); }
  else if (type === 'textarea') { input = el('textarea'); input.rows = 3; input.maxLength = 4000; }
  else { input = el('input'); input.type = type; input.maxLength = type === 'password' ? 256 : name === 'email' ? 254 : name === 'name' ? 60 : 140; }
  input.name = name; input.value = value ?? ''; input.required = required;
  if (type === 'password') { input.minLength = 10; input.autocomplete = 'new-password'; }
  wrapper.append(input); $('#editor-fields').append(wrapper); return input;
}
function checks(name, label, choices, selected) {
  const group = el('fieldset', 'checklist'); group.append(el('legend', '', label));
  if (!choices.length) group.append(el('p', 'view-note', 'No hay registros disponibles.'));
  choices.forEach(choice => { const row = el('label'), input = el('input'); input.type = 'checkbox'; input.name = name; input.value = choice.id; input.checked = selected.includes(choice.id); row.append(input, document.createTextNode(choice.name)); group.append(row); });
  $('#editor-fields').append(group);
}
function openEditor(kind, record = null, defaults = {}) {
  editor = { kind, record }; const data = record || defaults; $('#editor-fields').replaceChildren(); $('#editor-error').textContent = '';
  $('#editor-title').textContent = `${record ? 'Editar' : 'Crear'} ${names[kind]}`;
  $('#record-discussion').hidden = kind !== 'tasks' || !record;
  $('#delete-record').hidden = !record; $('#save-record').disabled = false;
  if (kind === 'tasks') {
    const typeInput = field('type', 'Tipo de registro', 'select', data.type || 'task', Object.entries(state.types).map(([key, value]) => [key, value.label]));
    typeInput.disabled = !!record;
    if (record) $('#editor-title').textContent = `${record.folio} · ${state.types[record.type].label}`;
    field('title', 'Título', 'text', data.title, null, true);
    field('description', 'Descripción', 'textarea', data.description);
    field('priority', 'Prioridad', 'select', data.priority || 'medium', Object.entries(priorities));
    const columnInput = field('columnId', 'Estatus / columna', 'select', data.columnId || columns().find(c => c.stage === 'pending')?.id, columns().map(c => [c.id, `${c.name} · ${state.stages[c.stage]}`]), true);
    const flowNote = el('div', 'flow-note'); $('#editor-fields').append(flowNote);
    const updateFlow = () => {
      const type = typeInput.value;
      for (const option of columnInput.options) {
        const column = columns().find(c => c.id === option.value);
        const reason = record ? transitionReason(record, column) : column.stage !== 'pending' ? 'Los registros nuevos comienzan en pendiente.' : '';
        option.disabled = !!reason; option.title = reason;
      }
      flowNote.replaceChildren(el('strong', '', 'Flujo de trabajo'));
      Object.entries(state.types[type].transitions).forEach(([from, targets]) => flowNote.append(el('small', '', `${state.stages[from]} → ${targets.map(t => state.stages[t]).join(' / ')}`)));
      if (type === 'change') flowNote.append(el('p', '', 'Se requiere aprobación de un administrador. Regresar a pendiente invalida la aprobación. Los datos aprobados se deben devolver a pendiente antes de modificarlos.'));
    };
    typeInput.addEventListener('change', updateFlow); updateFlow();
    const assign = field('assigneeId', 'Asignar a usuario o grupo', 'select', '', [['', 'Sin responsable']]);
    const availableUsers = state.me.role === 'admin' ? state.users : projectUsers();
    const availableGroups = state.groups.filter(g => state.me.role === 'admin' || currentProject().groupIds.includes(g.id));
    for (const [label, items] of [['Usuarios', availableUsers], ['Grupos', availableGroups]]) {
      const options = el('optgroup'); options.label = label;
      for (const item of items) {
        const group = label === 'Grupos';
        const linked = group ? currentProject().groupIds.includes(item.id) : currentProject().memberIds.includes(item.id);
        options.append(new Option(`${item.name}${linked ? '' : ' · se añadirá al proyecto'}`, group ? `group:${item.id}` : item.id));
      }
      assign.append(options);
    }
    assign.value = data.assigneeGroupId ? `group:${data.assigneeGroupId}` : data.assigneeId || '';
    $('#editor-fields').append(el('p', 'view-note', state.me.role === 'admin' ? 'Si eliges un usuario o grupo externo al proyecto, se le dará acceso al guardar. Un grupo asignado comparte la tarea entre sus integrantes.' : 'Puedes asignar usuarios y grupos vinculados al proyecto.'));
    const start = field('startAt', 'Fecha y hora de inicio', 'datetime-local', localInput(data.startAt));
    const end = field('endAt', 'Fecha y hora de fin', 'datetime-local', localInput(data.endAt));
    start.addEventListener('change', () => { end.min = start.value; }); end.min = start.value;
    $('#editor-fields').append(el('p', 'view-note', 'La duración activa es tiempo transcurrido entre inicio y fin, sin descontar pausas. Las fechas futuras representan planificación.'));
    const candidates = state.tasks.filter(t => t.projectId === projectId && t.id !== record?.id);
    checks('dependencyIds', 'Depende de · deben terminar antes de iniciar este registro', candidates.map(t => ({id: t.id, name: `${t.folio} · ${t.title}`})), data.dependencyIds || []);
    $('#editor-fields').append(el('p', 'view-note', 'Solo registros del mismo proyecto. Se rechazan ciclos. Las fechas se conservan; los solapamientos se señalan en el Gantt.'));
    if (record) {
      const successors = state.tasks.filter(t => t.dependencyIds.includes(record.id));
      if (successors.length) $('#editor-fields').append(el('p', 'view-note', `Este registro bloquea a: ${successors.map(t => `${t.folio} · ${t.title}`).join(', ')}`));
      $('#editor-fields').append(taskMetrics(record));
      const history = el('details', 'status-history'); history.append(el('summary', '', 'Historial de estatus'));
      for (const entry of record.statusHistory || []) history.append(el('p', '', `${state.columns.find(c => c.id === entry.columnId)?.name || 'Columna eliminada'} · ${dateText(entry.enteredAt)}`));
      $('#editor-fields').append(history);
    }
  } else {
    field('name', 'Nombre', 'text', data.name, null, true);
    if (kind === 'columns') { field('stage', 'Etapa del proceso', 'select', data.stage || 'progress', Object.entries(state.stages)); $('#editor-fields').append(el('p', 'view-note', 'El nombre es libre; la etapa determina las transiciones. Una columna ocupada no puede cambiar de etapa. Debe conservarse una columna por etapa.')); }
    if (kind === 'users') {
      field('email', 'Correo electrónico', 'email', data.email, null, true);
      field('role', 'Rol', 'select', data.role || 'member', [['member', 'Integrante'], ['admin', 'Administrador']]);
      checks('groupIds', 'Grupos a los que pertenece', state.groups, data.groupIds || []);
      field('password', record ? 'Nueva contraseña (deja vacío para conservarla)' : 'Contraseña (mínimo 10 caracteres)', 'password', '', null, !record);
    }
    if (kind === 'groups' || kind === 'projects') {
      field('description', 'Descripción', 'textarea', data.description);
      checks('userIds', kind === 'groups' ? 'Integrantes del grupo' : 'Integrantes directos del proyecto', state.users, data.userIds || []);
      if (kind === 'projects') checks('groupIds', 'Grupos con acceso al proyecto', state.groups, data.groupIds || []);
    }
  }
  editorSnapshot = JSON.stringify([...new FormData($('#editor-form'))]);
  if (kind === 'tasks' && record) renderDiscussion();
  if (!$('#editor').open) $('#editor').showModal(); $('#editor-fields input')?.focus();
}
async function deleteRecord(kind, record) {
  const suffix = kind === 'users' ? ' Se retirará de grupos, proyectos y asignaciones.' : kind === 'groups' ? ' Se retirará su acceso a los proyectos.' : '';
  if (!confirm(`¿Eliminar ${names[kind]} «${record.name || record.title}»?${suffix}`)) return;
  await command(kind, 'delete', { id: record.id }); if ($('#editor').open) $('#editor').close(); notify('Registro eliminado.');
}
function renderSchedule() {
  $('#calendar-section').hidden = !$('#show-calendar').checked; $('#gantt-section').hidden = !$('#show-gantt').checked;
  if ($('#show-calendar').checked) renderCalendar();
  if ($('#show-gantt').checked) renderGantt();
}
function undated(container, tasks) {
  container.replaceChildren(); const missing = tasks.filter(t => !t.startAt);
  if (!missing.length) return;
  container.append(el('strong', '', `Sin fecha de inicio (${missing.length}): `));
  missing.forEach(task => container.append(btn(task.title, 'undated-task', () => openEditor('tasks', task))));
}
function renderCalendar() {
  const tasks = visibleTasks(), calendar = $('#calendar'); calendar.replaceChildren();
  $('#calendar-month').textContent = month.toLocaleDateString('es-MX', { month: 'long', year: 'numeric' });
  ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'].forEach(day => calendar.append(el('div', 'calendar-weekday', day)));
  const first = new Date(month.getFullYear(), month.getMonth(), 1); first.setDate(first.getDate() - (first.getDay() + 6) % 7);
  for (let i = 0; i < 42; i++) {
    const date = new Date(first); date.setDate(first.getDate() + i);
    const cell = el('div', `calendar-cell${date.getMonth() !== month.getMonth() ? ' outside' : ''}${dayKey(date) === dayKey(new Date()) ? ' today' : ''}`);
    cell.append(el('span', 'calendar-day', date.getDate()));
    for (const task of tasks.filter(t => taskOnDay(t, date))) {
      const event = btn(`${task.folio} · ${task.title}`, `calendar-event ${task.priority}`, () => openEditor('tasks', task)); event.title = `${task.folio} · ${task.title}\n${dateText(task.startAt)} — ${dateText(task.endAt)}`; cell.append(event);
    }
    calendar.append(cell);
  }
  undated($('#calendar-undated'), tasks);
}
function ordinalDate(ordinal) { const d = new Date(ordinal * 86400000); return new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); }
function renderGantt() {
  const tasks = visibleTasks(), scheduled = dependencyOrder(tasks.filter(t => t.startAt).sort((a, b) => a.startAt.localeCompare(b.startAt)));
  const container = $('#gantt'); container.replaceChildren(); $('#gantt-dependency-notes').replaceChildren(); undated($('#gantt-undated'), tasks);
  if (!scheduled.length) { container.append(el('p', 'view-note', 'Añade una fecha de inicio a una tarea para verla en la línea de tiempo.')); return; }
  const range = timeline(scheduled, $('#gantt-scale').value), unit = range.step === 7 ? 100 : 44;
  if (range.count > 4000) { container.append(el('p', 'view-note', 'El intervalo es demasiado amplio. Selecciona la escala de semanas o ajusta las fechas.')); return; }
  const grid = el('div', 'gantt-grid'); grid.style.width = `${220 + range.count * unit}px`;
  const heading = el('div', 'gantt-row gantt-header'); heading.append(el('div', 'gantt-label', 'Tarea / responsable'));
  const ticks = el('div', 'gantt-ticks');
  for (let i = 0; i < range.count; i++) { const d = ordinalDate(range.start + i * range.step); const tick = el('div', 'gantt-tick', d.toLocaleDateString('es-MX', { day: 'numeric', month: 'short' })); tick.style.width = `${unit}px`; ticks.append(tick); }
  heading.append(ticks); grid.append(heading);
  scheduled.forEach(task => {
    const row = el('div', 'gantt-row'); const label = btn(`${task.folio} · ${task.title}`, 'gantt-label', () => openEditor('tasks', task)); label.title = task.title;
    label.append(el('small', '', responsibleName(task)));
    const track = el('div', 'gantt-track'); track.style.backgroundSize = `${unit}px 100%`;
    const start = dayOrdinal(task.startAt), end = dayOrdinal(task.endAt || task.startAt);
    const bar = btn(`${task.title}${task.endAt ? '' : ' →'}`, `gantt-bar ${task.priority}${task.endAt ? '' : ' open-ended'}`, () => openEditor('tasks', task));
    bar.style.left = `${(start - range.start) / range.step * unit}px`; bar.style.width = `${Math.max(12, (end - start + 1) / range.step * unit)}px`;
    bar.title = `${task.title}\nInicio: ${dateText(task.startAt)}\nFin: ${dateText(task.endAt)}`; track.append(bar); row.append(label, track); grid.append(row);
  });
  const today = dayOrdinal(new Date());
  if (today >= range.start && today <= range.end) { const line = el('div', 'gantt-today'); line.style.left = `${220 + (today - range.start) / range.step * unit}px`; line.title = 'Hoy'; grid.append(line); }
  renderGanttLinks(grid, scheduled, range, unit, tasks);
  container.append(grid);
}
function renderGanttLinks(grid, scheduled, range, unit, visible) {
  const ns = 'http://www.w3.org/2000/svg';
  const svgNode = (tag, attrs) => { const node = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value))); return node; };
  const width = range.count * unit, height = 42 + scheduled.length * 56;
  const svg = svgNode('svg', {width, height, class: 'dependency-svg', 'aria-hidden': 'true'}), defs = svgNode('defs', {});
  for (const [id, color] of [['normal', '#6d8c5c'], ['conflict', '#ba6c54']]) {
    const marker = svgNode('marker', {id: `arrow-${id}`, viewBox:'0 0 10 10', refX:9, refY:5, markerWidth:6, markerHeight:6, orient:'auto-start-reverse'});
    marker.append(svgNode('path', {d:'M 0 0 L 10 5 L 0 10 z', fill:color})); defs.append(marker);
  }
  svg.append(defs);
  const links = dependencyLinks(scheduled, range, unit), notes = $('#gantt-dependency-notes');
  for (const link of links) {
    const mid = link.x2 > link.x1 + 20 ? (link.x1 + link.x2) / 2 : Math.max(link.x1, link.x2) + 14;
    const route = link.x2 > link.x1 + 20
      ? `M ${link.x1} ${link.y1} H ${mid} V ${link.y2} H ${link.x2}`
      : `M ${link.x1} ${link.y1} H ${mid} V ${link.y2 - 20} H ${Math.max(1, link.x2 - 10)} V ${link.y2} H ${link.x2}`;
    const path = svgNode('path', {d: route, fill:'none', stroke:link.conflict ? '#ba6c54' : '#6d8c5c', 'stroke-width':1.5, 'stroke-dasharray':link.unknown ? '4 3' : 'none', 'marker-end':`url(#arrow-${link.conflict ? 'conflict' : 'normal'})`, class:'dependency-link'});
    svg.append(path);
  }
  const shown = new Set(scheduled.map(t => t.id));
  for (const task of visible) for (const id of task.dependencyIds) {
    const predecessor = state.tasks.find(t => t.id === id); if (!predecessor) continue;
    const conflict = task.startAt && predecessor.endAt && new Date(task.startAt) < new Date(predecessor.endAt);
    const missing = !shown.has(id) || !shown.has(task.id);
    notes.append(el('p', conflict ? 'dependency-warning' : '', `${predecessor.folio} → ${task.folio}${conflict ? ' · Las fechas planificadas se solapan.' : ''}${missing ? ' · Conexión fuera de la vista: faltan fechas o el registro está filtrado.' : ''}${!predecessor.endAt ? ' · El predecesor no tiene fin definido.' : ''}`));
  }
  grid.append(svg);
}
$('#comment-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = $('#post-comment'); button.disabled = true;
  try { const body = new FormData(event.target).get('body'); await command('tasks', 'comment', {id: editor.record.id, body}); event.target.reset(); renderDiscussion(); notify('Comentario publicado.'); }
  catch (error) { notify(error.message); } finally { button.disabled = false; }
});
$('#auth-form').addEventListener('submit', async e => {
  e.preventDefault(); $('#auth-error').textContent = ''; $('#auth-submit').disabled = true;
  try { await api(needsSetup ? 'setup' : 'login', Object.fromEntries(new FormData(e.currentTarget))); e.target.reset(); await refresh(); }
  catch (error) { $('#auth-error').textContent = error.message; } finally { $('#auth-submit').disabled = false; }
});
$('#logout').addEventListener('click', run(async () => { await api('logout', {}); showAuth(); await start(); }));
$('#refresh').addEventListener('click', run(refresh));
$('#create-main').addEventListener('click', () => openEditor(page === 'board' ? 'tasks' : page));
$('#new-column').addEventListener('click', () => openEditor('columns'));
$('#new-project').addEventListener('click', () => openEditor('projects'));
$('#edit-project').addEventListener('click', () => openEditor('projects', currentProject()));
$('#delete-project').addEventListener('click', run(() => deleteRecord('projects', currentProject())));
$('#project-select').addEventListener('change', e => { projectId = e.target.value; render(); });
for (const selector of ['#search', '#type-filter', '#priority-filter', '#only-mine']) $(selector).addEventListener(selector === '#search' ? 'input' : 'change', () => { renderBoard(); renderSchedule(); });
function toggleViews(open) { $('#views-panel').hidden = !open; $('#toggle-views').setAttribute('aria-expanded', String(open)); }
$('#toggle-views').addEventListener('click', () => toggleViews($('#views-panel').hidden)); $('#close-views').addEventListener('click', () => toggleViews(false));
for (const id of ['show-calendar', 'show-gantt', 'gantt-scale']) $(`#${id}`).addEventListener('change', renderSchedule);
$('#prev-month').addEventListener('click', () => { month = new Date(month.getFullYear(), month.getMonth() - 1, 1); renderCalendar(); });
$('#next-month').addEventListener('click', () => { month = new Date(month.getFullYear(), month.getMonth() + 1, 1); renderCalendar(); });
$('#today-month').addEventListener('click', () => { month = new Date(new Date().getFullYear(), new Date().getMonth(), 1); renderCalendar(); });
document.querySelectorAll('[data-page]').forEach(node => node.addEventListener('click', () => { page = node.dataset.page; render(); }));
$('#close-editor').addEventListener('click', () => $('#editor').close()); $('#cancel-editor').addEventListener('click', () => $('#editor').close());
$('#delete-record').addEventListener('click', run(() => deleteRecord(editor.kind, editor.record)));
$('#editor-form').addEventListener('submit', async e => {
  e.preventDefault(); if (loading) return; loading = true; $('#save-record').disabled = true; $('#editor-error').textContent = '';
  try {
    const form = new FormData(e.currentTarget), data = Object.fromEntries(form), { kind, record } = editor;
    if (record) { data.id = record.id; if (kind === 'tasks') { data.expectedUpdatedAt = record.updatedAt; data.type = record.type; } }
    if (['groups', 'projects'].includes(kind)) data.userIds = form.getAll('userIds');
    if (['users', 'projects'].includes(kind)) data.groupIds = form.getAll('groupIds');
    if (kind === 'tasks') { data.dependencyIds = form.getAll('dependencyIds'); data.assigneeGroupId = data.assigneeId.startsWith('group:') ? data.assigneeId.slice(6) : null; if (data.assigneeGroupId) data.assigneeId = null; data.startAt = data.startAt ? new Date(data.startAt).toISOString() : null; data.endAt = data.endAt ? new Date(data.endAt).toISOString() : null; }
    if (['tasks', 'columns'].includes(kind)) data.projectId = projectId;
    await command(kind, 'save', data); $('#editor').close(); notify('Cambios guardados.');
  } catch (error) { $('#editor-error').textContent = error.message; } finally { loading = false; $('#save-record').disabled = false; }
});
$('#import-legacy').addEventListener('click', run(async () => {
  if (!confirm('¿Importar el tablero anterior como un proyecto nuevo? Las fechas antiguas no estaban registradas; se usarán las de la importación.')) return;
  const raw = localStorage.getItem(STORAGE_KEY); if (!raw) return;
  await api('import', JSON.parse(raw)); await refresh(); notify('Tablero importado. La copia del navegador se conserva.');
}));
setInterval(() => {
  if (!state) return;
  document.querySelectorAll('.live-active,.live-status').forEach(node => { const task = state.tasks.find(t => t.id === node.dataset.task); if (task) node.textContent = node.classList.contains('live-active') ? `Activa: ${activeDuration(task)}` : `En estatus: ${duration(task.statusSince)}`; });
}, 30000);
start();
