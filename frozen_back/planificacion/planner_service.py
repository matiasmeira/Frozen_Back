import math
from collections import defaultdict
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, F, Q

# Importa tus modelos
from produccion.models import (
    OrdenProduccion, 
    LineaProduccion, 
    OrdenDeTrabajo,
    EstadoOrdenProduccion, # Necesitarás un estado "Planificada"
    EstadoOrdenTrabajo # Necesitarás un estado "Pendiente"
)

# Importa la biblioteca de OR-Tools
from ortools.sat.python import cp_model
from recetas.models import ProductoLinea

# --- Variables de Configuración ---

# Para este ejemplo, dividiremos las Órdenes de Producción grandes
# en Órdenes de Trabajo más pequeñas de este tamaño.
# ¡Puedes ajustar esto!
TAMANO_LOTE_TRABAJO = 20  # Tamaño MÁXIMO (puedes poner 20, 100, etc.)
TAMANO_LOTE_MINIMO = 10

# El "horizonte" es el tiempo máximo que el planificador mirará hacia el futuro.
# Ejemplo: 1 mes (en minutos). CP-SAT REQUIERE ENTEROS.
HORIZONTE_MINUTOS = 24 * 60 #30 * 24 * 60 


def ejecutar_planificador():
    """
    Función principal que lee las órdenes pendientes, las planifica
    y guarda los resultados en la base de datos.
    
    VERSIÓN ACTUALIZADA:
    Respeta la capacidad específica definida en la tabla ProductoLinea.
    """
    
    # 1. --- OBTENER DATOS DE DJANGO ---
    
    ordenes_pendientes = list(OrdenProduccion.objects.filter(
        id_estado_orden_produccion__descripcion='Pendiente de inicio' 
    ).select_related('id_producto')) # Optimización: precargar el producto
    
    # <-- CAMBIO 2: Ya no filtramos por la capacidad genérica de la línea
    lineas = list(LineaProduccion.objects.filter(
        Q(id_estado_linea_produccion__descripcion='Disponible') | 
        Q(id_estado_linea_produccion__descripcion='Ocupada')
    ))

    if not ordenes_pendientes or not lineas:
        print("No hay órdenes pendientes o no hay líneas operativas.")
        return
        
    # --- ¡NUEVO! PRE-CARGAR CAPACIDADES ESPECÍFICAS ---
    # Para evitar miles de consultas a la BD, cargamos las capacidades
    # de ProductoLinea en un diccionario para búsqueda rápida.
    
    productos_ids = [op.id_producto_id for op in ordenes_pendientes]
    lineas_ids = [linea.id_linea_produccion for linea in lineas]

    capacidades_qs = ProductoLinea.objects.filter(
        id_producto_id__in=productos_ids,
        id_linea_produccion_id__in=lineas_ids
    ).values(
        'id_producto_id', 
        'id_linea_produccion_id', 
        'cant_por_hora'
    )
    
    # Creamos el diccionario: (id_producto, id_linea) -> capacidad
    capacidades_lookup = {}
    for item in capacidades_qs:
        key = (item['id_producto_id'], item['id_linea_produccion_id'])
        capacidades_lookup[key] = item['cant_por_hora']
    
    print(f"Capacidades específicas cargadas: {len(capacidades_lookup)} reglas encontradas.")

    # --- 2. PRE-PROCESAR TAREAS (LÓGICA MEJORADA) ---
    # (Esta es la lógica con Lote Mínimo que ya implementaste)

    all_sub_tasks = [] 
    task_counter = 0

    for op in ordenes_pendientes:
        cantidad_pendiente = op.cantidad
        tareas_para_esta_op = [] 
        
        # ... (Tu lógica de bucle 'while' con TAMANO_LOTE_MINIMO va aquí) ...
        # ... (La copiaré de nuestra conversación anterior para que esté completa) ...
        
        while cantidad_pendiente > 0:
            if cantidad_pendiente >= TAMANO_LOTE_MINIMO:
                tamano_actual_lote = min(cantidad_pendiente, TAMANO_LOTE_TRABAJO)
                resto = cantidad_pendiente - tamano_actual_lote
                if 0 < resto < TAMANO_LOTE_MINIMO:
                    tamano_actual_lote += resto
                    cantidad_pendiente = 0
                else:
                    cantidad_pendiente -= tamano_actual_lote
                tareas_para_esta_op.append((op, tamano_actual_lote, task_counter))
                task_counter += 1
            else:
                if tareas_para_esta_op:
                    ultima_tarea = tareas_para_esta_op.pop() 
                    (op_padre, tamano_previo, id_previo) = ultima_tarea
                    nuevo_tamano = tamano_previo + cantidad_pendiente
                    tareas_para_esta_op.append((op_padre, nuevo_tamano, id_previo))
                else:
                    tareas_para_esta_op.append((op, cantidad_pendiente, task_counter))
                    task_counter += 1
                cantidad_pendiente = 0
        all_sub_tasks.extend(tareas_para_esta_op) 

    print(f"Planificando {len(ordenes_pendientes)} OPs divididas en {len(all_sub_tasks)} Tareas (OTs)...")

    # --- 3. CONFIGURAR EL MODELO CP-SAT ---
    
    model = cp_model.CpModel()
    tasks = {} 
    intervals_per_linea = defaultdict(list)
    all_end_vars = []

    # --- 4. CREAR VARIABLES Y RESTRICCIONES (EL NÚCLEO) ---

    for (op, tamano_lote, task_id) in all_sub_tasks:
        
        start_var = model.NewIntVar(0, HORIZONTE_MINUTOS, f'task_{task_id}_start')
        end_var = model.NewIntVar(0, HORIZONTE_MINUTOS, f'task_{task_id}_end')
        
        literals = []     
        alternatives = [] 

        # Obtenemos el ID del producto para esta tarea
        producto_id = op.id_producto_id

        # Crear una "alternativa" para cada línea de producción posible
        for i, linea in enumerate(lineas):
            
            # <-- CAMBIO 3: Lógica de Duración Actualizada
            
            # 1. Buscar la capacidad específica en nuestro diccionario
            lookup_key = (producto_id, linea.id_linea_produccion)
            capacidad_especifica = capacidades_lookup.get(lookup_key)

            # 2. Si no hay regla O la capacidad es 0, esta línea no puede hacer este producto.
            if not capacidad_especifica or capacidad_especifica <= 0:
                # print(f"Línea {linea.descripcion} NO PUEDE hacer Producto {producto_id}. Saltando.")
                continue # Salta esta línea

            # 3. (CRÍTICO) Calcular duración USANDO LA CAPACIDAD ESPECÍFICA
            try:
                duracion = math.ceil((tamano_lote / capacidad_especifica) * 60) # en minutos
            except ZeroDivisionError:
                continue # Seguridad extra

            # --- El resto de la lógica es igual ---
            
            lit = model.NewBoolVar(f'task_{task_id}_on_line_{linea.id_linea_produccion}')
            literals.append(lit)
            
            interval = model.NewOptionalIntervalVar(
                start_var, duracion, end_var, lit,
                f'task_{task_id}_interval_on_line_{linea.id_linea_produccion}'
            )
            
            alternatives.append((linea, interval, lit)) # (linea, interval_var, literal)
            intervals_per_linea[linea.id_linea_produccion].append(interval)

        # RESTRICCIÓN 1: "Exactly One"
        if not literals:
            # ¡Problema! Ninguna línea puede fabricar este producto.
            print(f"ADVERTENCIA: No se encontró NINGUNA línea capaz de producir el producto {op.id_producto.nombre} (OP: {op.id_orden_produccion}). Esta OP no se puede planificar.")
            # Opcional: podrías marcar la OP con un estado de "Error de Planificación"
            continue # Salta esta tarea
            
        model.AddExactlyOne(literals)

        tasks[task_id] = {
            'op': op,
            'tamano': tamano_lote,
            'start': start_var,
            'end': end_var,
            'alternatives': alternatives,
        }
        all_end_vars.append(end_var)


    # RESTRICCIÓN 2: "No Overlap"
    for linea_id, intervals in intervals_per_linea.items():
        model.AddNoOverlap(intervals)

    # --- 5. DEFINIR EL OBJETIVO ---
    
    if not all_end_vars:
        print("No se generaron variables de finalización. No hay nada que planificar.")
        return

    makespan = model.NewIntVar(0, HORIZONTE_MINUTOS, 'makespan')
    model.AddMaxEquality(makespan, all_end_vars)
    model.Minimize(makespan)

    # --- 6. RESOLVER EL MODELO ---
    
    print("Iniciando el solucionador CP-SAT...")
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    print(f"Estado de la solución: {solver.StatusName(status)}")

    # --- 7. GUARDAR RESULTADOS EN DJANGO ---

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        
        try:
            estado_ot_pendiente = EstadoOrdenTrabajo.objects.get(descripcion='Pendiente')
            estado_op_planificada = EstadoOrdenProduccion.objects.get(descripcion='Planificada')
        except Exception as e:
            print(f"ERROR: No se encontraron los estados 'Pendiente' o 'Planificada' en la BD. {e}")
            return
            
        hora_inicio_plan = timezone.now()
        ordenes_trabajo_a_crear = []
        ops_a_actualizar = set() 

        for task_id, task_data in tasks.items():
            for (linea, interval_var, literal) in task_data['alternatives']:
                if solver.Value(literal): 
                    start_minutos = solver.Value(task_data['start'])
                    end_minutos = solver.Value(task_data['end'])
                    
                    start_datetime = hora_inicio_plan + timezone.timedelta(minutes=start_minutos)
                    end_datetime = hora_inicio_plan + timezone.timedelta(minutes=end_minutos)

                    ot = OrdenDeTrabajo(
                        id_orden_produccion = task_data['op'],
                        id_linea_produccion = linea,
                        cantidad_programada = task_data['tamano'],
                        hora_inicio_programada = start_datetime,
                        hora_fin_programada = end_datetime,
                        id_estado_orden_trabajo = estado_ot_pendiente
                    )
                    ordenes_trabajo_a_crear.append(ot)
                    ops_a_actualizar.add(task_data['op'].id_orden_produccion)
                    break 
        
        try:
            with transaction.atomic():
                OrdenDeTrabajo.objects.bulk_create(ordenes_trabajo_a_crear)
                OrdenProduccion.objects.filter(
                    id_orden_produccion__in=ops_a_actualizar
                ).update(id_estado_orden_produccion=estado_op_planificada)
                
            print(f"¡Éxito! Se crearon {len(ordenes_trabajo_a_crear)} Órdenes de Trabajo.")
        
        except Exception as e:
            print(f"ERROR al guardar en la base de datos: {e}")

    else:
        print("No se encontró una solución óptima o factible.")