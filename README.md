# frozen_back

Backend Django para la pyme Frozen — sistema de gestión de producción, planificación, stock, ventas y reportes.

## Índice
- **Resumen**: qué es el proyecto.
- **Stack**: tecnologías usadas.
- **Estructura**: carpetas y apps principales.
- **Requisitos**: entorno mínimo.
- **Instalación (Windows PowerShell)**: instrucciones paso a paso.
- **Configuración**: variables y base de datos.
- **Ejecutar**: correr migraciones, servidor y pruebas.
- **API / Endpoints**: cómo encontrar y documentar endpoints.
- **Reporte OEE**: notas sobre la implementación y cómo consumirlo.
- **Contribuir**: guía rápida para colaboradores.
- **Contacto**n+
---

## Resumen

`frozen_back` es el backend de la aplicación de gestión de una pyme del rubro alimentario. Implementado con Django y Django REST Framework, contiene módulos para producción, planificación, compras, despachos, stock, trazabilidad, recetas, reportes y ventas.

El propósito de este README es permitir a desarrolladores levantar el proyecto localmente, ejecutar tests y entender dónde extender la funcionalidad (por ejemplo, el reporte OEE).

## Stack tecnológico

- Python 3.x
- Django
- Django REST Framework
- SQLite (por defecto en desarrollo)
- Dependencias listadas en `requirements.txt`

## Estructura del repositorio (resumen)

- `manage.py` — utilitario Django.
- `frozen_back/` — settings y configuración del proyecto.
- Apps principales (carpetas): `produccion`, `planificacion`, `reportes`, `stock`, `recetas`, `materias_primas`, `empleados`, `ventas`, `despachos`, `compras`, `login`, `productos`, `reportes`, `trazabilidad`, `planificacion`.
- `env/` — entorno virtual incluido (opcional). No subas entornos grandes al repo en producción.

Para detalles de modelos y vistas, revisa cada app en su carpeta correspondiente (ej. `produccion/models.py`, `reportes/views.py`).

## Requisitos previos

- Windows PowerShell (o Bash)
- Python 3.8+ instalado
- `pip` disponible

Recomendación: usar el entorno virtual incluido (`env`) o crear uno nuevo.

## Instalación y ejecución (Windows PowerShell)

1) Activar el entorno virtual provisto (si lo vas a usar):

```powershell
# desde la raíz del proyecto
.\env\Scripts\Activate.ps1
# o si usas virtualenv/venv personalizado:
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2) Instalar dependencias:

```powershell
pip install -r requirements.txt
```

3) Configurar variables de entorno (opcional). Si usas `.env`, copia el ejemplo y ajusta:

```powershell
# crear un .env con las variables necesarias (SECRET_KEY, DEBUG, DB settings, etc.)
copy .env.example .env
# editar .env según corresponda
```

4) Migraciones y creación de superusuario:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

5) Correr servidor de desarrollo:

```powershell
python manage.py runserver 0.0.0.0:8000
```

6) (Opcional) Cargar datos de ejemplo si existen fixtures:

```powershell
python manage.py loaddata fixtures/initial_data.json
```

## Base de datos

Por defecto el proyecto incluye `db.sqlite3` para desarrollo. Para producción, configura una base de datos adecuada (Postgres, MySQL) y ajusta `frozen_back/settings.py` o variables de entorno.

## Pruebas

Ejecutar tests:

```powershell
python manage.py test
```

## API / Endpoints

El proyecto usa Django REST Framework en varias apps. Para encontrar endpoints:

- Revisa `urls.py` en la raíz (`frozen_back/urls.py`) y en cada app (`*/urls.py`).
- Si está habilitado, la interfaz browsable de DRF está disponible al abrir las rutas en el navegador.

Ejemplo de endpoints (puede variar según versión/branch):

- `GET /api/produccion/` — listar eventos de producción.
- `POST /api/planificacion/...` — operaciones de planificación.
- `GET /api/reportes/oee/` — (si se implementa) reporte OEE.

Si quieres documentación automática, podemos añadir `drf-yasg` o `drf-spectacular` para generar OpenAPI/Swagger.

## Reporte OEE (operational equipment effectiveness)

Notas rápidas para implementarlo:

- El cálculo OEE requiere Availability, Performance y Quality. Ver la fórmula en `reportes`.
- Recomendación de implementación:
	- Añadir/confirmar registros de producción con campos: `machine`, `start_time`, `end_time`, `total_count`, `good_count`, `product` y registros de downtime.
	- Crear servicio reusables en `reportes/services.py`, por ejemplo `compute_oee(start, end, machine=None)`.
	- Exponer endpoint REST en `reportes/views.py` y registrar en `reportes/urls.py`.

En este repositorio ya existe la app `reportes/` — revisa `reportes/views.py` para integrarlo o ampliar.

## Desarrollo y estilo de código

- Sigue las convenciones PEP8.
- Recomendado: `black` para formateo y `isort` para imports.

Instalación de herramientas (opcional):

```powershell
pip install black isort
# formatear:
black .
isort .
```

## Contribuir

1. Crea una rama feature: `git checkout -b feature/mi-cambio`.
2. Implementa cambios y añade tests.
3. Ejecuta `python manage.py test` y formatea el código.
4. Abre un Pull Request con descripción clara y referencias a issues.

Si vas a añadir el cálculo de OEE, incluye tests unitarios para cubrir casos borde (tiempos cero, producción cero, todas piezas defectuosas, etc.).

## Deploy (resumen)

- Configurar variables de entorno y base de datos de producción.
- Usar un servidor WSGI (Gunicorn/uWSGI) detrás de un proxy (NGINX).
- Configurar almacenamiento estático/media y backups de base de datos.

## Archivos y lugares importantes

- `manage.py` — comandos Django.
- `frozen_back/settings.py` — configuración del proyecto.
- `reportes/` — lógica de reportes (lugar natural para OEE).
- `produccion/` — modelos y datos de producción.
- `planificacion/` — lógica de planificación y replanificador (`planificacion/replanificador.py`).

## Contacto

Si necesitas asistencia con la implementación de una funcionalidad (por ejemplo, el endpoint OEE o tests), dime y puedo:

- Implementar `reportes/services.py` con la función `compute_oee`.
- Añadir la vista DRF y tests básicos.

---

Licencia: revisa la política de tu empresa o añade un archivo `LICENSE` si corresponde.

Última actualización: diciembre 2025


