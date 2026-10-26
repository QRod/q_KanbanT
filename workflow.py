"""Reglas de proceso compartidas por API, migración e interfaz."""
STAGES = {'pending': 'Pendiente', 'approval': 'Aprobación', 'progress': 'En curso', 'review': 'Revisión', 'done': 'Terminado'}
TYPES = {
    'task': {'label': 'Tarea', 'prefix': 'TAR', 'transitions': {
        'pending': ['progress'], 'progress': ['pending', 'review'], 'review': ['progress', 'done'], 'done': ['progress']}},
    'incident': {'label': 'Incidente', 'prefix': 'INC', 'transitions': {
        'pending': ['progress'], 'progress': ['pending', 'review'], 'review': ['progress', 'done'], 'done': ['progress']}},
    'request': {'label': 'Solicitud', 'prefix': 'SOL', 'transitions': {
        'pending': ['review'], 'review': ['pending', 'progress'], 'progress': ['review', 'done'], 'done': ['review']}},
    'change': {'label': 'Cambio', 'prefix': 'CAM', 'transitions': {
        'pending': ['approval'], 'approval': ['pending', 'progress'], 'progress': ['pending', 'review'],
        'review': ['pending', 'progress', 'done'], 'done': ['pending']}}
}
DEFAULT_STAGES = ['pending', 'progress', 'review', 'done', 'approval']


def dependency_cycle(tasks, task_id, dependencies):
    """Recorrido iterativo: no limita la longitud por la recursión de Python."""
    edges = {t['id']: t.get('dependencyIds', []) for t in tasks}
    edges[task_id] = dependencies
    seen, stack = set(), list(dependencies)
    while stack:
        item = stack.pop()
        if item == task_id:
            return True
        if item not in seen:
            seen.add(item)
            stack.extend(edges.get(item, []))
    return False
