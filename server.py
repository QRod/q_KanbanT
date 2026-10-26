"""Servidor local de q_KanbanT: API, sesiones y SQLite, sin dependencias externas."""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from workflow import STAGES, TYPES, DEFAULT_STAGES, dependency_cycle

ROOT = Path(__file__).resolve().parent
DEFAULT_COLUMNS = ['Por hacer', 'En progreso', 'En revisión', 'Hecho', 'Por aprobar']


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def uid():
    return secrets.token_hex(16)


def text(value, name, limit=140, required=True):
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise Problem(f'El campo {name} es obligatorio y admite hasta {limit} caracteres.')
    return value.strip()


def timestamp(value):
    if value in (None, ''):
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError()
        return date.astimezone(timezone.utc).isoformat(timespec='milliseconds')
    except (ValueError, TypeError, AttributeError):
        raise Problem('Fecha inválida; debe incluir zona horaria.')


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise Problem('La contraseña debe tener entre 10 y 256 caracteres.')
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'{salt}:{digest}'


def public(user):
    return {k: v for k, v in user.items() if k != 'passwordHash'}


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS counters (kind TEXT PRIMARY KEY, value INTEGER NOT NULL);
            ''')
        self.migrate()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    def all(self, db, kind):
        return [json.loads(row[0]) for row in db.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid', (kind,))]

    def get(self, db, kind, record_id):
        row = db.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, record_id)).fetchone()
        if not row:
            raise Problem('El registro ya no existe. Actualiza la página.', 404)
        return json.loads(row[0])

    def put(self, db, kind, record):
        db.execute('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data',
                   (kind, record['id'], json.dumps(record, ensure_ascii=False)))

    def remove(self, db, kind, record_id):
        db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, record_id))

    def next_folio(self, db, record_type):
        db.execute('INSERT INTO counters VALUES(?,1) ON CONFLICT(kind) DO UPDATE SET value=value+1', (record_type,))
        number = db.execute('SELECT value FROM counters WHERE kind=?', (record_type,)).fetchone()[0]
        return f'{TYPES[record_type]["prefix"]}-{number:06d}'

    def ensure_project_stages(self, db, project_id):
        columns = [c for c in self.all(db, 'columns') if c['projectId'] == project_id]
        missing = set(STAGES) - {c['stage'] for c in columns}
        position = max((c['position'] for c in columns), default=-1)
        for index, stage in enumerate(DEFAULT_STAGES):
            if stage in missing:
                position += 1
                self.put(db, 'columns', {'id': uid(), 'projectId': project_id, 'name': DEFAULT_COLUMNS[index], 'position': position, 'stage': stage})

    def migrate(self):
        with sqlite3.connect(self.path) as source:
            if source.execute('PRAGMA user_version').fetchone()[0] >= 3:
                return
            if source.execute("SELECT COUNT(*) FROM records WHERE kind='tasks'").fetchone()[0]:
                backup_path = Path(self.path).parent / 'backups' / f'pre-v03-{uid()}.sqlite3'
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(backup_path) as backup:
                    source.backup(backup)
        with self.connection() as db:
            for column in self.all(db, 'columns'):
                if 'stage' not in column:
                    column['stage'] = DEFAULT_STAGES[column['position']] if column['position'] in range(4) else 'pending'
                    self.put(db, 'columns', column)
            for project in self.all(db, 'projects'):
                self.ensure_project_stages(db, project['id'])
            for task in self.all(db, 'tasks'):
                task.setdefault('type', 'task')
                task.setdefault('folio', self.next_folio(db, task['type']))
                task.setdefault('approval', {'status': 'pending'})
                task.setdefault('assigneeGroupId', None)
                task.setdefault('dependencyIds', [])
                self.put(db, 'tasks', task)
                self.audit(db, None, task, 'migrated')
            db.execute('PRAGMA user_version=3')

    def audit(self, db, actor, task, action, changes=None):
        if action == 'updated' and not changes:
            return
        self.put(db, 'activity', {'id': uid(), 'projectId': task['projectId'], 'taskId': task['id'],
                                 'folio': task['folio'], 'title': task['title'], 'action': action,
                                 'actorId': actor['id'] if actor else None,
                                 'actorName': actor['name'] if actor else 'Sistema',
                                 'createdAt': now(), 'changes': changes or []})

    def task_changes(self, db, before, after):
        fields = {'title': 'Título', 'description': 'Descripción', 'priority': 'Prioridad', 'columnId': 'Estatus',
                  'assigneeId': 'Usuario responsable', 'assigneeGroupId': 'Grupo responsable', 'startAt': 'Inicio',
                  'endAt': 'Fin', 'dependencyIds': 'Dependencias', 'approval': 'Aprobación'}
        def readable(field, value):
            kind = {'columnId': 'columns', 'assigneeId': 'users', 'assigneeGroupId': 'groups'}.get(field)
            if kind and value:
                try:
                    return self.get(db, kind, value)['name']
                except Problem:
                    return 'Registro eliminado'
            if field == 'dependencyIds':
                return ', '.join(self.get(db, 'tasks', task_id)['folio'] for task_id in (value or [])) or 'Ninguna'
            if field == 'approval':
                return {'pending': 'Pendiente', 'approved': 'Aprobado', 'rejected': 'Rechazado'}.get((value or {}).get('status'), 'Pendiente')
            if field == 'priority':
                return {'high': 'Alta', 'medium': 'Media', 'low': 'Baja'}.get(value, value)
            return value if value not in (None, '') else 'Sin definir'
        return [{'field': field, 'label': label, 'before': readable(field, before.get(field)), 'after': readable(field, after.get(field))}
                for field, label in fields.items() if before.get(field) != after.get(field)]

    def execution_stages(self, record_type):
        return ('progress', 'done') if record_type == 'request' else ('progress', 'review', 'done')

    def validate_dependencies(self, db, task, target_stage):
        if target_stage not in self.execution_stages(task['type']):
            return
        blocked = []
        for dependency_id in task.get('dependencyIds', []):
            dependency = self.get(db, 'tasks', dependency_id)
            if self.get(db, 'columns', dependency['columnId'])['stage'] != 'done':
                blocked.append(dependency['folio'])
        if blocked:
            raise Problem(f'Primero deben terminar las dependencias: {", ".join(blocked)}.')

    def validate_transition(self, db, task, target, dependencies=None):
        source = self.get(db, 'columns', task['columnId'])
        start, end = source['stage'], target['stage']
        if start != end and end not in TYPES[task['type']]['transitions'].get(start, []):
            raise Problem(f'Transición no permitida para {TYPES[task["type"]]["label"]}: {STAGES[start]} → {STAGES[end]}.')
        if task['type'] == 'change' and end in ('progress', 'review', 'done') and task.get('approval', {}).get('status') != 'approved':
            raise Problem('El cambio requiere aprobación de un administrador antes de ejecutarse.')
        self.validate_dependencies(db, {**task, 'dependencyIds': dependencies if dependencies is not None else task.get('dependencyIds', [])}, end)
        if start == 'done' and end != 'done':
            for successor in self.all(db, 'tasks'):
                if task['id'] in successor.get('dependencyIds', []) and self.get(db, 'columns', successor['columnId'])['stage'] in self.execution_stages(successor['type']):
                    raise Problem(f'No se puede reabrir: {successor["folio"]} depende de este registro y ya está en ejecución o terminado.')

    def task_action(self, db, user, task, action, data):
        if action == 'comment':
            body = text(data.get('body'), 'comentario', 4000)
            self.put(db, 'comments', {'id': uid(), 'projectId': task['projectId'], 'taskId': task['id'],
                                      'authorId': user['id'], 'authorName': user['name'], 'createdAt': now(), 'body': body})
            self.audit(db, user, task, 'commented')
            return
        if user['role'] != 'admin':
            raise Problem('Solo un administrador puede aprobar o rechazar cambios.', 403)
        if data.get('expectedUpdatedAt') != task['updatedAt']:
            raise Problem('El cambio fue modificado. Actualiza y revisa sus datos antes de decidir.', 409)
        if task['type'] != 'change' or self.get(db, 'columns', task['columnId'])['stage'] != 'approval':
            raise Problem('El cambio debe estar en una columna de aprobación.')
        if task.get('approval', {}).get('status') != 'pending':
            raise Problem('La decisión ya fue registrada. Regresa el cambio a pendiente para solicitar otra revisión.', 409)
        reason = text(data.get('reason'), 'motivo de la decisión', 2000)
        before = dict(task)
        task['approval'] = {'status': 'approved' if action == 'approve' else 'rejected', 'actorId': user['id'],
                            'actorName': user['name'], 'decidedAt': now(), 'reason': reason}
        task['updatedAt'] = now()
        self.put(db, 'tasks', task)
        self.audit(db, user, task, action, self.task_changes(db, before, task))

    def invalidate_approval(self, db, task):
        if task['type'] == 'change' and task.get('approval', {}).get('status') == 'approved':
            # Una baja administrativa no revierte trabajo ya terminado ni sus sucesores.
            if self.get(db, 'columns', task['columnId'])['stage'] == 'done':
                return
            task['approval'] = {'status': 'pending'}
            pending = next(c for c in self.all(db, 'columns') if c['projectId'] == task['projectId'] and c['stage'] == 'pending')
            if task['columnId'] != pending['id']:
                task['columnId'], task['statusSince'] = pending['id'], now()
                task['statusHistory'].append({'columnId': pending['id'], 'enteredAt': task['statusSince']})

    def authenticated(self, db, token):
        row = db.execute('SELECT user_id FROM sessions WHERE token=? AND expires>?', (token, time.time())).fetchone()
        if not row:
            raise Problem('Inicia sesión para continuar.', 401)
        return self.get(db, 'users', row[0])

    def login(self, db, data, setup=False):
        if setup:
            if self.all(db, 'users'):
                raise Problem('Ya existe un administrador.', 409)
            user = self.save_user(db, None, {**data, 'role': 'admin'})
            project = {'id': uid(), 'name': 'Mi primer proyecto', 'description': '', 'userIds': [user['id']], 'groupIds': [], 'createdAt': now()}
            self.put(db, 'projects', project)
            self.seed_columns(db, project['id'])
        else:
            email = str(data.get('email', '')).strip().lower()
            user = next((u for u in self.all(db, 'users') if u['email'] == email), None)
            try:
                candidate = password_hash(data.get('password'), user['passwordHash'].split(':')[0] if user else None)
            except Problem:
                candidate = ''
            if not user or not hmac.compare_digest(candidate, user['passwordHash']):
                raise Problem('Correo o contraseña incorrectos.', 401)
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires <= ?', (time.time(),))
        db.execute('INSERT INTO sessions VALUES(?,?,?)', (token, user['id'], time.time() + 43200))
        return token

    def seed_columns(self, db, project_id):
        for index, name in enumerate(DEFAULT_COLUMNS):
            self.put(db, 'columns', {'id': uid(), 'projectId': project_id, 'name': name, 'position': index, 'stage': DEFAULT_STAGES[index]})

    def project_members(self, db, project):
        members = set(project['userIds'])
        for group in self.all(db, 'groups'):
            if group['id'] in project['groupIds']:
                members.update(group['userIds'])
        return members

    def allowed(self, db, user, project):
        return user['role'] == 'admin' or user['id'] in self.project_members(db, project)

    def state(self, db, user):
        projects = [p for p in self.all(db, 'projects') if self.allowed(db, user, p)]
        project_ids = {p['id'] for p in projects}
        member_ids = {user['id']}
        for project in projects:
            member_ids.update(self.project_members(db, project))
            project['memberIds'] = sorted(self.project_members(db, project))
        groups = self.all(db, 'groups')
        users = [{**public(u), 'groupIds': [g['id'] for g in groups if u['id'] in g['userIds']]}
                 for u in self.all(db, 'users') if user['role'] == 'admin' or u['id'] in member_ids]
        return {'me': public(user), 'users': users,
                'groups': [g for g in groups if user['role'] == 'admin' or any(g['id'] in p['groupIds'] for p in projects)], 'projects': projects,
                'columns': [c for c in self.all(db, 'columns') if c['projectId'] in project_ids],
                'tasks': [t for t in self.all(db, 'tasks') if t['projectId'] in project_ids],
                'legacyImported': bool(self.all(db, 'imports')), 'types': TYPES, 'stages': STAGES,
                'comments': [c for c in self.all(db, 'comments') if c['projectId'] in project_ids],
                'activity': [e for e in self.all(db, 'activity') if e['projectId'] in project_ids]}

    def refs(self, db, data, field, kind):
        values = data.get(field, [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise Problem('Selección inválida.')
        existing = {r['id'] for r in self.all(db, kind)}
        if not set(values) <= existing:
            raise Problem('Una de las selecciones ya no existe.')
        return list(dict.fromkeys(values))

    def save_user(self, db, old, data, actor=None):
        group_ids = self.refs(db, data, 'groupIds', 'groups') if 'groupIds' in data else None
        email = text(data.get('email'), 'correo', 254).lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise Problem('Introduce un correo válido.')
        if any(u['email'] == email and u['id'] != (old or {}).get('id') for u in self.all(db, 'users')):
            raise Problem('Ese correo ya está registrado.', 409)
        role = data.get('role')
        if role not in ('admin', 'member'):
            raise Problem('Rol inválido.')
        if old and old['role'] == 'admin' and role != 'admin':
            self.ensure_other_admin(db, old)
        record = {**(old or {'id': uid(), 'createdAt': now()}), 'name': text(data.get('name'), 'nombre'), 'email': email, 'role': role}
        if data.get('password') or not old:
            record['passwordHash'] = password_hash(data.get('password'))
        self.put(db, 'users', record)
        if group_ids is not None:
            for group in self.all(db, 'groups'):
                group['userIds'] = [i for i in group['userIds'] if i != record['id']]
                if group['id'] in group_ids:
                    group['userIds'].append(record['id'])
                self.put(db, 'groups', group)
            self.clean_assignments(db, actor)
        if old and data.get('password'):
            db.execute('DELETE FROM sessions WHERE user_id=?', (old['id'],))
        return record

    def clean_assignments(self, db, actor=None):
        for project in self.all(db, 'projects'):
            members = self.project_members(db, project)
            for task in self.all(db, 'tasks'):
                if task['projectId'] != project['id']:
                    continue
                before = dict(task)
                changed = False
                if task.get('assigneeId') and task['assigneeId'] not in members:
                    task['assigneeId'], changed = None, True
                if task.get('assigneeGroupId') and task['assigneeGroupId'] not in project['groupIds']:
                    task['assigneeGroupId'], changed = None, True
                if changed:
                    self.invalidate_approval(db, task)
                    task['updatedAt'] = now()
                    self.put(db, 'tasks', task)
                    self.audit(db, actor, task, 'updated', self.task_changes(db, before, task))

    def ensure_other_admin(self, db, user):
        if not any(u['role'] == 'admin' and u['id'] != user['id'] for u in self.all(db, 'users')):
            raise Problem('Debe permanecer al menos un administrador.')

    def command(self, db, user, body, importing=False):
        kind, action, data = body.get('kind'), body.get('action'), body.get('data', {})
        if kind not in ('users', 'groups', 'projects', 'columns', 'tasks') or action not in ('save', 'delete', 'move', 'comment', 'approve', 'reject') or not isinstance(data, dict):
            raise Problem('Operación inválida.')
        if kind in ('users', 'groups', 'projects') and user['role'] != 'admin':
            raise Problem('Solo un administrador puede gestionar estos registros.', 403)
        old = self.get(db, kind, data['id']) if data.get('id') else None
        if action == 'delete' and not old:
            raise Problem('Falta el registro a eliminar.')
        project = None
        if kind in ('tasks', 'columns'):
            project_id = old['projectId'] if old else data.get('projectId')
            project = self.get(db, 'projects', project_id)
            if not self.allowed(db, user, project):
                raise Problem('No tienes acceso a este proyecto.', 403)
            if old and data.get('projectId', project_id) != project_id:
                raise Problem('No se puede cambiar el proyecto del registro.')
        if action in ('comment', 'approve', 'reject'):
            if kind != 'tasks' or not old:
                raise Problem('La acción requiere un registro existente.')
            self.task_action(db, user, old, action, data)
            return
        if action == 'move':
            if kind != 'tasks' or not old:
                raise Problem('Solo se pueden mover tareas existentes.')
            column = self.get(db, 'columns', data.get('columnId'))
            if column['projectId'] != project['id']:
                raise Problem('La columna pertenece a otro proyecto.')
            self.validate_transition(db, old, column)
            if old['columnId'] != column['id']:
                before = dict(old)
                old['columnId'], old['statusSince'], old['updatedAt'] = column['id'], now(), now()
                if old['type'] == 'change' and column['stage'] == 'pending':
                    old['approval'] = {'status': 'pending'}
                old['statusHistory'].append({'columnId': column['id'], 'enteredAt': old['statusSince']})
                self.put(db, kind, old)
                self.audit(db, user, old, 'updated', self.task_changes(db, before, old))
            return
        if action == 'delete':
            self.delete(db, user, kind, old)
            return
        if kind == 'users':
            self.save_user(db, old, data, user)
            return
        record = {**(old or {'id': uid(), 'createdAt': now()})}
        if kind in ('groups', 'projects', 'columns'):
            record['name'] = text(data.get('name'), 'nombre', 60)
        if kind in ('groups', 'projects'):
            record['description'] = text(data.get('description', ''), 'descripción', 4000, False)
            record['userIds'] = self.refs(db, data, 'userIds', 'users')
        if kind == 'projects':
            record['groupIds'] = self.refs(db, data, 'groupIds', 'groups')
        if kind == 'columns':
            stage = data.get('stage', (old or {}).get('stage', 'progress'))
            if stage not in STAGES:
                raise Problem('Etapa de proceso inválida.')
            if old and old['stage'] != stage and any(t['columnId'] == old['id'] for t in self.all(db, 'tasks')):
                raise Problem('Vacía la columna antes de cambiar su etapa de proceso.')
            if old and old['stage'] != stage and not any(c['id'] != old['id'] and c['projectId'] == project['id'] and c['stage'] == old['stage'] for c in self.all(db, 'columns')):
                raise Problem('Debe existir al menos una columna para cada etapa. Crea otra antes de cambiar esta.')
            record['stage'] = stage
            record['projectId'] = project['id']
            record['position'] = old['position'] if old else 1 + max((c['position'] for c in self.all(db, 'columns') if c['projectId'] == project['id']), default=-1)
        if kind == 'tasks':
            if old and data.get('expectedUpdatedAt') and data['expectedUpdatedAt'] != old['updatedAt']:
                raise Problem('La tarea cambió mientras la editabas. Cierra el formulario y actualiza antes de volver a editar.', 409)
            record_type = data.get('type', (old or {}).get('type', 'task'))
            if record_type not in TYPES:
                raise Problem('Tipo de registro inválido.')
            if old and old['type'] != record_type:
                raise Problem('El tipo no se puede cambiar después de crear el registro.')
            record['type'] = record_type
            column = self.get(db, 'columns', data.get('columnId'))
            if column['projectId'] != project['id']:
                raise Problem('La columna pertenece a otro proyecto.')
            if not old and not importing and column['stage'] != 'pending':
                raise Problem('Los registros nuevos deben comenzar en una columna pendiente.')
            if data.get('priority') not in ('high', 'medium', 'low'):
                raise Problem('Prioridad inválida.')
            assignee = data.get('assigneeId') or None
            assignee_group = data.get('assigneeGroupId') or None
            if assignee and assignee_group:
                raise Problem('Selecciona un usuario o un grupo como responsable.')
            if assignee:
                self.get(db, 'users', assignee)
            if assignee_group:
                self.get(db, 'groups', assignee_group)
            if assignee and assignee not in self.project_members(db, project):
                if user['role'] != 'admin':
                    raise Problem('El responsable debe ser integrante del proyecto.', 403)
                project['userIds'].append(assignee)
                self.put(db, 'projects', project)
            if assignee_group and assignee_group not in project['groupIds']:
                if user['role'] != 'admin':
                    raise Problem('El grupo debe estar vinculado al proyecto.', 403)
                project['groupIds'].append(assignee_group)
                self.put(db, 'projects', project)
            start, end = timestamp(data.get('startAt')), timestamp(data.get('endAt'))
            if end and not start:
                raise Problem('Indica el inicio antes de establecer el fin.')
            if start and end and end < start:
                raise Problem('La fecha de fin no puede ser anterior al inicio.')
            status_changed = old is None or old['columnId'] != column['id']
            record.update(title=text(data.get('title'), 'título'), description=text(data.get('description', ''), 'descripción', 4000, False),
                          priority=data['priority'], projectId=project['id'], columnId=column['id'], assigneeId=assignee, assigneeGroupId=assignee_group,
                          startAt=start, endAt=end, updatedAt=now())
            if status_changed:
                record['statusSince'] = now()
                record['statusHistory'] = (old or {}).get('statusHistory', []) + [{'columnId': column['id'], 'enteredAt': record['statusSince']}]
            dependencies = self.refs(db, data, 'dependencyIds', 'tasks') if 'dependencyIds' in data else (old or {}).get('dependencyIds', [])
            for dependency_id in dependencies:
                dependency = self.get(db, 'tasks', dependency_id)
                if dependency['projectId'] != project['id']:
                    raise Problem('Las dependencias deben pertenecer al mismo proyecto.')
            if dependency_cycle(self.all(db, 'tasks'), record['id'], dependencies):
                raise Problem('La dependencia produciría un ciclo. Un registro no puede depender de sí mismo ni de sus sucesores.')
            record['dependencyIds'] = dependencies
            record.setdefault('approval', {'status': 'pending'})
            if old:
                significant = ['title', 'description', 'priority', 'assigneeId', 'assigneeGroupId', 'startAt', 'endAt', 'dependencyIds']
                if old['type'] == 'change' and old.get('approval', {}).get('status') == 'approved' and any(old.get(k) != record.get(k) for k in significant):
                    raise Problem('Regresa el cambio a una columna pendiente antes de modificarlo; requerirá una nueva aprobación.')
                self.validate_transition(db, old, column, dependencies)
                if record_type == 'change' and column['stage'] == 'pending' and status_changed:
                    record['approval'] = {'status': 'pending'}
            if column['stage'] in ('progress', 'review', 'done'):
                self.validate_dependencies(db, record, column['stage'])
            if not old:
                record['folio'] = self.next_folio(db, record_type)
                record['createdBy'] = user['id']
        self.put(db, kind, record)
        if kind == 'tasks':
            self.audit(db, user, record, 'updated' if old else 'created', self.task_changes(db, old, record) if old else [])
        if kind == 'projects' and not old:
            self.seed_columns(db, record['id'])
        if kind in ('projects', 'groups'):
            self.clean_assignments(db, user)

    def delete(self, db, user, kind, record):
        record_id = record['id']
        if kind == 'tasks':
            if any(record_id in t.get('dependencyIds', []) for t in self.all(db, 'tasks')):
                raise Problem('Retira las dependencias hacia este registro antes de eliminarlo.')
            self.audit(db, user, record, 'deleted')
        if kind == 'users':
            if user['id'] == record_id:
                raise Problem('No puedes eliminar tu propia cuenta.')
            if record['role'] == 'admin':
                self.ensure_other_admin(db, record)
            db.execute('DELETE FROM sessions WHERE user_id=?', (record_id,))
            for parent_kind in ('groups', 'projects'):
                for parent in self.all(db, parent_kind):
                    parent['userIds'] = [i for i in parent['userIds'] if i != record_id]
                    self.put(db, parent_kind, parent)
            for task in self.all(db, 'tasks'):
                if task['assigneeId'] == record_id:
                    before = dict(task)
                    task['assigneeId'], task['updatedAt'] = None, now()
                    self.invalidate_approval(db, task)
                    self.put(db, 'tasks', task)
                    self.audit(db, user, task, 'updated', self.task_changes(db, before, task))
        if kind == 'groups':
            for project in self.all(db, 'projects'):
                project['groupIds'] = [i for i in project['groupIds'] if i != record_id]
                self.put(db, 'projects', project)
            self.remove(db, kind, record_id)
            self.clean_assignments(db, user)
            return
        if kind == 'projects':
            if any(t['projectId'] == record_id for t in self.all(db, 'tasks')):
                raise Problem('El proyecto tiene tareas. Elimínalas antes de borrar el proyecto.')
            for column in self.all(db, 'columns'):
                if column['projectId'] == record_id:
                    self.remove(db, 'columns', column['id'])
        if kind == 'columns' and not any(c['id'] != record_id and c['projectId'] == record['projectId'] and c['stage'] == record['stage'] for c in self.all(db, 'columns')):
            raise Problem('Debe permanecer al menos una columna de cada etapa para completar los flujos.')
        if kind == 'columns' and any(t['columnId'] == record_id for t in self.all(db, 'tasks')):
            raise Problem('Mueve o elimina las tareas antes de borrar la columna.')
        self.remove(db, kind, record_id)

    def import_legacy(self, db, user, data):
        if user['role'] != 'admin':
            raise Problem('Solo un administrador puede importar.', 403)
        if self.all(db, 'imports'):
            raise Problem('El tablero anterior ya se importó.', 409)
        columns, tasks = data.get('columns'), data.get('tasks')
        if data.get('version') != 1 or not isinstance(columns, list) or not isinstance(tasks, list):
            raise Problem('Tablero anterior inválido.')
        if len(columns) > 200 or len(tasks) > 10000:
            raise Problem('El tablero excede el tamaño permitido.')
        project = {'id': uid(), 'name': 'Tablero anterior', 'description': 'Importado del navegador. Las fechas originales no estaban registradas.', 'userIds': [user['id']], 'groupIds': [], 'createdAt': now()}
        self.put(db, 'projects', project)
        mapping = {}
        for index, column in enumerate(columns):
            if not isinstance(column, dict) or not isinstance(column.get('id'), str) or column['id'] in mapping:
                raise Problem('Columnas inválidas en el tablero anterior.')
            column_id = uid()
            mapping[column['id']] = column_id
            self.put(db, 'columns', {'id': column_id, 'projectId': project['id'], 'name': text(column.get('name'), 'columna', 60), 'position': index, 'stage': DEFAULT_STAGES[index] if index < 4 else 'pending'})
        task_ids = set()
        for task in tasks:
            if not isinstance(task, dict) or task.get('columnId') not in mapping or not isinstance(task.get('id'), str) or task['id'] in task_ids:
                raise Problem('Tareas inválidas en el tablero anterior.')
            task_ids.add(task['id'])
            self.command(db, user, {'kind': 'tasks', 'action': 'save', 'data': {'projectId': project['id'], 'columnId': mapping[task['columnId']], 'title': task.get('title'), 'description': task.get('description', ''), 'priority': task.get('priority')}}, importing=True)
        self.ensure_project_stages(db, project['id'])
        self.put(db, 'imports', {'id': 'legacy', 'importedAt': now()})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith('/api/'):
            self.api()
            return
        path = urlsplit(self.path).path
        allowed = {'/', '/index.html', '/src/app.js', '/src/board.js', '/src/styles.css'}
        if path not in allowed:
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if urlsplit(self.path).path not in {'/', '/index.html', '/src/app.js', '/src/board.js', '/src/styles.css'}:
            self.send_error(404)
            return
        super().do_HEAD()

    def do_POST(self):
        self.api()

    def reply(self, data, status=200, cookie=None):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        if cookie is not None:
            secure = '; Secure' if os.environ.get('QKT_SECURE_COOKIE') == '1' else ''
            self.send_header('Set-Cookie', f'qkt_session={cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age={43200 if cookie else 0}{secure}')
        self.end_headers()
        self.wfile.write(raw)

    def api(self):
        try:
            body = {}
            if self.command == 'POST':
                if self.headers.get('X-QKT-Request') != '1' or self.headers.get_content_type() != 'application/json':
                    raise Problem('Solicitud no permitida.', 403)
                origin = self.headers.get('Origin')
                if origin and origin != os.environ.get('QKT_PUBLIC_ORIGIN', f'http://{self.headers.get("Host")}'):
                    raise Problem('Origen no permitido.', 403)
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 2_000_000:
                    raise Problem('Solicitud demasiado grande.', 413)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise Problem('Solicitud inválida.')
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookies['qkt_session'].value if 'qkt_session' in cookies else ''
            store = self.server.store
            cookie = None
            with store.connection() as db:
                if self.path == '/api/session' and self.command == 'GET':
                    result = {'needsSetup': not bool(store.all(db, 'users')), 'me': None}
                    try:
                        result['me'] = public(store.authenticated(db, token))
                    except Problem:
                        pass
                elif self.path in ('/api/login', '/api/setup') and self.command == 'POST':
                    if self.path == '/api/setup' and os.environ.get('QKT_DISABLE_WEB_SETUP') == '1':
                        raise Problem('Crea la primera cuenta mediante q-kanbant-admin en el servidor.', 403)
                    # Limita intentos fallidos por servidor local; se reinicia al arrancar.
                    cutoff = time.time() - 60
                    self.server.attempts = [t for t in self.server.attempts if t > cutoff]
                    if len(self.server.attempts) >= 20:
                        raise Problem('Demasiados intentos. Espera un minuto.', 429)
                    self.server.attempts.append(time.time())
                    cookie = store.login(db, body, self.path == '/api/setup')
                    result = {'ok': True}
                elif self.path == '/api/logout' and self.command == 'POST':
                    db.execute('DELETE FROM sessions WHERE token=?', (token,))
                    cookie, result = '', {'ok': True}
                else:
                    user = store.authenticated(db, token)
                    if self.path == '/api/state' and self.command == 'GET':
                        result = store.state(db, user)
                    elif self.path == '/api/command' and self.command == 'POST':
                        store.command(db, user, body)
                        result = {'ok': True}
                    elif self.path == '/api/import' and self.command == 'POST':
                        store.import_legacy(db, user, body)
                        result = {'ok': True}
                    else:
                        raise Problem('Ruta no encontrada.', 404)
            self.reply(result, cookie=cookie)
        except Problem as error:
            self.reply({'error': str(error)}, error.status)
        except (ValueError, TypeError, KeyError):
            self.reply({'error': 'Datos de solicitud inválidos.'}, 400)
        except Exception:
            self.log_error('Error interno al procesar la solicitud')
            self.reply({'error': 'No se pudo completar la operación.'}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5173)
    parser.add_argument('--database', default=os.environ.get('QKT_DATABASE', str(ROOT / '.data' / 'kanbant.sqlite3')))
    parser.add_argument('--create-admin', action='store_true')
    args = parser.parse_args()
    if args.create_admin:
        import getpass
        store = Store(args.database)
        with store.connection() as db:
            if store.all(db, 'users'): raise SystemExit('Ya existe una cuenta administradora; utiliza la interfaz para gestionar usuarios')
            name = input('Nombre del administrador: ').strip()
            email = input('Correo del administrador: ').strip()
            password = getpass.getpass('Contraseña (mínimo 10 caracteres): ')
            if password != getpass.getpass('Confirmar contraseña: '): raise SystemExit('Las contraseñas no coinciden')
            store.login(db, {'name': name, 'email': email, 'password': password}, True)
        print('Administrador creado')
        return
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.store = Store(args.database)
    server.attempts = []
    print(f'q_KanbanT disponible en http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
