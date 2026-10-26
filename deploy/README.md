# Despliegue

`install.sh` genera unidades systemd y configuración HTTPS en cada servidor.
La configuración activa y sus secretos pertenecen a `/etc`, los datos a `/var/lib`
y las entregas inmutables a `/opt`. No copiar archivos activos al repositorio.

Para un proxy externo, dirigir las solicitudes HTTPS al backend loopback elegido.
Mantener Host y configurar el origen público de Kanban mediante QKT_PUBLIC_ORIGIN.
