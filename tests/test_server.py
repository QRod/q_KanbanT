import tempfile
import unittest
from pathlib import Path
from server import Store, Problem, password_hash


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'test.sqlite3')
        with self.store.connection() as db:
            self.token = self.store.login(db, {'name': 'Admin', 'email': 'admin@example.test', 'password': 'test-password-123'}, True)
            self.admin = self.store.authenticated(db, self.token)
            self.project = self.store.all(db, 'projects')[0]
            self.columns = self.store.all(db, 'columns')
            self.member = self.store.save_user(db, None, {'name': 'Ana', 'email': 'ana@example.test', 'password': 'member-password', 'role': 'member'})

    def tearDown(self):
        self.tmp.cleanup()

    def command(self, kind, data, action='save', user=None):
        with self.store.connection() as db:
            self.store.command(db, user or self.admin, {'kind': kind, 'action': action, 'data': data})

    def task(self, **extra):
        data = {'title': 'Tarea', 'description': 'Detalle', 'priority': 'medium', 'projectId': self.project['id'], 'columnId': self.columns[0]['id'], **extra}
        self.command('tasks', data)
        with self.store.connection() as db:
            return self.store.all(db, 'tasks')[-1]

    def test_login_hash_and_private_state(self):
        with self.store.connection() as db:
            self.assertNotIn('test-password-123', self.admin['passwordHash'])
            token = self.store.login(db, {'email': 'ana@example.test', 'password': 'member-password'})
            member = self.store.authenticated(db, token)
            state = self.store.state(db, member)
            self.assertEqual(state['projects'], [])
            self.assertNotIn('passwordHash', state['me'])
            with self.assertRaises(Problem):
                self.store.login(db, {'email': 'ana@example.test', 'password': 'incorrect-password'})
            with self.assertRaises(Problem):
                self.store.login(db, {}, True)

    def test_member_cannot_manage_users_or_unassigned_projects(self):
        with self.assertRaises(Problem) as error:
            self.command('groups', {'name': 'Equipo'}, user=self.member)
        self.assertEqual(error.exception.status, 403)
        with self.assertRaises(Problem):
            self.command('tasks', {'projectId': self.project['id']}, user=self.member)

    def test_group_membership_grants_access_and_assignment(self):
        self.command('groups', {'name': 'Soporte', 'userIds': [self.member['id']]})
        with self.store.connection() as db:
            group = self.store.all(db, 'groups')[0]
        self.command('projects', {**self.project, 'groupIds': [group['id']]})
        task = self.task(assigneeId=self.member['id'])
        with self.store.connection() as db:
            state = self.store.state(db, self.member)
            self.assertEqual(len(state['projects']), 1)
            self.assertIn(self.member['id'], state['projects'][0]['memberIds'])
            self.assertEqual(state['tasks'][0]['assigneeId'], self.member['id'])
        self.command('tasks', {'id': task['id'], 'columnId': self.columns[1]['id']}, 'move', self.member)
        self.command('groups', {'id': group['id']}, 'delete')
        with self.store.connection() as db:
            self.assertEqual(self.store.state(db, self.member)['projects'], [])
            self.assertIsNone(self.store.get(db, 'tasks', task['id'])['assigneeId'])

    def test_user_delete_cleans_relations_and_sessions(self):
        self.command('projects', {**self.project, 'userIds': [self.member['id']]})
        task = self.task(assigneeId=self.member['id'])
        self.command('users', {'id': self.member['id']}, 'delete')
        with self.store.connection() as db:
            self.assertEqual(self.store.get(db, 'projects', self.project['id'])['userIds'], [])
            self.assertIsNone(self.store.get(db, 'tasks', task['id'])['assigneeId'])
        with self.assertRaises(Problem):
            self.command('users', {'id': self.admin['id']}, 'delete')
        with self.assertRaises(Problem):
            self.command('users', {**self.admin, 'role': 'member'})

    def test_task_dates_assignment_and_cross_project_validation(self):
        for dates in [{'endAt': '2026-10-25T10:00:00Z'}, {'startAt': 'bad'}, {'startAt': '2026-10-25T10:00:00Z', 'endAt': '2026-10-24T10:00:00Z'}]:
            with self.assertRaises(Problem):
                self.task(**dates)
        self.command('projects', {'name': 'Otro', 'userIds': [], 'groupIds': []})
        with self.store.connection() as db:
            other_column = self.store.all(db, 'columns')[-1]
        with self.assertRaises(Problem):
            self.task(columnId=other_column['id'])
        task = self.task(startAt='2026-10-24T12:00:00-06:00', endAt='2026-10-24T14:00:00-06:00')
        self.assertEqual(task['startAt'], '2026-10-24T18:00:00.000+00:00')
        self.assertEqual(task['dependencyIds'], [])

    def test_move_changes_status_history_but_preserves_creation_and_dates(self):
        task = self.task(startAt='2026-10-24T10:00:00Z')
        self.command('tasks', {'id': task['id'], 'columnId': self.columns[1]['id']}, 'move')
        with self.store.connection() as db:
            moved = self.store.get(db, 'tasks', task['id'])
        self.assertEqual(moved['createdAt'], task['createdAt'])
        self.assertEqual(moved['startAt'], task['startAt'])
        self.assertEqual(len(moved['statusHistory']), 2)
        self.command('tasks', {'id': task['id'], 'columnId': self.columns[1]['id']}, 'move')
        with self.store.connection() as db:
            self.assertEqual(len(self.store.get(db, 'tasks', task['id'])['statusHistory']), 2)
        self.command('tasks', {**moved, 'title': 'Editada'})
        with self.store.connection() as db:
            self.assertEqual(self.store.get(db, 'tasks', task['id'])['statusSince'], moved['statusSince'])
        with self.assertRaises(Problem) as error:
            self.command('tasks', {**moved, 'expectedUpdatedAt': 'old'})
        self.assertEqual(error.exception.status, 409)

    def test_delete_populated_column_or_project_rejected(self):
        self.task()
        with self.assertRaises(Problem):
            self.command('columns', {'id': self.columns[0]['id']}, 'delete')
        with self.assertRaises(Problem):
            self.command('projects', {'id': self.project['id']}, 'delete')

    def test_import_preserves_legacy_tasks_and_is_atomic(self):
        legacy = {'version': 1, 'columns': [{'id': 'old', 'name': 'Pendientes'}], 'tasks': [{'id': 'old-task', 'columnId': 'old', 'title': 'Anterior', 'priority': 'high', 'description': 'Conservar'}]}
        with self.store.connection() as db:
            self.store.import_legacy(db, self.admin, legacy)
        with self.store.connection() as db:
            self.assertEqual(self.store.all(db, 'tasks')[0]['description'], 'Conservar')
            self.assertTrue(self.store.state(db, self.admin)['legacyImported'])
            with self.assertRaises(Problem):
                self.store.import_legacy(db, self.admin, legacy)

    def test_failed_import_rolls_back_and_db_survives_reopen(self):
        with self.assertRaises(Problem):
            with self.store.connection() as db:
                self.store.import_legacy(db, self.admin, {'version': 1, 'columns': [{'id': 'a', 'name': 'OK'}], 'tasks': [{'id': 't', 'columnId': 'missing'}]})
        reopened = Store(self.store.path)
        with reopened.connection() as db:
            self.assertEqual(len(reopened.all(db, 'projects')), 1)
            self.assertEqual(reopened.all(db, 'imports'), [])

    def test_duplicate_email_and_short_password_rejected(self):
        with self.assertRaises(Problem):
            self.command('users', {'name': 'Otro', 'email': self.member['email'], 'password': 'long-password', 'role': 'member'})
        with self.assertRaises(Problem):
            password_hash('short')

    def test_user_groups_can_be_edited_from_both_sides(self):
        self.command('groups', {'name': 'Operaciones', 'userIds': []})
        with self.store.connection() as db:
            group = self.store.all(db, 'groups')[0]
        self.command('users', {**self.member, 'groupIds': [group['id']]})
        with self.store.connection() as db:
            self.assertIn(self.member['id'], self.store.get(db, 'groups', group['id'])['userIds'])
            member = next(u for u in self.store.state(db, self.admin)['users'] if u['id'] == self.member['id'])
            self.assertEqual(member['groupIds'], [group['id']])
        self.command('groups', {**group, 'userIds': []})
        with self.store.connection() as db:
            member = next(u for u in self.store.state(db, self.admin)['users'] if u['id'] == self.member['id'])
            self.assertEqual(member['groupIds'], [])

    def test_admin_assignment_links_user_or_group_to_project(self):
        individual = self.task(assigneeId=self.member['id'])
        with self.store.connection() as db:
            self.assertIn(self.member['id'], self.store.get(db, 'projects', self.project['id'])['userIds'])
        self.command('groups', {'name': 'Equipo', 'userIds': [self.member['id']]})
        with self.store.connection() as db:
            group = self.store.all(db, 'groups')[0]
        shared = self.task(assigneeGroupId=group['id'])
        self.assertIsNone(shared['assigneeId'])
        with self.store.connection() as db:
            self.assertIn(group['id'], self.store.get(db, 'projects', self.project['id'])['groupIds'])
            self.assertEqual(self.store.state(db, self.member)['groups'][0]['id'], group['id'])
        self.command('groups', {'id': group['id']}, 'delete')
        with self.store.connection() as db:
            self.assertIsNone(self.store.get(db, 'tasks', shared['id'])['assigneeGroupId'])
            self.assertEqual(self.store.get(db, 'tasks', individual['id'])['assigneeId'], self.member['id'])

    def test_member_cannot_grant_project_access_through_assignment(self):
        self.command('projects', {**self.project, 'userIds': [self.member['id']]})
        self.command('groups', {'name': 'Externo', 'userIds': []})
        with self.store.connection() as db:
            group = self.store.all(db, 'groups')[0]
        base = {'projectId': self.project['id'], 'columnId': self.columns[0]['id'], 'title': 'No autorizado', 'priority': 'low'}
        for assignment in [{'assigneeGroupId': group['id']}, {'assigneeId': self.admin['id']}]:
            with self.assertRaises(Problem) as error:
                self.command('tasks', {**base, **assignment}, user=self.member)
            self.assertEqual(error.exception.status, 403)
        with self.assertRaises(Problem):
            self.task(assigneeId=self.member['id'], assigneeGroupId=group['id'])
