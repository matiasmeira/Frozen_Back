from datetime import datetime, date
from empleados.models import Empleado, Fichada

def euclidean_distance(vec1, vec2):
    if len(vec1) != len(vec2):
        raise ValueError("Los vectores deben tener la misma longitud")
    # Calcula la raíz cuadrada de la suma de los cuadrados de las diferencias
    suma = sum((a - b) ** 2 for a, b in zip(vec1, vec2))
    return suma ** 0.5


def buscar_empleado_por_vector_facial(vector):
    empleados = Empleado.objects.select_related("id_face").all()

    for empleado in empleados:
        if not empleado.id_face or not empleado.id_face.vector:
            continue

        vector_db = empleado.id_face.vector

        if len(vector) != len(vector_db):
            continue

        distancia = euclidean_distance(vector, vector_db)

        if distancia < 0.6:
            return empleado

    return None


def registrar_fichada(empleado):
    hoy = date.today()
    ahora = datetime.now()

    fichada = Fichada.objects.filter(
        id_empleado=empleado, fecha=hoy, hora_salida__isnull=True
    ).first()

    if fichada:
        fichada.hora_salida = ahora.time()
        fichada.save()
        return "salida", ahora
    else:
        Fichada.objects.create(
            id_empleado=empleado,
            fecha=hoy,
            hora_entrada=ahora.time()
        )
        return "entrada", ahora


def obtener_info_empleado(empleado):
    return {
        "nombre": empleado.nombre,
        "apellido": empleado.apellido,
        "rol": empleado.id_rol.descripcion if empleado.id_rol else "No especificado",
        "departamento": empleado.id_departamento.descripcion if hasattr(empleado, "id_departamento") and empleado.id_departamento else "No especificado",
        "turno": empleado.id_turno.descripcion if empleado.id_turno else "No especificado",
    }
