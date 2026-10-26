# q_KanbanT · 0.4

Aplicación local para gestión de proyectos con tablero Kanban, usuarios, grupos, tipos de registro, flujos, comentarios, trazabilidad y dependencias. Frontend HTML/CSS/JavaScript y servidor Python 3.11+ con SQLite, sin dependencias externas de ejecución.

## Instalación en Linux

El instalador independiente descarga una entrega de GitHub Releases, verifica SHA-256, instala dependencias y crea servicios de aplicación y HTTPS. Requiere Linux con systemd, acceso root y Python 3.11+ disponible en los repositorios de la distribución. Código en `/opt/q-kanbant/releases/`, enlace `current`, datos en `/var/lib/q-kanbant` y configuración privada en `/etc/q-kanbant`. No se guardan datos reales en este repositorio.

Para una IP o nombre de la red local, sustituye `SERVIDOR`:

```sh
curl -fsSL https://raw.githubusercontent.com/QRod/q_KanbanT/v0.4.1/install.sh -o install.sh
less install.sh
sudo bash install.sh --version v0.4.1 --address SERVIDOR --https-port 8444
```

La CA local genera el certificado en cada instalación; no hay certificados ni claves compartidos. El navegador advertirá de la falta de confianza hasta importar la CA local del proxy en el cliente.

Para dominio y certificado público de Let's Encrypt:

```sh
sudo bash install.sh --version v0.4.1 --address app.example.com --tls public --https-port 443 --email admin@example.com
```

El DNS debe apuntar al servidor y los puertos 80/443 estar libres y accesibles desde Internet. Caddy gestiona emisión y renovación. Si ya tienes un proxy compartido o esos puertos ocupados, usa `--proxy external` y configura tu proxy HTTPS contra el backend en loopback; el instalador no modifica ese proxy. El firewall permanece bajo administración del operador.

Después de instalar, crea la primera cuenta de forma interactiva:

```sh
sudo q-kanbant-admin --create-admin
```

El comando detiene brevemente la app, solicita la contraseña sin mostrarla, conserva la propiedad de los datos y vuelve a iniciar el servicio. Las instalaciones de Kanban deshabilitan el alta inicial desde la web para que la primera cuenta no pueda ser reclamada por otro visitante.

### Distribuciones y límites

Se prepararon rutas para Debian/Ubuntu/Zorin/Mint (`apt`), Fedora/RHEL/Rocky/AlmaLinux (`dnf`), openSUSE (`zypper`) y Arch/Manjaro (`pacman`). El proxy incluido tiene binarios oficiales verificados para x86_64 y ARM64. No implica compatibilidad con todas las versiones históricas: se exige Python 3.11+, venv y systemd. En Arch se presupone un sistema actualizado; el instalador no hace una actualización global. Alpine/OpenRC y NixOS requieren instalación manual.

La instalación real se valida en Zorin OS. La detección de las otras familias se prueba con archivos os-release; aún no se ha ejecutado la instalación completa en ellas. La configuración de TLS público está preparada, pero su emisión real requiere un dominio y DNS del operador.

### Actualización, respaldo y recuperación

Vuelve a ejecutar el instalador indicando la nueva etiqueta con las mismas opciones (las preferencias de instalación quedan guardadas de forma privada). No se descarga una rama de desarrollo como si fuera una entrega. Cada versión tiene su propio entorno virtual. Antes del cambio se respalda SQLite mediante su API, junto con configuración y unidades anteriores en `/var/backups/q-kanbant`.

Si el nuevo servicio falla en la comprobación de arranque, el instalador intenta restaurar la versión, base y configuración anteriores. La recuperación manual debe hacerse con el servicio detenido y utilizando el respaldo de la misma fecha; volver solo al código no revierte una migración de datos. Conserva además copias externas de datos y claves; el instalador no sustituye una política de respaldo.

Para migrar una instalación manual, añade `--migrate-from /ruta/a/la/instalacion`. Se copia la base sin borrar el origen. Para q_Inv con credenciales ya cifradas, coloca antes su clave original en `/etc/q-inv/credentials.key` con permisos 600: una clave diferente no recupera las contraseñas anteriores.

Para preparar una entrega desde un checkout limpio:

```sh
python3 scripts/package_release.py v0.4.1
```

El resultado y `SHA256SUMS` quedan en `dist/`, excluido del repositorio. Los paquetes se construyen a partir de archivos versionados, sin bases, claves ni entornos locales. La suma protege la integridad de la descarga; su autenticidad depende del repositorio y del canal HTTPS de GitHub.

## Iniciar

Desde este directorio:

```sh
npm run dev
```

O directamente, sin Node.js:

```sh
python3 server.py
```

Abrir http://127.0.0.1:5173. El servidor debe permanecer encendido; Ctrl+C lo detiene. El antiguo comando `python3 -m http.server` ya no es suficiente, porque la aplicación utiliza una API.

En el primer acceso se solicita crear un administrador con nombre, correo y contraseña de al menos 10 caracteres. No hay credenciales predeterminadas. El administrador puede crear otras cuentas y restablecer sus contraseñas. Los cambios de contraseña revocan las sesiones de esa cuenta, incluida la actual.

La base se crea automáticamente en `.data/kanbant.sqlite3`, excluida de Git. Para respaldarla, detener el servidor y copiar ese archivo a un lugar seguro; para restaurar, reemplazarlo con el servidor detenido. No borrar `.data` al actualizar los archivos de la aplicación. La aplicación usa transacciones SQLite mediante la biblioteca estándar de Python: https://docs.python.org/3.11/library/sqlite3.html.

## Navegación

- **Trabajo → Mi tablero:** selector de proyecto, tareas, columnas, filtros y planificación.
- **Gestión → Usuarios:** crear, modificar y borrar cuentas; roles de administrador e integrante.
- **Gestión → Grupos:** crear equipos, editar sus miembros y eliminarlos.
- Los proyectos se crean, editan y eliminan junto al selector del tablero. Pueden tener integrantes directos y grupos completos. Un grupo representa un equipo en esta etapa.

## Permisos

Los administradores gestionan usuarios, grupos y proyectos, y acceden a todos los proyectos. Los integrantes acceden únicamente a proyectos donde están incluidos directamente o por grupo; en ellos pueden gestionar columnas y tareas. El backend comprueba esos permisos en cada operación. Los roles específicos por proyecto quedan para otra etapa.

Una tarea se puede asignar a un usuario o a un grupo. La relación entre usuarios y grupos se edita desde cualquiera de ambos formularios y se muestra en sus listados. El selector de tareas separa Usuarios y Grupos. Los administradores ven todos los registros: elegir un responsable externo al proyecto añade al usuario como integrante directo o vincula al grupo completo al guardar, tal como indica el formulario. Los integrantes solo pueden elegir responsables ya vinculados al proyecto. «Mis tareas» incluye las asignadas al usuario y a los grupos de los que forma parte. Al retirar usuarios de un proyecto o grupo se limpian las asignaciones que dejan de ser válidas. Eliminar usuarios retira sus membresías y revoca sus sesiones. No se permite eliminar la cuenta propia ni dejar al sistema sin administradores.

No se pueden borrar proyectos con tareas ni columnas ocupadas. Los cambios se guardan en el servidor, compartidos entre sesiones de este servidor. El botón **Actualizar** recupera los cambios de otras sesiones. La edición de una tarea detecta cambios concurrentes; los movimientos de estatus solo actualizan el estado y su historial. No hay sincronización en tiempo real.

## Tareas y tiempos

Cada tarea contiene título, descripción, prioridad, responsable, proyecto, columna, fechas, historial de estatus e identificador estable.

- **Creación:** registrada por el servidor, no editable.
- **Inicio y fin:** fechas con hora, opcionales. El fin requiere inicio y no puede ser anterior a él. Son también las fechas utilizadas para planificar.
- **Tiempo activa:** desde inicio hasta el momento actual, limitado por fin cuando ya ocurrió. Antes del inicio muestra «Por iniciar»; sin inicio, «Sin iniciar». Es tiempo natural, no tiempo trabajado ni SLA: no descuenta pausas, fines de semana o inactividad.
- **Tiempo en el estatus actual:** desde la entrada a la columna actual hasta ahora. Solo cambia su origen al mover la tarea a otra columna; editarla o elegir la misma columna no reinicia el contador. Continúa contando también en «Hecho».

Las fechas se guardan en UTC y se presentan en la zona horaria del navegador. Los contadores visibles se actualizan cada 30 segundos.

## Calendario y Gantt

El botón **Vistas** despliega un panel a la derecha. Activa **Calendario**, **Línea de tiempo** o ambos para mostrarlos debajo del tablero. Respetan el proyecto, búsqueda, prioridad y filtro de mis tareas.

El calendario tiene navegación mensual y muestra cada tarea en todos los días de su intervalo; sin fin se muestra en el día de inicio. El Gantt permite escala diaria o semanal, incluye indicador de hoy y barras por tarea. Las tareas sin fin tienen flecha y un segmento inicial; no se les inventa una fecha de fin. Las tareas sin inicio aparecen en una lista separada. El Gantt dibuja conexiones fin → inicio entre predecesores y sucesores, ordena predecesores antes de sucesores y marca en rojo los solapamientos de fechas. Si una conexión queda fuera de la vista por filtros o falta de fechas, se indica debajo del diagrama. Pulsar una tarea en cualquiera de las vistas abre su edición.

Las dependencias se seleccionan en el formulario de cada registro. Solo se admiten dentro del mismo proyecto, sin autorreferencias ni ciclos. Bloquean el paso a ejecución hasta que todos los predecesores estén terminados. No se puede eliminar un predecesor referenciado ni reabrirlo si ya tiene sucesores en ejecución o terminados. Las fechas no se reprograman automáticamente. Las barras representan días de calendario; no sustituyen un cálculo de capacidad o de duración laboral.


## Registros, flujos y actividad · versión 0.3

El botón **Nuevo registro** permite crear tareas (`TAR`), incidentes (`INC`), solicitudes (`SOL`) y cambios (`CAM`). Los folios son automáticos, inmutables y no se reutilizan después de borrar un registro. El tipo se elige al crear y no se puede cambiar después. Se puede buscar por folio y filtrar por tipo en el tablero; calendario y Gantt respetan esos filtros.

Cada columna tiene una etapa de proceso además de su nombre libre. Los movimientos por selector, formulario, arrastre y API se validan con las reglas de cada tipo. Los cambios requieren una decisión explícita de un administrador, con motivo, en la etapa de aprobación. Ver [WORKFLOWS.md](WORKFLOWS.md) para las rutas y restricciones.

Al abrir un registro se pueden publicar comentarios y consultar su actividad: autor, fecha, campos anteriores y nuevos. Las decisiones de aprobación conservan autor y motivo. Los comentarios y eventos son de solo lectura después de publicarse y conservan el nombre del autor aunque se elimine su cuenta. **Historial de actividad del proyecto** permite consultar eventos incluso de registros eliminados. Solo se entrega la actividad de proyectos a los que la sesión tiene acceso. Esto es trazabilidad del trabajo; no es un registro de auditoría certificado ni resistente a modificaciones directas de la base por un administrador del equipo.

Al iniciar con una base anterior, se realiza una migración transaccional: se conservan identificadores, columnas, relaciones, fechas y contenido; los registros existentes reciben tipo Tarea y folio. Las cuatro etapas originales se asignan por posición y las columnas adicionales antiguas quedan como pendientes; se pueden revisar sus etapas en **Editar columna** cuando estén vacías. Se añade cualquier etapa que falte, incluida aprobación. Antes de migrar una base con tareas se crea una copia en `.data/backups/pre-v03-*.sqlite3`. La migración ocurre una sola vez; no hay historial retroactivo de acciones que antes no se registraban.

## Importar la versión anterior

Si el navegador conserva `q-kanbant.board.v1` en localStorage, al entrar como administrador aparece **Importar tablero anterior**. Lo convierte, una sola vez, en un proyecto nuevo llamado «Tablero anterior». La copia original permanece intacta. La importación usa una transacción: un fallo no deja datos parciales.

La versión anterior no registraba fechas: la creación y entrada al estatus se fijan al momento de importar; inicio y fin quedan vacíos. Usar la misma dirección y puerto del tablero anterior para acceder al almacenamiento del navegador.

## Verificación

Con Node.js 20+ y Python 3.11+:

```sh
npm run check
npm test
```

Prueba opcional de navegador con Node.js 22+ y Google Chrome:

```sh
node tests/browser-smoke.mjs
```

Usa puertos 5174 y 9227 y crea base de datos, cuenta y perfil de Chrome temporales; no modifica la base real. En otros sistemas indicar la ruta del ejecutable mediante `QKT_CHROME`.

## Alcance y siguientes etapas

El backend escucha solamente en `127.0.0.1`. El instalador añade un proxy HTTPS para acceso de red. Las sesiones duran 12 horas y usan cookies HttpOnly y SameSite; las contraseñas se almacenan con scrypt y sal aleatoria. Hay validación de solicitudes, rutas estáticas permitidas y límites de intentos de acceso.

Antes de un despliegue de producción deben completarse recuperación de cuentas, revisión de seguridad y pruebas de carga. El instalador proporciona HTTPS, servicios y respaldo previo a las actualizaciones; los respaldos periódicos externos quedan a cargo del operador. Los permisos granulares, adjuntos, notificaciones, auditoría de administración, catálogos, SLA, editor de flujos, camino crítico, reprogramación automática y cliente Windows/macOS son etapas posteriores. Esta versión incluye flujos iniciales por tipo, no una implementación completa de ITIL.

La fuente de Google Fonts es opcional; sin conexión se usan las fuentes del sistema.

## Archivos

- `server.py`: servidor, API, sesiones, permisos, migraciones y persistencia.
- `workflow.py`: tipos, etapas, transiciones y validación del grafo de dependencias.
- `WORKFLOWS.md`: guía de los flujos y reglas implementados.
- `src/app.js`: interfaz y comunicación con API.
- `src/board.js`: utilidades de fechas y planificación; compatibilidad con importación v1.
- `src/styles.css`: diseño adaptable a escritorio y móvil.
- `tests/`: validaciones del modelo, backend y recorrido de navegador.
