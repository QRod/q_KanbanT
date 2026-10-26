// Prueba real de navegador con Chrome y CDP; usa exclusivamente datos temporales.
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import assert from 'node:assert/strict';
const temporary = await mkdtemp(join(tmpdir(), 'qkanbant-qa-'));
const chromePath = process.env.QKT_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const server = spawn('python3', ['server.py', '--port', '5174', '--database', join(temporary, 'qa.sqlite3')], { stdio: 'ignore' });
const chrome = spawn(chromePath, ['--headless=new', `--user-data-dir=${join(temporary, 'chrome')}`, '--remote-debugging-port=9227', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-sync', 'about:blank'], { stdio: 'ignore' });
let socket;
async function until(fn, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { try { const value = await fn(); if (value) return value; } catch {} await new Promise(r => setTimeout(r, 120)); }
  throw new Error('Tiempo de espera agotado');
}
try {
  await until(async () => (await fetch('http://127.0.0.1:5174/api/session')).ok);
  const targets = await until(async () => await (await fetch('http://127.0.0.1:9227/json')).json());
  socket = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  let nextId = 0; const pending = new Map(), errors = [];
  socket.addEventListener('message', event => { const data = JSON.parse(event.data); if (data.id) { const cb = pending.get(data.id); pending.delete(data.id); if (data.error) cb.reject(new Error(data.error.message)); else cb.resolve(data.result); } if (data.method === 'Runtime.exceptionThrown') errors.push(data.params.exceptionDetails.text); });
  const cdp = (method, params = {}) => new Promise((resolve, reject) => { const id = ++nextId; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); });
  const evaluate = async expression => { const result = await cdp('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }); if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text); return result.result.value; };
  const wait = expression => until(() => evaluate(expression));
  const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const fill = values => evaluate(`{ const form = document.querySelector('dialog[open] form') || document.querySelector('#auth-form'); for (const [key, value] of Object.entries(${JSON.stringify(values)})) form.elements[key].value = value; }`);
  const submit = () => evaluate(`(document.querySelector('dialog[open] form') || document.querySelector('#auth-form')).requestSubmit()`);
  await cdp('Runtime.enable'); await cdp('Page.enable');
  await cdp('Page.navigate', { url: 'http://127.0.0.1:5174/' });
  await wait(`document.querySelector('#auth-title')?.textContent === 'Crea tu espacio'`);
  await fill({ name: 'QA Admin', email: 'qa@example.test', password: 'qa-password-123' }); await submit();
  await wait(`!document.querySelector('#app').hidden`);
  await click('[data-page="users"]'); await click('#create-main');
  await fill({ name: 'Integrante QA', email: 'member@example.test', role: 'member', password: 'member-password-123' }); await submit();
  await wait(`!document.querySelector('#editor').open && document.querySelector('#management-list').textContent.includes('Integrante QA')`);
  await click('[data-page="groups"]'); await click('#create-main');
  await fill({ name: 'Soporte QA', description: 'Grupo de prueba' });
  await evaluate(`document.querySelectorAll('input[name="userIds"]')[1].checked = true`); await submit();
  await wait(`!document.querySelector('#editor').open && document.querySelector('#management-list').textContent.includes('Soporte QA')`);
  await click('[data-page="users"]');
  await evaluate(`[...document.querySelectorAll('tbody tr')].find(r=>r.textContent.includes('member@example.test')).querySelector('button').click()`);
  assert.equal(await evaluate(`document.querySelector('input[name="groupIds"]').checked`), true);
  await submit(); await wait(`!document.querySelector('#editor').open`);
  await click('[data-page="board"]'); await click('#new-project');
  await fill({ name: 'Proyecto QA', description: 'Proyecto de prueba' }); await evaluate(`document.querySelector('input[name="groupIds"]').checked = true`); await submit();
  await wait(`!document.querySelector('#editor').open && [...document.querySelector('#project-select').options].some(o => o.text === 'Proyecto QA')`);
  await evaluate(`{ const s = document.querySelector('#project-select'); s.value = [...s.options].find(o => o.text === 'Proyecto QA').value; s.dispatchEvent(new Event('change')); }`);
  await click('#create-main');
  await fill({ title: 'Tarea QA', description: 'Recorrido de extremo a extremo', startAt: '2026-10-24T09:00', endAt: '2026-10-26T18:00', priority: 'high' });
  await evaluate(`{const s=document.querySelector('select[name="assigneeId"]');s.value=[...s.options].find(o=>o.text.startsWith('Integrante QA')).value;}`); await submit();
  await wait(`!document.querySelector('#editor').open && document.querySelector('#board').textContent.includes('Tarea QA')`);
  await evaluate(`{ const s = document.querySelector('.move-select'); s.selectedIndex = 1; s.dispatchEvent(new Event('change')); }`);
  await wait(`document.querySelectorAll('.column')[1].textContent.includes('Tarea QA')`);
  await click('.task-title');
  await evaluate(`{const s=document.querySelector('select[name="assigneeId"]');s.value=[...s.options].find(o=>o.value.startsWith('group:')).value;}`);
  await submit(); await wait(`!document.querySelector('#editor').open && document.querySelector('.assignee').textContent.includes('Grupo: Soporte QA')`);
  await click('#toggle-views'); await click('#show-calendar'); await click('#show-gantt');
  assert.equal(await evaluate(`document.querySelector('#calendar-section').hidden`), false);
  assert.equal(await evaluate(`document.querySelector('#gantt-section').hidden`), false);
  assert.equal(await evaluate(`document.querySelectorAll('.gantt-bar').length`), 1);
  assert.equal(await evaluate(`document.querySelectorAll('.calendar-cell').length`), 42);
  await click('.gantt-bar');
  assert.equal(await evaluate(`document.querySelector('input[name="title"]').value`), 'Tarea QA');
  assert.equal(await evaluate(`document.querySelector('.status-history').textContent.includes('En progreso')`), true);
  await click('#cancel-editor');
  // Tipos y folios, aprobación y comentarios reales desde la interfaz.
  for (const [type, title, prefix] of [['incident','Incidente QA','INC-'],['request','Solicitud QA','SOL-'],['change','Cambio QA','CAM-']]) {
    await click('#create-main'); await fill({type, title});
    await evaluate(`document.querySelector('select[name="type"]').dispatchEvent(new Event('change'))`);
    await submit(); await wait(`!document.querySelector('#editor').open && document.querySelector('#board').textContent.includes(${JSON.stringify(title)})`);
    assert.equal(await evaluate(`document.querySelector('#board').textContent.includes(${JSON.stringify(prefix)})`), true);
  }
  const editByTitle = title => evaluate(`[...document.querySelectorAll('.task-title')].find(n=>n.textContent===${JSON.stringify(title)}).click()`);
  const setStage = name => evaluate(`{const s=document.querySelector('select[name="columnId"]');s.value=[...s.options].find(o=>o.text.startsWith(${JSON.stringify(name)})).value;}`);
  await editByTitle('Cambio QA'); await setStage('Por aprobar'); await submit(); await wait(`!document.querySelector('#editor').open`);
  await editByTitle('Cambio QA');
  await evaluate(`document.querySelector('#comment-form textarea').value='<script>no ejecutar</script> Contexto de aprobación'`);
  await evaluate(`document.querySelector('#comment-form').requestSubmit()`);
  await wait(`document.querySelector('#comments-list').textContent.includes('Contexto de aprobación')`);
  assert.equal(await evaluate(`document.querySelectorAll('#comments-list script').length`), 0);
  await evaluate(`document.querySelector('#approval-reason').value='Validación funcional completa'`);
  await click('#approval-panel .primary'); await wait(`document.querySelector('#approval-panel h3')?.textContent.includes('Aprobado')`);
  await setStage('En progreso'); await submit(); await wait(`!document.querySelector('#editor').open`);
  // Una actualización al comentar no permite aprobar datos que aún no se revisaron.
  await click('#create-main'); await fill({type:'change',title:'Cambio concurrente QA'}); await submit(); await wait(`!document.querySelector('#editor').open`);
  await editByTitle('Cambio concurrente QA'); await setStage('Por aprobar'); await submit(); await wait(`!document.querySelector('#editor').open`);
  await editByTitle('Cambio concurrente QA');
  assert.equal(await evaluate(`(async()=>{const state=await fetch('/api/state').then(r=>r.json());const task=state.tasks.find(t=>t.title==='Cambio concurrente QA');return fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json','X-QKT-Request':'1'},body:JSON.stringify({kind:'tasks',action:'save',data:{...task,description:'Alcance modificado por otra sesión',expectedUpdatedAt:task.updatedAt}})}).then(r=>r.status)})()`),200);
  await evaluate(`document.querySelector('#comment-form textarea').value='Comentario que actualiza la actividad sin reemplazar el formulario'`);
  await evaluate(`document.querySelector('#comment-form').requestSubmit()`);
  await wait(`document.querySelector('#comments-list').textContent.includes('Comentario que actualiza')`);
  await evaluate(`document.querySelector('#approval-reason').value='Decisión desde formulario anterior'`);
  await click('#approval-panel .primary'); await wait(`document.querySelector('#toast').textContent.includes('Actualiza y revisa')`);
  await click('#cancel-editor'); await editByTitle('Cambio concurrente QA');
  assert.equal(await evaluate(`document.querySelector('textarea[name="description"]').value`),'Alcance modificado por otra sesión');
  await click('#cancel-editor');
  // Dependencias, ciclo rechazado y bloqueo hasta finalizar el predecesor.
  await click('#create-main'); await fill({title:'Predecesor QA',startAt:'2026-10-24T09:00',endAt:'2026-10-26T18:00'}); await submit(); await wait(`!document.querySelector('#editor').open`);
  await click('#create-main'); await fill({title:'Sucesor QA',startAt:'2026-10-25T09:00',endAt:'2026-10-27T18:00'});
  await evaluate(`[...document.querySelectorAll('input[name="dependencyIds"]')].find(n=>n.parentElement.textContent.includes('Predecesor QA')).checked=true`);
  await submit(); await wait(`!document.querySelector('#editor').open && document.querySelectorAll('.dependency-link').length===1`);
  assert.equal(await evaluate(`document.querySelector('#gantt-dependency-notes').textContent.includes('solapan')`), true);
  assert.equal(await evaluate(`[...document.querySelectorAll('.task-card')].find(n=>n.textContent.includes('Sucesor QA')).querySelector('.move-select').options[1].disabled`), true);
  await editByTitle('Predecesor QA');
  await evaluate(`[...document.querySelectorAll('input[name="dependencyIds"]')].find(n=>n.parentElement.textContent.includes('Sucesor QA')).checked=true`);
  await submit(); await wait(`document.querySelector('#editor-error').textContent.includes('ciclo')`); await click('#cancel-editor');
  for (const stage of ['En progreso','En revisión','Hecho']) {
    await editByTitle('Predecesor QA'); await setStage(stage); await submit(); await wait(`!document.querySelector('#editor').open`);
  }
  await editByTitle('Sucesor QA'); await setStage('En progreso'); await submit(); await wait(`!document.querySelector('#editor').open`);
  await evaluate(`{ const s=document.querySelector('#type-filter');s.value='incident';s.dispatchEvent(new Event('change')); }`);
  assert.equal(await evaluate(`document.querySelectorAll('.task-card').length`), 1);
  await evaluate(`{ const s=document.querySelector('#type-filter');s.value='';s.dispatchEvent(new Event('change')); }`);
  assert.equal(await evaluate(`document.querySelector('#project-activity-list').textContent.includes('aprobó el cambio')`), true);
  // Verifica acceso del integrante mediante un inicio de sesión real.
  await click('#logout'); await wait(`!document.querySelector('#auth').hidden`);
  await fill({ email: 'member@example.test', password: 'member-password-123' }); await submit();
  await wait(`!document.querySelector('#app').hidden`);
  assert.equal(await evaluate(`document.querySelector('#project-select').options.length`), 1);
  assert.equal(await evaluate(`document.querySelector('#project-actions').hidden`), true);
  await click('#create-main');
  assert.equal(await evaluate(`document.querySelector('select[name="assigneeId"]').options.length`), 3);
  await click('#cancel-editor'); await click('[data-page="users"]');
  assert.equal(await evaluate(`document.querySelector('#create-main').hidden`), true);
  // Comprueba denegación en la API, no solo en la interfaz.
  assert.equal(await evaluate(`fetch('/api/command', {method:'POST', headers:{'Content-Type':'application/json','X-QKT-Request':'1'},body:JSON.stringify({kind:'users',action:'delete',data:{id:'invalid'}})}).then(r=>r.status)`), 403);
  await cdp('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await click('[data-page="board"]');
  assert.equal(await evaluate(`document.documentElement.scrollWidth <= window.innerWidth`), true);
  assert.deepEqual(errors, []);
  console.log('QA Chrome OK: alta inicial, usuarios, grupos, proyectos, asignación, movimiento, calendario, Gantt, tipos y folios, aprobación, comentarios, ciclos, bloqueos, permisos y ancho móvil.');
} finally {
  socket?.close(); chrome.kill('SIGTERM'); server.kill('SIGTERM');
  await new Promise(r => setTimeout(r, 1000));
  await rm(temporary, { recursive: true, force: true });
}
