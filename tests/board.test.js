import test from 'node:test';
import assert from 'node:assert/strict';
import { initialBoard, validBoard, moveTask } from '../src/board.js';

test('el tablero inicial es válido y no comparte estado', () => {
  const board = initialBoard();
  assert.equal(validBoard(board), true);
  board.columns.pop();
  assert.equal(initialBoard().columns.length, 4);
});
test('mover una tarea conserva sus datos y rechaza destinos inexistentes', () => {
  const board = initialBoard();
  board.tasks.push({ id: 't1', columnId: 'pending', title: 'Revisar servicio', description: 'Contexto', priority: 'high' });
  assert.equal(moveTask(board, 't1', 'progress'), true);
  assert.equal(board.tasks[0].columnId, 'progress');
  assert.equal(board.tasks[0].description, 'Contexto');
  assert.equal(moveTask(board, 't1', 'missing'), false);
  assert.equal(moveTask(board, 'missing', 'pending'), false);
  assert.equal(validBoard(board), true);
});
test('rechaza almacenamiento corrupto, duplicados y tareas huérfanas', () => {
  assert.equal(validBoard(null), false);
  assert.equal(validBoard({ version: 2, columns: [], tasks: [] }), false);
  const board = initialBoard();
  board.tasks.push({ id: 't1', columnId: 'missing', title: 'Tarea', description: '', priority: 'low' });
  assert.equal(validBoard(board), false);
  board.tasks[0].columnId = 'pending';
  assert.equal(validBoard(board), true);
  board.tasks.push({ ...board.tasks[0] });
  assert.equal(validBoard(board), false);
  board.tasks = [];
  board.columns.push({ ...board.columns[0] });
  assert.equal(validBoard(board), false);
});

import { duration, activeDuration, localInput, taskOnDay, timeline, dayOrdinal } from '../src/board.js';

test('los tiempos manejan fechas futuras, ausencia de inicio y fin', () => {
  const clock = Date.parse('2026-10-24T18:00:00Z');
  assert.equal(activeDuration({ startAt: null }, clock), 'Sin iniciar');
  assert.equal(activeDuration({ startAt: '2026-10-25T18:00:00Z' }, clock), 'Por iniciar');
  assert.equal(activeDuration({ startAt: '2026-10-24T16:00:00Z', endAt: '2026-10-24T17:00:00Z' }, clock), '1 h 0 min');
  assert.equal(activeDuration({ startAt: '2026-10-24T16:00:00Z', endAt: '2026-10-25T17:00:00Z' }, clock), '2 h 0 min');
  assert.equal(duration('2026-10-23T17:30:00Z', clock), '1 d 0 h 30 min'.replace('0 h ', ''));
});
test('el calendario muestra todo el intervalo y separa las tareas sin fechas', () => {
  const start = new Date(2026, 9, 23, 10), end = new Date(2026, 9, 25, 12);
  const task = { startAt: start.toISOString(), endAt: end.toISOString() };
  assert.equal(taskOnDay(task, new Date(2026, 9, 24)), true);
  assert.equal(taskOnDay(task, new Date(2026, 9, 26)), false);
  assert.equal(taskOnDay({ startAt: null }, new Date()), false);
  assert.equal(localInput(start).slice(0, 10), '2026-10-23');
});
test('Gantt calcula intervalos por día y semana y cruza cambios de mes', () => {
  const tasks = [{ startAt: new Date(2026, 9, 30).toISOString(), endAt: new Date(2026, 10, 20).toISOString() }];
  const days = timeline(tasks), weeks = timeline(tasks, 'week');
  assert.equal(days.count, 22);
  assert.equal(weeks.count, 4);
  assert.equal(days.start, dayOrdinal(tasks[0].startAt));
  assert.equal(timeline([]).count, 14);
});


import { dependencyOrder, dependencyLinks } from '../src/board.js';
test('Gantt ordena predecesores antes de sucesores y dibuja sus conexiones', () => {
  const predecessor = {id:'a',startAt:new Date(2026,9,24,9).toISOString(),endAt:new Date(2026,9,26,18).toISOString(),dependencyIds:[]};
  const successor = {id:'b',startAt:new Date(2026,9,25,9).toISOString(),endAt:new Date(2026,9,27,18).toISOString(),dependencyIds:['a']};
  const ordered = dependencyOrder([successor,predecessor]);
  assert.deepEqual(ordered.map(t=>t.id), ['a','b']);
  const links=dependencyLinks(ordered,timeline(ordered),44);
  assert.equal(links.length,1);
  assert.equal(links[0].conflict,true);
  assert.equal(links[0].y2-links[0].y1,56);
  assert.equal(dependencyLinks([successor],timeline([successor]),44).length,0);
});
test('las conexiones respetan horarios del mismo día y predecesores sin fin', () => {
  const predecessor={id:'a',startAt:new Date(2026,9,24,9).toISOString(),endAt:new Date(2026,9,24,10).toISOString(),dependencyIds:[]};
  const successor={id:'b',startAt:new Date(2026,9,24,12).toISOString(),dependencyIds:['a']};
  assert.equal(dependencyLinks([predecessor,successor],timeline([predecessor,successor]),44)[0].conflict,false);
  predecessor.endAt=null;
  assert.equal(dependencyLinks([predecessor,successor],timeline([predecessor,successor]),44)[0].unknown,true);
});
