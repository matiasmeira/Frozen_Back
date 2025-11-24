# Asumo que OrdenProduccion tiene el campo 'cantidad_producida' (entregada, o ya consumida por OTs terminadas)
from datetime import date
from django.db import transaction
from datetime import timedelta, datetime
from django.db.models import F, Sum, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
import math
from ventas.models import OrdenVenta, EstadoVenta
from recetas.models import ProductoLinea
from produccion.models import EstadoOrdenProduccion, OrdenProduccion, CalendarioProduccion, OrdenProduccionPegging, EstadoOrdenTrabajo
# Constantes
HORAS_LABORABLES_POR_DIA = 16
DIAS_BUFFER_ENTREGA_PT = 1  # Días de buffer entre fin de producción y entrega al cliente



@transaction.atomic
def replanificar_ops_por_capacidad(
    fecha_simulada: date, 
    productos_a_replanificar_ids: list[int] = None, 
    dias_minimo_a_replanificar: int = 2
):
    """
    Replanifica OPs activas (En espera, Pendiente de inicio, Planificada)
    que tienen reservas en el calendario a partir de pasado mañana,
    ajustando las horas y fechas para la cantidad pendiente de producir.
    """
    
    hoy = fecha_simulada
    # Fecha mínima: pasado mañana (o el valor de dias_minimo_a_replanificar)
    fecha_minima_replanificacion = hoy + timedelta(days=dias_minimo_a_replanificar) 
    
    print(f"--- INICIANDO REPLANIFICACIÓN POR CAPACIDAD ({hoy}) ---")
    print(f"--- Foco: OPs con reservas a partir de: {fecha_minima_replanificacion} ---")

    # 1. Obtener Estados Necesarios
    try:
        estado_op_en_espera = EstadoOrdenProduccion.objects.get(descripcion="En espera")
        estado_op_pendiente_inicio = EstadoOrdenProduccion.objects.get(descripcion="Pendiente de inicio")
        estado_op_planificada = EstadoOrdenProduccion.objects.get(descripcion="Planificada") 
        estado_op_en_proceso = EstadoOrdenProduccion.objects.get(descripcion="En proceso")
        estado_ov_en_preparacion = EstadoVenta.objects.get(descripcion="En Preparación")
        # 🚨 Nuevo: Estado de OT finalizada para calcular lo ya producido
        estado_ot_finalizada = EstadoOrdenTrabajo.objects.get(descripcion__iexact="Completada") 
        estado_ot_pendiente = EstadoOrdenTrabajo.objects.get(descripcion__iexact="Pendiente")
        estado_ot_en_proceso = EstadoOrdenTrabajo.objects.get(descripcion__iexact="En progreso")
        # Ajusta "Completada" o "Finalizada" según tu BD
    except Exception as e:
        print(f"¡ERROR! No se pudieron obtener estados base: {e}")
        raise 
        
    estados_activos_para_replanificar = [
        estado_op_en_espera, 
        estado_op_pendiente_inicio, 
        estado_op_planificada,
        estado_op_en_proceso
    ]

    estados_ot_consumidos = [
        estado_ot_pendiente, 
        estado_ot_en_proceso, 
        estado_ot_finalizada
    ]
    
    # 2. Filtrar OPs Elegibles y Calcular Cantidad Pendiente
    ops_elegibles_query = OrdenProduccion.objects.filter(
        # Filtro A: Estado Activo (Incluye 'Planificada')
        id_estado_orden_produccion__in=estados_activos_para_replanificar,
        
        # Hemos quitado el filtro de calendario (reservas_calendario__fecha__gte) 
        # para que las OPs activas siempre sean elegibles.
        
    ).annotate(
        # 🚨 CÁLCULO CORREGIDO: (Utilizando el Related Name 'ordenes_de_trabajo')
        # Suma la 'cantidad_programada' de OTs en estados que ya no requieren planificación
        cantidad_producida_real=Coalesce(
            Sum(
                # Campo a sumar en el modelo OrdenTrabajo
                'ordenes_de_trabajo__cantidad_programada', 
                # Filtro para solo incluir OTs que ya están asignadas o completadas
                filter=Q(ordenes_de_trabajo__id_estado_orden_trabajo__in=estados_ot_consumidos)
            ), 
            0
        ), 
        # Calcular la cantidad que queda por planificar/producir
        cantidad_pendiente=F('cantidad') - F('cantidad_producida_real')
    ).filter(
        # Filtro C: Solo si aún les queda trabajo por hacer
        cantidad_pendiente__gt=0 
    ).select_related('id_producto').order_by('fecha_planificada').distinct()
        
    ops_a_replanificar = list(ops_elegibles_query)
    
    print(f"   > Encontradas {len(ops_a_replanificar)} OPs elegibles para replanificar.")
    
    for op in ops_a_replanificar:
        
        cantidad_a_producir_restante = op.cantidad_pendiente
        producto = op.id_producto
        
        # 3.1 Recalcular Horas Necesarias con la Capacidad ACTUAL (para la cantidad restante)
        capacidades_linea = ProductoLinea.objects.filter(id_producto=producto)
        cant_total_por_hora = capacidades_linea.aggregate(total=Sum('cant_por_hora'))['total'] or 0
        
        if cant_total_por_hora <= 0:
            print(f"     !ERROR: Capacidad 0/hr para {producto.nombre}. No se puede replanificar.")
            continue
            
        horas_necesarias_float = float(cantidad_a_producir_restante) / float(cant_total_por_hora)
        horas_necesarias_totales = math.ceil(horas_necesarias_float)

        print(f"\n   --- Replanificando OP {op.id_orden_produccion} ({producto.nombre}).")
        print(f"     > Cantidad restante: {cantidad_a_producir_restante} u. Nuevas horas requeridas: {horas_necesarias_totales} hs.")

        # 4. Modificación: Borrar solo las reservas a partir de la fecha mínima de replanificación
        # Obtener la fecha a partir de la cual se considerará 'futuro'
        fecha_borrado_minima = fecha_minima_replanificacion 
        
        CalendarioProduccion.objects.filter(
            id_orden_produccion=op,
            # 🚨 FILTRO CLAVE: Solo borra las reservas en o después de la fecha mínima
            fecha__gte=fecha_borrado_minima 
        ).delete()
        print(f"     > Eliminadas reservas a partir de: {fecha_borrado_minima}.")
        
        # 5. Determinar Fecha de Inicio Mínima (punto de partida)
        # El punto de partida es el máximo entre la fecha de replanificación forzosa (fecha_minima_replanificacion)
        # y la fecha planificada original de la OP (que actúa como restricción de inicio).
        fecha_inicio_minima_real = max(
            op.fecha_planificada.date(), 
            fecha_minima_replanificacion
        )
        
       # 6. Walk the Calendar (Buscar nuevo hueco)
        cantidad_pendiente_op = cantidad_a_producir_restante
        horas_pendientes = horas_necesarias_totales 
        fecha_a_buscar = fecha_inicio_minima_real
        
        while fecha_a_buscar.weekday() >= 5: fecha_a_buscar += timedelta(days=1) 

        fecha_inicio_real_asignada = None
        ultimo_dia_trabajado = None
        
        # 💡 CORRECCIÓN CRÍTICA: La lista debe inicializarse aquí
        reservas_a_crear_bulk = [] 
        
        # 🚨 AJUSTE DE CANTIDAD PENDIENTE (Implementado previamente)
        cantidad_reservada_no_borrada = CalendarioProduccion.objects.filter(
            id_orden_produccion=op,
            fecha__lt=fecha_borrado_minima 
        ).aggregate(
            total_reservado=Coalesce(Sum('cantidad_a_producir'), 0)
        )['total_reservado']

        cantidad_pendiente_op -= cantidad_reservada_no_borrada
        
        if cantidad_pendiente_op <= 0:
            print(f"     > Cantidad cubierta por reservas existentes no borradas. Saltando OP.")
            continue # <--- Esto hace que el código salte el resto del bucle y vaya a la siguiente OP
            
        horas_necesarias_float_nueva = float(cantidad_pendiente_op) / float(cant_total_por_hora)
        horas_pendientes = math.ceil(horas_necesarias_float_nueva) 
        horas_pendientes = max(0, horas_pendientes)
        
        # --- INICIO LÓGICA DE CALENDAR WALK ---
        while horas_pendientes > 0 and cantidad_pendiente_op > 0:
            horas_libres_cuello_botella = HORAS_LABORABLES_POR_DIA
            lineas_ids_producto = [c.id_linea_produccion_id for c in capacidades_linea]
            
            # Carga existente de OPs activas
            carga_existente = CalendarioProduccion.objects.filter(
                id_linea_produccion_id__in=lineas_ids_producto,
                fecha=fecha_a_buscar,
                id_orden_produccion__id_estado_orden_produccion__in=estados_activos_para_replanificar
            ).values('id_linea_produccion_id').annotate(
                total_reservado=Sum('horas_reservadas')
            ).values('id_linea_produccion_id', 'total_reservado')
            
            carga_por_linea = {c['id_linea_produccion_id']: float(c['total_reservado']) for c in carga_existente}

            for linea_id in lineas_ids_producto:
                carga_dia = carga_por_linea.get(linea_id, 0.0)
                horas_libres_linea = max(0, HORAS_LABORABLES_POR_DIA - carga_dia)
                horas_libres_cuello_botella = min(horas_libres_cuello_botella, horas_libres_linea)

            horas_libres_enteras = math.floor(horas_libres_cuello_botella)

            if horas_libres_enteras <= 0:
                fecha_a_buscar += timedelta(days=1)
                while fecha_a_buscar.weekday() >= 5: fecha_a_buscar += timedelta(days=1)
                continue
                    
            horas_a_reservar_hoy = min(horas_pendientes, horas_libres_enteras) 
            se_reservo_tiempo_en_fecha = False

            for cap_linea in capacidades_linea:
                cantidad_calculada_linea = round(float(horas_a_reservar_hoy) * float(cap_linea.cant_por_hora))
                cantidad_real_linea = min(cantidad_pendiente_op, cantidad_calculada_linea)

                if horas_a_reservar_hoy > 0 and cantidad_real_linea > 0:
                    se_reservo_tiempo_en_fecha = True 
                    
                    reservas_a_crear_bulk.append(
                        CalendarioProduccion(
                            id_orden_produccion=op, 
                            id_linea_produccion=cap_linea.id_linea_produccion,
                            fecha=fecha_a_buscar,
                            horas_reservadas=horas_a_reservar_hoy,
                            cantidad_a_producir=cantidad_real_linea
                        )
                    )
                    cantidad_pendiente_op -= cantidad_real_linea
                    
                    if cantidad_pendiente_op <= 0: break 
            
            if se_reservo_tiempo_en_fecha:
                horas_pendientes -= horas_a_reservar_hoy 
                ultimo_dia_trabajado = fecha_a_buscar
                if fecha_inicio_real_asignada is None:
                    fecha_inicio_real_asignada = fecha_a_buscar
            
            if cantidad_pendiente_op <= 0:
                horas_pendientes = 0 
                break

            fecha_a_buscar += timedelta(days=1)
            while fecha_a_buscar.weekday() >= 5: fecha_a_buscar += timedelta(days=1)
            
            if cantidad_pendiente_op > 0:
                # Recalcular horas pendientes en base a la cantidad restante
                horas_necesarias_float_nueva = float(cantidad_pendiente_op) / float(cant_total_por_hora)
                horas_pendientes = math.ceil(horas_necesarias_float_nueva) 
        # --- FIN LÓGICA DE CALENDAR WALK ---

        # 7. Guardar OP y Calendario Nuevos
        if fecha_inicio_real_asignada is None:
            fecha_inicio_real_asignada = fecha_inicio_minima_real

        fecha_fin_real_asignada = ultimo_dia_trabajado if ultimo_dia_trabajado else fecha_inicio_real_asignada
        while fecha_fin_real_asignada.weekday() >= 5:
             fecha_fin_real_asignada -= timedelta(days=1)
        if fecha_fin_real_asignada < fecha_inicio_real_asignada:
            fecha_fin_real_asignada = fecha_inicio_real_asignada

        op.fecha_planificada = timezone.make_aware(datetime.combine(fecha_inicio_real_asignada, datetime.min.time()))
        op.fecha_fin_planificada = fecha_fin_real_asignada
        # No cambiamos el estado aquí, se mantiene 'Planificada', 'En espera' o 'Pendiente de inicio'
        op.save(update_fields=['fecha_planificada', 'fecha_fin_planificada'])
        
        CalendarioProduccion.objects.bulk_create(reservas_a_crear_bulk)
        
        print(f"     ✅ OP {op.id_orden_produccion} REPLANIFICADA. Nuevo rango: {op.fecha_planificada.date()} a {op.fecha_fin_planificada}.")

        # 8. Revisar y Desplazar OVs Vinculadas
        peggings = OrdenProduccionPegging.objects.filter(id_orden_produccion=op).select_related('id_orden_venta_producto__id_orden_venta')

        for peg in peggings:
            ov = peg.id_orden_venta_producto.id_orden_venta
            dias_totales_margen = DIAS_BUFFER_ENTREGA_PT + 1
            
            # 1. Calcular la nueva fecha sugerida de entrega (objeto datetime.date)
            nueva_fecha_entrega_sugerida_date = op.fecha_fin_planificada + timedelta(days=dias_totales_margen)
            
            # Asegurar que el día sugerido sea laborable
            while nueva_fecha_entrega_sugerida_date.weekday() >= 5:
                nueva_fecha_entrega_sugerida_date += timedelta(days=1) 

            # 2. Obtener la fecha de entrega original de la OV como DATE
            # Esto resuelve el TypeError (date vs datetime), ya que ov.fecha_entrega es un DateTimeField
            fecha_entrega_ov_original_date = ov.fecha_entrega.date() 
            
            # 3. Determinar si hay un retraso respecto a la fecha original
            hay_retraso = nueva_fecha_entrega_sugerida_date > fecha_entrega_ov_original_date
            
            # 4. Determinar si hay un avance respecto a la fecha original
            hay_avance = nueva_fecha_entrega_sugerida_date < fecha_entrega_ov_original_date

            # 5. La OV debe reflejar el nuevo pronóstico, sea un avance o un retraso.
            ov.fecha_entrega = nueva_fecha_entrega_sugerida_date
            
            campos_a_actualizar = ['fecha_entrega']

            if hay_retraso:
                # Se activa la alerta y se actualiza el estado
                print(f"     🚨 ¡ALERTA! OV {ov.id_orden_venta} desplazada a {nueva_fecha_entrega_sugerida_date}. (RETRASO)")
                ov.id_estado_venta = estado_ov_en_preparacion 
                campos_a_actualizar.append('id_estado_venta')
            elif hay_avance:
                # Solo se registra el avance, el estado se deja como está
                print(f"     🎉 ¡AVANCE! OV {ov.id_orden_venta} adelantada a {nueva_fecha_entrega_sugerida_date}.")

            # 6. Guardar los cambios en la OV
            ov.save(update_fields=campos_a_actualizar)

    print("\n--- REPLANIFICACIÓN POR CAPACIDAD FINALIZADA ---")
    return True