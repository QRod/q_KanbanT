import json
import sqlite3
import unittest
from pathlib import Path
import test_server
from server import Store, Problem
from workflow import dependency_cycle


class WorkflowTests(unittest.TestCase):
    setUp = test_server.StoreTests.setUp
    tearDown = test_server.StoreTests.tearDown
    command = test_server.StoreTests.command
    task = test_server.StoreTests.task

    def get(self, task):
        with self.store.connection() as db:
            return self.store.get(db, 'tasks', task['id'])

    def move(self, task, stage, user=None):
        column = next(c for c in self.columns if c['stage'] == stage)
        self.command('tasks', {'id': task['id'], 'columnId': column['id']}, 'move', user)
        return self.get(task)

    def finish(self, task):
        for stage in ['progress', 'review', 'done']:
            self.move(task, stage)
        return self.get(task)

    def decision(self, task, action='approve', user=None):
        task = self.get(task)
        self.command('tasks', {'id': task['id'], 'reason': 'Revisado y evaluado', 'expectedUpdatedAt': task['updatedAt']}, action, user)
        return self.get(task)

    def test_types_folios_are_immutable_unique_and_not_reused(self):
        first = self.task()
        self.assertEqual(first['folio'], 'TAR-000001')
        self.command('tasks', {'id': first['id']}, 'delete')
        second = self.task()
        self.assertEqual(second['folio'], 'TAR-000002')
        incident = self.task(type='incident')
        self.assertEqual(incident['folio'], 'INC-000001')
        self.assertEqual(self.task(type='request')['folio'], 'SOL-000001')
        self.assertEqual(self.task(type='change')['folio'], 'CAM-000001')
        with self.assertRaises(Problem):
            self.command('tasks', {**incident, 'type': 'task'})
        with self.assertRaises(Problem):
            self.task(type='unknown')
        self.command('tasks', {**second, 'folio': 'FORGED'})
        self.assertEqual(self.get(second)['folio'], 'TAR-000002')

    def test_workflow_cannot_be_skipped_by_move_save_or_create(self):
        task = self.task()
        with self.assertRaises(Problem):
            self.move(task, 'done')
        with self.assertRaises(Problem):
            self.command('tasks', {**task, 'columnId': self.columns[3]['id']})
        with self.assertRaises(Problem):
            self.task(columnId=self.columns[3]['id'])
        request = self.task(type='request')
        with self.assertRaises(Problem):
            self.move(request, 'progress')
        self.move(request, 'review')
        self.move(request, 'progress')
        self.move(request, 'done')

    def test_change_approval_roles_staleness_and_invalidation(self):
        self.command('projects', {**self.project, 'userIds': [self.member['id']]})
        change = self.task(type='change')
        with self.assertRaises(Problem):
            self.move(change, 'progress')
        change = self.move(change, 'approval')
        with self.assertRaises(Problem) as error:
            self.decision(change, user=self.member)
        self.assertEqual(error.exception.status, 403)
        with self.assertRaises(Problem):
            self.move(change, 'progress')
        with self.assertRaises(Problem) as error:
            self.command('tasks', {'id': change['id'], 'reason': 'Obsoleto', 'expectedUpdatedAt': 'old'}, 'approve')
        self.assertEqual(error.exception.status, 409)
        approved = self.decision(change)
        self.assertEqual(approved['approval']['actorName'], self.admin['name'])
        with self.assertRaises(Problem):
            self.command('tasks', {**approved, 'title': 'Alterado después de aprobar'})
        self.move(change, 'progress', user=self.member)
        self.move(change, 'review')
        self.move(change, 'done')
        reopened = self.move(change, 'pending')
        self.assertEqual(reopened['approval']['status'], 'pending')
        self.command('tasks', {**reopened, 'title': 'Nueva propuesta'})
        self.move(change, 'approval')
        with self.assertRaises(Problem):
            self.move(change, 'progress')

    def test_rejected_changes_require_resubmission(self):
        change = self.move(self.task(type='change'), 'approval')
        self.decision(change, 'reject')
        with self.assertRaises(Problem):
            self.move(change, 'progress')
        with self.assertRaises(Problem):
            self.decision(change)
        self.move(change, 'pending')
        self.move(change, 'approval')
        self.decision(change)
        self.move(change, 'progress')

    def test_automatic_assignment_removal_invalidates_change_approval(self):
        change = self.task(type='change', assigneeId=self.member['id'])
        self.move(change, 'approval')
        self.decision(change)
        self.move(change, 'progress')
        self.command('users', {'id': self.member['id']}, 'delete')
        updated = self.get(change)
        self.assertEqual(updated['approval']['status'], 'pending')
        self.assertEqual(updated['columnId'], self.columns[0]['id'])
        self.assertIsNone(updated['assigneeId'])

    def test_assignment_cleanup_preserves_completed_change_and_successors(self):
        change = self.task(type='change', assigneeId=self.member['id'])
        self.move(change, 'approval')
        self.decision(change)
        self.finish(change)
        successor = self.task(dependencyIds=[change['id']])
        self.move(successor, 'progress')
        self.command('users', {'id': self.member['id']}, 'delete')
        completed = self.get(change)
        self.assertEqual(completed['columnId'], self.columns[3]['id'])
        self.assertEqual(completed['approval']['status'], 'approved')
        self.assertIsNone(completed['assigneeId'])

    def test_dependencies_reject_self_cycles_and_cross_project_links(self):
        a, b, c = self.task(title='A'), self.task(title='B'), self.task(title='C')
        self.command('tasks', {**b, 'dependencyIds': [a['id']]})
        self.command('tasks', {**c, 'dependencyIds': [b['id']]})
        with self.assertRaises(Problem):
            self.command('tasks', {**a, 'dependencyIds': [c['id']]})
        with self.assertRaises(Problem):
            self.command('tasks', {**a, 'dependencyIds': [a['id']]})
        self.command('projects', {'name': 'Otro', 'userIds': [], 'groupIds': []})
        with self.store.connection() as db:
            other = self.store.all(db, 'projects')[-1]
            column = next(c for c in self.store.all(db, 'columns') if c['projectId'] == other['id'] and c['stage'] == 'pending')
        with self.assertRaises(Problem):
            self.task(projectId=other['id'], columnId=column['id'], dependencyIds=[a['id']])
        with self.assertRaises(Problem):
            self.command('tasks', {'id': a['id']}, 'delete')
        with self.assertRaises(Problem):
            self.task(dependencyIds=['missing'])
        self.assertEqual(self.get(a)['dependencyIds'], [])

    def test_dependencies_block_execution_and_reopening_predecessor(self):
        predecessor = self.task()
        successor = self.task(dependencyIds=[predecessor['id']])
        with self.assertRaises(Problem):
            self.move(successor, 'progress')
        self.finish(predecessor)
        self.move(successor, 'progress')
        with self.assertRaises(Problem):
            self.move(predecessor, 'progress')
        another = self.task()
        with self.assertRaises(Problem):
            self.command('tasks', {**self.get(successor), 'dependencyIds': [another['id']]})
        self.move(successor, 'pending')
        self.move(predecessor, 'progress')

    def test_comments_audit_and_visibility_survive_author_deletion(self):
        task = self.task(assigneeId=self.member['id'])
        self.command('tasks', {'id': task['id'], 'body': '<script>texto seguro</script>'}, 'comment', self.member)
        current = self.get(task)
        self.command('tasks', {**current, 'title': 'Título actualizado', 'priority': 'high'})
        self.move(task, 'progress')
        self.command('users', {'id': self.member['id']}, 'delete')
        with self.store.connection() as db:
            state = self.store.state(db, self.admin)
            self.assertEqual(state['comments'][0]['authorName'], 'Ana')
            self.assertEqual(state['comments'][0]['body'], '<script>texto seguro</script>')
            events = state['activity']
            self.assertEqual(events[0]['action'], 'created')
            self.assertTrue(any(e['actorName'] == 'Ana' and e['action'] == 'commented' for e in events))
            self.assertTrue(any(c['field'] == 'priority' and c['before'] == 'Media' and c['after'] == 'Alta' for e in events for c in e['changes']))
            outsider = self.store.save_user(db, None, {'name': 'Fuera', 'email': 'outside@example.test', 'role': 'member', 'password': 'outside-password'})
            self.assertEqual(self.store.state(db, outsider)['activity'], [])
            self.assertEqual(self.store.state(db, outsider)['comments'], [])
        with self.assertRaises(Problem):
            self.command('tasks', {'id': task['id'], 'body': ' '}, 'comment')
        self.command('tasks', {'id': task['id']}, 'delete')
        with self.store.connection() as db:
            self.assertEqual(self.store.state(db, self.admin)['activity'][-1]['action'], 'deleted')

    def test_column_stage_changes_cannot_bypass_workflow(self):
        task = self.task()
        with self.assertRaises(Problem):
            self.command('columns', {**self.columns[0], 'stage': 'done'})
        self.command('columns', {'projectId': self.project['id'], 'name': 'Segunda pendiente', 'stage': 'pending'})
        with self.store.connection() as db:
            new = self.store.all(db, 'columns')[-1]
        self.move(task, 'progress')
        self.command('columns', {**self.columns[0], 'stage': 'review'})
        with self.assertRaises(Problem):
            self.command('columns', {'id': new['id']}, 'delete')

    def test_legacy_migration_preserves_records_and_makes_backup_once(self):
        legacy_path = Path(self.tmp.name) / 'legacy.sqlite3'
        source = Store(legacy_path)
        task = {'id': 'old-task', 'title': 'Conservar', 'description': '', 'priority': 'low', 'projectId': 'old-project', 'columnId': 'old-column', 'createdAt': '2026-01-01T00:00:00Z', 'statusSince': '2026-01-02T00:00:00Z', 'updatedAt': '2026-01-02T00:00:00Z', 'assigneeId': None, 'startAt': None, 'endAt': None, 'statusHistory': [], 'dependencyIds': []}
        with source.connection() as db:
            source.put(db, 'projects', {'id': 'old-project', 'name': 'Anterior', 'userIds': [], 'groupIds': []})
            source.put(db, 'columns', {'id': 'old-column', 'name': 'En progreso', 'projectId': 'old-project', 'position': 1})
            source.put(db, 'tasks', task)
            db.execute('PRAGMA user_version=0')
        migrated = Store(legacy_path)
        with migrated.connection() as db:
            updated = migrated.get(db, 'tasks', task['id'])
            self.assertEqual(updated['createdAt'], task['createdAt'])
            self.assertEqual(updated['statusSince'], task['statusSince'])
            self.assertEqual(updated['folio'], 'TAR-000001')
            self.assertEqual(migrated.get(db, 'columns', 'old-column')['stage'], 'progress')
            self.assertEqual(len(migrated.all(db, 'columns')), 5)
        self.assertEqual(len(list((legacy_path.parent / 'backups').glob('*.sqlite3'))), 1)
        Store(legacy_path)
        with migrated.connection() as db:
            self.assertEqual(len(migrated.all(db, 'activity')), 1)
            self.assertEqual(migrated.next_folio(db, 'task'), 'TAR-000002')

    def test_cycle_detection_handles_long_chains_without_recursion(self):
        tasks = [{'id': str(i), 'dependencyIds': [str(i - 1)] if i else []} for i in range(3000)]
        self.assertTrue(dependency_cycle(tasks, '0', ['2999']))
        self.assertFalse(dependency_cycle(tasks, '3000', ['2999']))
