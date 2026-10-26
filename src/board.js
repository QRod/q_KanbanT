export const STORAGE_KEY = 'q-kanbant.board.v1';
export const priorities = { high: 'Alta', medium: 'Media', low: 'Baja' };
export const uid = () => crypto.randomUUID();
export function initialBoard() {
  return { version: 1, columns: [
    { id: 'pending', name: 'Por hacer' },
    { id: 'progress', name: 'En progreso' },
    { id: 'review', name: 'En revisión' },
    { id: 'done', name: 'Hecho' }
  ], tasks: [] };
}
export function validBoard(board) {
  if (!board || board.version !== 1 || !Array.isArray(board.columns) || !Array.isArray(board.tasks)) return false;
  const ids = new Set();
  for (const column of board.columns) {
    if (!column || typeof column.id !== 'string' || ids.has(column.id) || typeof column.name !== 'string' || !column.name.trim()) return false;
    ids.add(column.id);
  }
  const taskIds = new Set();
  return board.tasks.every(task => {
    if (!task || typeof task.id !== 'string' || taskIds.has(task.id) || !ids.has(task.columnId) || typeof task.title !== 'string' || !task.title.trim() || typeof task.description !== 'string' || !Object.hasOwn(priorities, task.priority)) return false;
    taskIds.add(task.id);
    return true;
  });
}
export function moveTask(board, taskId, columnId) {
  const task = board.tasks.find(item => item.id === taskId);
  if (!task || !board.columns.some(column => column.id === columnId)) return false;
  task.columnId = columnId;
  return true;
}

// El servidor usa ISO-8601 UTC. La presentación siempre usa la zona del navegador.
export function duration(from, to = Date.now()) {
  if (!from) return 'Sin iniciar';
  const ms = new Date(to).getTime() - new Date(from).getTime();
  if (!Number.isFinite(ms)) return '—';
  if (ms < 0) return 'Por iniciar';
  const minutes = Math.floor(ms / 60000);
  if (!minutes) return '< 1 min';
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor(minutes % 1440 / 60);
  return [days ? `${days} d` : '', hours ? `${hours} h` : '', `${minutes % 60} min`].filter(Boolean).join(' ');
}
export function activeDuration(task, clock = Date.now()) {
  return duration(task.startAt, task.endAt ? Math.min(new Date(task.endAt).getTime(), clock) : clock);
}
export function localInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
export function dayKey(date) {
  return localInput(date).slice(0, 10);
}
export function dayOrdinal(date) {
  const d = new Date(date);
  return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86400000;
}
export function taskOnDay(task, date) {
  if (!task.startAt) return false;
  const day = dayOrdinal(date);
  return day >= dayOrdinal(task.startAt) && day <= dayOrdinal(task.endAt || task.startAt);
}
export function timeline(tasks, scale = 'day') {
  const scheduled = tasks.filter(t => t.startAt);
  const today = dayOrdinal(new Date());
  const start = scheduled.length ? Math.min(...scheduled.map(t => dayOrdinal(t.startAt))) : today;
  const end = scheduled.length ? Math.max(...scheduled.map(t => dayOrdinal(t.endAt || t.startAt))) : today + 13;
  const step = scale === 'week' ? 7 : 1;
  return { start, end: Math.max(end, start + 13), step, count: Math.ceil((Math.max(end, start + 13) - start + 1) / step) };
}

export function dependencyOrder(tasks) {
  const byId = new Map(tasks.map(task => [task.id, task]));
  const indegree = new Map(tasks.map(task => [task.id, (task.dependencyIds || []).filter(id => byId.has(id)).length]));
  const successors = new Map(tasks.map(task => [task.id, []]));
  for (const task of tasks) for (const id of task.dependencyIds || []) if (byId.has(id)) successors.get(id).push(task.id);
  const ready = tasks.filter(t => indegree.get(t.id) === 0), result = [];
  for (let i = 0; i < ready.length; i++) {
    const task = ready[i]; result.push(task);
    for (const id of successors.get(task.id)) { indegree.set(id, indegree.get(id) - 1); if (!indegree.get(id)) ready.push(byId.get(id)); }
  }
  return result.length === tasks.length ? result : tasks;
}
export function dependencyLinks(tasks, range, unit) {
  const index = new Map(tasks.map((task, row) => [task.id, row]));
  const links = [];
  for (const task of tasks) for (const id of task.dependencyIds || []) {
    if (!index.has(id)) continue;
    const predecessor = tasks[index.get(id)];
    links.push({ from: id, to: task.id,
      x1: (dayOrdinal(predecessor.endAt || predecessor.startAt) - range.start + 1) / range.step * unit,
      x2: (dayOrdinal(task.startAt) - range.start) / range.step * unit,
      y1: 42 + index.get(id) * 56 + 28, y2: 42 + index.get(task.id) * 56 + 28,
      conflict: !!predecessor.endAt && new Date(task.startAt) < new Date(predecessor.endAt),
      unknown: !predecessor.endAt });
  }
  return links;
}
