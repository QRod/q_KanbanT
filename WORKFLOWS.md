# Flujos de trabajo · q_KanbanT 0.3

Estos son los flujos iniciales de la aplicación. Las reglas se aplican en el servidor a toda operación, también al arrastre y a solicitudes directas a la API.

## Tipos y etapas

| Tipo | Folio | Recorrido principal |
|---|---|---|
| Tarea | TAR-000001 | Pendiente → En curso → Revisión → Terminado |
| Incidente | INC-000001 | Pendiente → En curso → Revisión → Terminado |
| Solicitud | SOL-000001 | Pendiente → Revisión → En curso → Terminado |
| Cambio | CAM-000001 | Pendiente → Aprobación → En curso → Revisión → Terminado |

Las columnas son la representación de las etapas: «Por hacer» corresponde a Pendiente; «En progreso», a En curso; «En revisión», a Revisión; «Hecho», a Terminado; «Por aprobar», a Aprobación. Se pueden renombrar, agregar columnas de una misma etapa y mover registros entre ellas sin alterar su proceso. Cambiar de columna reinicia el contador de estatus, incluso si ambas pertenecen a la misma etapa.

Los registros nuevos comienzan en Pendiente. El formulario muestra todas las transiciones del tipo seleccionado. Los menús deshabilitan las que no se permiten y el servidor las rechaza igualmente. Debe permanecer al menos una columna por etapa, para que ningún flujo se quede sin salida. Para cambiar la etapa de una columna hay que vaciarla y conservar otra de la etapa anterior.

## Rutas de retorno

- Tareas e incidentes: En curso → Pendiente; Revisión → En curso; Terminado → En curso.
- Solicitudes: Revisión → Pendiente; En curso → Revisión; Terminado → Revisión.
- Cambios: Aprobación → Pendiente; En curso → Pendiente; Revisión → Pendiente o En curso; Terminado → Pendiente.

No existe una excepción que permita a los administradores saltarse una transición. Las solicitudes se revisan antes de ejecutarse; tareas e incidentes se revisan después de ejecutarse.

## Aprobación de cambios

1. Crear el cambio en Pendiente con sus datos y fechas.
2. Moverlo a Aprobación.
3. Un administrador lo abre y registra **Aprobar cambio** o **Rechazar cambio**, incluyendo un motivo obligatorio.
4. Si está aprobado, un integrante del proyecto puede moverlo a En curso. La aprobación no mueve automáticamente el cambio.
5. Si se rechaza, debe volver a Pendiente y después a Aprobación para una nueva decisión.

La decisión requiere que el registro no haya cambiado desde que el administrador lo abrió. No se puede reemplazar una decisión ya registrada. Regresar a Pendiente invalida la aprobación y queda registrado en la actividad.

Después de aprobar, no se permite modificar título, descripción, prioridad, responsables, fechas ni dependencias hasta regresar a Pendiente. Esto evita ejecutar un alcance distinto del que se aprobó. Los comentarios pueden seguir publicándose sin invalidar la aprobación. Las bajas de usuarios o membresías que retiren un responsable de un cambio abierto invalidan automáticamente la aprobación y lo devuelven a Pendiente. Si el cambio ya terminó, se conserva su aprobación histórica y su estado final; la baja queda registrada sin reabrir trabajo concluido.

Esta versión usa el rol Administrador para aprobar y permite que un administrador apruebe un cambio propio. La separación de funciones, comité de cambios, niveles de riesgo y múltiples aprobadores son posteriores.

## Dependencias

En el formulario, **Depende de** selecciona predecesores del mismo proyecto. Si B depende de A, A debe estar Terminado antes de que B pase a ejecución. Para tareas, incidentes y cambios esto incluye En curso, Revisión y Terminado; para solicitudes incluye En curso y Terminado, porque su Revisión sucede antes de ejecutar.

Se rechazan autorreferencias, ciclos directos o indirectos, referencias inexistentes y registros de otros proyectos. No se permite agregar un predecesor abierto a un registro ya en ejecución. No se permite borrar un predecesor mientras esté referenciado. Para reabrir un predecesor, sus sucesores deben haber regresado a una etapa anterior a ejecución o haberse desvinculado.

Las dependencias son de fin a inicio sin desfase, no reglas de programación automática. No se exige que las fechas sean coherentes al guardar: el Gantt advierte el conflicto, de modo que se pueda planificar antes de completar la información.

## Gantt

Las filas se ordenan colocando predecesores antes de sucesores. Las flechas conectan el fin planificado del predecesor con el inicio del sucesor. Una conexión roja indica que el sucesor está planificado para comenzar antes del fin de su predecesor. La comparación usa fecha y hora, aunque las barras se dibujan por día.

Las líneas discontinuas indican un predecesor sin fin definido. Los registros sin inicio permanecen en la lista «Sin fecha de inicio». Las conexiones ocultas por los filtros o por falta de fechas se indican debajo del Gantt. No se calculan duración laboral, ruta crítica ni reprogramación automática.

## Actividad y comentarios

Cada registro permite consultar comentarios y actividad con autor y fecha. La actividad registra creación, cambios de campos, asignaciones, fechas, dependencias, estatus, decisiones y eliminación. Los eventos guardan los nombres y valores conocidos en ese momento. La actividad del proyecto permite consultar también los registros eliminados.

No hay edición ni borrado de comentarios o actividad desde la interfaz o la API. Se muestran como texto: contenido que parezca HTML no se ejecuta. Los datos anteriores a la migración tienen un evento de migración; no se inventan autores ni cambios anteriores.
