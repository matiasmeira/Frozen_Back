from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, F, Count
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek, ExtractYear, ExtractDay
from datetime import datetime, timedelta # Asegúrate de importar timedelta si usas el helper


# --- ¡IMPORTANTE! ---
# Ahora importas los modelos desde sus apps correspondientes
from produccion.models import OrdenDeTrabajo, NoConformidad, EstadoOrdenTrabajo, LineaProduccion, estado_linea_produccion
from stock.models import LoteProduccionMateria
from productos.models import Producto
from materias_primas.models import MateriaPrima
from django.db.models import Sum, F, Count, Value, CharField, FloatField, Q, DateField, Case, When, BooleanField, ExpressionWrapper, DurationField
from django.db.models.functions import TruncDate, Coalesce, Cast

from django.utils import timezone


# Helper para parsear fechas (puedes mejorarlo)
def parsear_fechas(request):
    """Obtiene fecha_desde y fecha_hasta de los query params."""
    # Valores por defecto (ej. últimos 30 días) - ¡Ajústalos a tu gusto!
    fecha_hasta_str = request.query_params.get('fecha_hasta', datetime.now().strftime('%Y-%m-%d'))
    # Por defecto, 30 días antes de la fecha_hasta
    fecha_desde_str = request.query_params.get('fecha_desde', 
        (datetime.strptime(fecha_hasta_str, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d'))

    try:
        # Asegúrate de incluir el final del día en fecha_hasta para los filtros __range
        fecha_desde = datetime.strptime(fecha_desde_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        fecha_hasta = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        return fecha_desde, fecha_hasta
    except ValueError:
        # Manejo de error si las fechas no son válidas
        return None, None


# --- VISTAS DE REPORTES ---

### 1. Reportes de Producción

class ReporteProduccionDiaria(APIView):
    """
    API para gráfico de serie temporal (ej. líneas apiladas).
    Devuelve la cantidad total por día Y POR ESTADO.
    
    Usa 'hora_inicio_programada' para filtrar y agrupar por fecha.
    
    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        # 1. Filtramos por RANGO DE FECHAS usando la fecha programada
        query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta)
        ).select_related(
            'id_estado_orden_trabajo' # Optimización para joins
        )

        # 2. Agregación: Agrupar por día Y por estado
        reporte = query.annotate(
            # Trunca la fecha programada a solo la fecha (día)
            fecha=TruncDate('hora_inicio_programada') 
        ).values(
            'fecha', # Agrupar por la fecha truncada
            # Maneja el caso de que el estado sea NULO
            estado=Coalesce(
                F('id_estado_orden_trabajo__descripcion'), 
                Value('Sin Estado'), 
                output_field=CharField()
            )
        ).annotate(
            # Sumamos la cantidad programada, ya que 'producida' puede ser Nulo
            total_cantidad=Sum('cantidad_programada')
        ).order_by('fecha', 'estado') # Importante para gráficos

        """
        Salida de Ejemplo:
        [
            {"fecha": "2025-10-20", "estado": "Pendiente", "total_cantidad": 500},
            {"fecha": "2025-10-20", "estado": "En Progreso", "total_cantidad": 300},
            {"fecha": "2025-10-21", "estado": "Completada", "total_cantidad": 1500},
            {"fecha": "2025-10-21", "estado": "Pendiente", "total_cantidad": 400}
        ]
        """
        return Response(reporte)


class ReporteProduccionPorProducto(APIView):
    """
    API para gráfico de torta o barras (Pie chart / Bar chart).
    Devuelve el total por producto Y POR ESTADO en un rango de fechas.

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # 1. Filtramos por RANGO DE FECHAS usando la fecha programada
        query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta)
        ).select_related(
            'id_orden_produccion__id_producto', # Optimización
            'id_estado_orden_trabajo'          # Optimización
        )

        # 2. Agregación: Agrupar por producto Y por estado
        reporte = query.values(
            # Agrupar por el nombre/descripción del producto
            producto_nombre=Coalesce(
                F('id_orden_produccion__id_producto__descripcion'),
                Value('Producto Desconocido'),
                output_field=CharField()
            ),
            # Agrupar por la descripción del estado
            estado=Coalesce(
                F('id_estado_orden_trabajo__descripcion'),
                Value('Sin Estado'),
                output_field=CharField()
            )
        ).annotate(
            # Sumamos la cantidad programada
            total_cantidad=Sum('cantidad_programada')
        ).order_by('producto_nombre', 'estado') 

        """
        Salida de Ejemplo:
        [
            {"producto_nombre": "Producto A", "estado": "Pendiente", "total_cantidad": 500},
            {"producto_nombre": "Producto A", "estado": "Completada", "total_cantidad": 4000},
            {"producto_nombre": "Producto B", "estado": "En Progreso", "total_cantidad": 800}
        ]
        """
        return Response(reporte)


### 2. Reporte de Consumo

class ReporteConsumoMateriaPrima(APIView):
    """
    API para gráfico de barras o serie temporal.
    Devuelve la cantidad total de materia prima consumida.
    Usamos 'LoteProduccionMateria' que registra el consumo real.

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # Filtramos por la fecha de producción del lote que consumió la materia
        query = LoteProduccionMateria.objects.filter(
            id_lote_produccion__fecha_produccion__range=(fecha_desde, fecha_hasta)
        )

        # Agregación: Agrupar por materia prima y sumar
        reporte = query.values(
            # Accedemos a la descripción de la materia prima
            materia_prima_nombre=F('id_lote_materia_prima__id_materia_prima__descripcion')
        ).annotate(
            total_consumido=Sum('cantidad_usada')
        ).order_by('-total_consumido')

        # Salida: [{"materia_prima_nombre": "Acero", "total_consumido": 10000}, ...]
        return Response(reporte)


### 3. Reporte de Desperdicio

class ReporteDesperdicioPorCausa(APIView):
    """
    API para gráfico de torta o barras (Pareto).
    Muestra el total desperdiciado agrupado por la causa estandarizada (TipoNoConformidad).

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # 1. FILTRADO: Usamos la fecha de creación de la Orden de Producción (OP), 
        #    accediendo a través de la Orden de Trabajo (OT).
        query = NoConformidad.objects.filter(
            # Cadena de FKs: NC -> OT -> OP -> fecha_creacion
            id_orden_trabajo__id_orden_produccion__fecha_creacion__range=(fecha_desde, fecha_hasta)
        )

        # 2. AGRUPACIÓN: Agrupar por el Tipo de No Conformidad (causa estandarizada)
        reporte = query.values(
            # Agrupamos por el nombre del TipoNoConformidad
            causa=F('id_tipo_no_conformidad__nombre') 
        ).annotate(
            total_desperdiciado=Sum('cant_desperdiciada')
        ).order_by('-total_desperdiciado')

        # Salida: [{"causa": "Falla de Empaque", "total_desperdiciado": 150}, ...]
        return Response(reporte)


class ReporteDesperdicioPorProducto(APIView):
    """
    API para gráfico de barras.
    Muestra el total desperdiciado agrupado por producto,
    utilizando la cadena de FK: NoConformidad -> OrdenDeTrabajo -> OrdenProduccion -> Producto.

    Filtros (Query Params):
    - ?fecha_desde=YYYY-MM-DD
    - ?fecha_hasta=YYYY-MM-DD
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido."}, status=400)

        # 1. FILTRADO: Usamos la fecha_creacion de la Orden de Producción,
        #    accediendo a través de la Orden de Trabajo.
        query = NoConformidad.objects.filter(
            # Cadena de FKs: NC -> OT -> OP -> fecha_creacion
            id_orden_trabajo__id_orden_produccion__fecha_creacion__range=(fecha_desde, fecha_hasta)
        )

        # 2. AGRUPACIÓN: Agrupar por producto, accediendo a la descripción del producto
        #    a través de la Orden de Producción.
        reporte = query.values(
            # Cadena de FKs: NC -> OT -> OP -> Producto -> descripción
            producto_nombre=F('id_orden_trabajo__id_orden_produccion__id_producto__descripcion')
        ).annotate(
            total_desperdiciado=Sum('cant_desperdiciada')
        ).order_by('-total_desperdiciado')

        # Salida: [{"producto_nombre": "Producto B", "total_desperdiciado": 80}, ...]
        return Response(reporte)
    

class ReporteTasaDeDesperdicio(APIView):
    """
    Calcula la Tasa de Desperdicio (Total Desperdiciado / Total Programado de OTs Completadas)
    basándose ÚNICAMENTE en las Órdenes de Trabajo que han sido Completadas.
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        rango_fecha_filtro = (fecha_desde, fecha_hasta)
        
        # --- 0. Definir el conjunto base de OTs Completadas en el rango de fecha ---
        # Filtramos las OTs que terminaron dentro del rango o que iniciaron en el rango y se completaron
        ots_completadas = OrdenDeTrabajo.objects.filter(
            id_estado_orden_trabajo__descripcion='Completada',  # Filtro esencial
            hora_inicio_programada__range=rango_fecha_filtro
        )

        # 1. CALCULAR EL TOTAL DESPERDICIADO (NUMERADOR)
        # 🚨 CAMBIO: Filtramos las No Conformidades que pertenecen a las OTs COMPLETADAS
        total_desperdiciado_query = NoConformidad.objects.filter(
            # Filtra las NCs que tienen una OT cuya hora_inicio_programada cae en el rango
            id_orden_trabajo__hora_inicio_programada__range=rango_fecha_filtro,
            # Filtra las NCs cuya OT está en estado 'Completada'
            id_orden_trabajo__id_estado_orden_trabajo__descripcion='Completada' 
        ).aggregate(
            total_desperdiciado=Coalesce(
                Sum('cant_desperdiciada'), 
                Value(0.0), 
                output_field=FloatField() 
            )
        )
        total_desperdiciado = total_desperdiciado_query.get('total_desperdiciado', 0.0)

        # 2. CALCULAR EL TOTAL PROGRAMADO (DENOMINADOR)
        # 🚨 CAMBIO: Sumamos SOLO la cantidad programada de las OTs Completadas
        total_producido_query = ots_completadas.aggregate(
            total_programado=Coalesce(
                Sum('cantidad_programada'), 
                Value(0.0),
                output_field=FloatField() 
            )
        )
        total_programado = total_producido_query.get('total_programado', 0.0)
        
        # 3. CÁLCULO DE LA TASA
        tasa_desperdicio = 0.0
        
        if total_programado > 0:
            # Tasa de desperdicio = (Desperdiciado total / Programado en OTs completadas) * 100
            tasa_desperdicio = (total_desperdiciado / total_programado) * 100.0

        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "total_programado_completado": total_programado,
            "total_desperdiciado": total_desperdiciado,
            "tasa_desperdicio_porcentaje": round(tasa_desperdicio, 2)
        }

        return Response(resultado)
    

class ReporteCumplimientoPlan(APIView):
    """
    API para calcular el Porcentaje de Cumplimiento de Adherencia (PCA) por Cantidad (Volumen).
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request) 
        
        if fecha_desde is None or fecha_hasta is None:
            return Response({"error": "Debe proporcionar fechas válidas (desde, hasta) en formato YYYY-MM-DD."}, status=400)
        
        # 1. CALCULAR EL TOTAL PLANIFICADO (DENOMINADOR)
        total_planificado_query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta)
        ).aggregate(
            total_planificado=Coalesce(Sum('cantidad_programada'), Value(0.0), output_field=FloatField())
        )
        total_planificado = total_planificado_query.get('total_planificado', 0.0)

        # 2. CALCULAR LA CANTIDAD CUMPLIDA A TIEMPO (NUMERADOR)
        ots_anotadas = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta) 
        ).annotate(
            dia_fin_real=F('hora_fin_real__date'),
            dia_fin_programado=F('hora_fin_programada__date')
        ).annotate(
            cumplio_fecha=Case(
                When(
                    dia_fin_real=F('dia_fin_programado'),
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        
        total_cumplido_query = ots_anotadas.filter(
            cumplio_fecha=True, 
            id_estado_orden_trabajo__descripcion='Completada', 
            hora_fin_real__isnull=False, 
        ).aggregate(
            total_cumplido_adherencia=Coalesce(
                Sum('cantidad_producida'), 
                Value(0.0),
                output_field=FloatField()
            )
        )
        total_cumplido = total_cumplido_query.get('total_cumplido_adherencia', 0.0)

        # 3. CÁLCULO DEL PCA y Respuesta
        pcp = 0.0
        if total_planificado > 0:
            pcp = (total_cumplido / total_planificado) * 100.0

        # CORRECCIÓN DE ERROR: Usar timedelta directamente
        fecha_fin_respuesta = (fecha_hasta - timedelta(days=1)).strftime('%Y-%m-%d')
        
        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_fin_respuesta,
            "total_planificado": total_planificado,
            "total_cantidad_cumplida_a_tiempo": total_cumplido,
            "porcentaje_cumplimiento_adherencia": round(pcp, 2)
        }

        return Response(resultado)
    
class ReporteCumplimientoPlanMensual(APIView):
    """
    API para calcular el Porcentaje de Cumplimiento de Adherencia (PCA) agrupado por mes.
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        
        if fecha_desde is None or fecha_hasta is None:
            return Response({"error": "Debe proporcionar fechas válidas (desde, hasta) en formato YYYY-MM-DD."}, status=400)

        # 1. ANOTAR LAS OTs con el mes, año y si cumplió la fecha programada
        ots_base = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta),
        ).annotate(
            # Campo para agrupar: Mes de la hora de inicio programada
            mes_reporte=TruncMonth('hora_inicio_programada'),
            
            # Campos para verificar cumplimiento
            dia_fin_real=F('hora_fin_real__date'),
            dia_fin_programado=F('hora_fin_programada__date')
        ).annotate(
            cumplio_fecha=Case(
                When(
                    # Criterio de cumplimiento: Día de fin real <= Día de fin programado
                    dia_fin_real__lte=F('dia_fin_programado'), 
                    # El estado debe ser 'Completada' y la hora_fin_real no nula
                    id_estado_orden_trabajo__descripcion='Completada',
                    hora_fin_real__isnull=False,
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        
        # 2. AGREGAR Y AGRUPAR POR MES
        resultados_agrupados = ots_base.values('mes_reporte').annotate(
            # Denominador: Total planificado para ese mes
            total_planificado=Coalesce(Sum('cantidad_programada'), Value(0.0), output_field=FloatField()),
            
            # Numerador: Suma de la cantidad_programada SOLO de las que cumplieron
            total_cumplido_adherencia=Coalesce(
                Sum(
                    Case(
                        When(cumplio_fecha=True, then='cantidad_producida'),
                        default=Value(0),
                        output_field=FloatField()
                    )
                ), 
                Value(0.0),
                output_field=FloatField()
            )
        ).order_by('mes_reporte')
        
        # 3. Formatear resultados y calcular PCA por mes
        reporte = []
        for item in resultados_agrupados:
            planificado = item['total_planificado']
            cumplido = item['total_cumplido_adherencia']
            
            # Cálculo del PCA mensual
            pca_mensual = (cumplido / planificado * 100) if planificado > 0 else 0.0
            
            reporte.append({
                "mes": item['mes_reporte'].strftime('%Y-%m'), 
                "total_planificado": round(planificado, 2),
                "total_cumplido_adherencia": round(cumplido, 2),
                "pca_mensual": round(pca_mensual, 2)
            })
            
        return Response(reporte)
    
class ReporteCumplimientoPlanSemanal(APIView):
    """
    API para calcular el Porcentaje de Cumplimiento de Adherencia (PCA) agrupado por semana.
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        
        if fecha_desde is None or fecha_hasta is None:
            return Response({"error": "Debe proporcionar fechas válidas (desde, hasta) en formato YYYY-MM-DD."}, status=400)

        # 1. ANOTAR LAS OTs con la semana y si cumplió la fecha programada
        ots_base = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=(fecha_desde, fecha_hasta),
        ).annotate(
            # Campo para agrupar: Trunca a la fecha de inicio de la semana
            semana_reporte=TruncWeek('hora_inicio_programada'),
            
            # Campos para verificar cumplimiento
            dia_fin_real=F('hora_fin_real__date'),
            dia_fin_programado=F('hora_fin_programada__date')
        ).annotate(
            cumplio_fecha=Case(
                When(
                    # Criterio de cumplimiento: Día de fin real <= Día de fin programado
                    dia_fin_real__lte=F('dia_fin_programado'), 
                    # El estado debe ser 'Completada' y la hora_fin_real no nula
                    id_estado_orden_trabajo__descripcion='Completada',
                    hora_fin_real__isnull=False,
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )
        
        # 2. AGREGAR Y AGRUPAR POR SEMANA
        resultados_agrupados = ots_base.values('semana_reporte').annotate(
            # Denominador: Total planificado para esa semana
            total_planificado=Coalesce(Sum('cantidad_programada'), Value(0.0), output_field=FloatField()),
            
            # Numerador: Suma de la cantidad_programada SOLO de las que cumplieron
            total_cumplido_adherencia=Coalesce(
                Sum(
                    Case(
                        When(cumplio_fecha=True, then='cantidad_producida'),
                        default=Value(0),
                        output_field=FloatField()
                    )
                ), 
                Value(0.0),
                output_field=FloatField()
            )
        ).order_by('semana_reporte')
        
        # 3. Formatear resultados y calcular PCA por semana
        reporte = []
        for item in resultados_agrupados:
            planificado = item['total_planificado']
            cumplido = item['total_cumplido_adherencia']
            
            # Cálculo del PCA semanal
            pca_semanal = (cumplido / planificado * 100) if planificado > 0 else 0.0
            
            # El resultado de TruncWeek es un objeto datetime, lo formateamos a YYYY-MM-DD (fecha de inicio de la semana)
            reporte.append({
                "semana_inicio": item['semana_reporte'].strftime('%Y-%m-%d'),
                "total_planificado": round(planificado, 2),
                "total_cumplido_adherencia": round(cumplido, 2),
                "pca_semanal": round(pca_semanal, 2)
            })
            
        return Response(reporte)
    
class LineasProduccionYEstado(APIView):
    """
    Devuelve la lista de TODAS las líneas de producción, mostrando su nombre 
    y la descripción de su estado actual, sin importar si están activas o no.
    """
    def get(self, request, *args, **kwargs):
        
        # Obtenemos TODAS las líneas de producción
        lineas = LineaProduccion.objects.all().values(
            # Proyectamos el nombre de la línea
            nombre_linea=F('descripcion'), 
            
            # Obtenemos la descripción del estado a través de la clave foránea.
            # Usamos Coalesce para manejar si, hipotéticamente, el estado fuera NULL
            estado_actual=Coalesce(
                F('id_estado_linea_produccion__descripcion'), 
                Value('Sin Estado Asignado'),
                output_field=CharField()
            )
        ).order_by('nombre_linea')
        
        """
        Salida de Ejemplo:
        [
            {"nombre_linea": "Línea Ensamblaje A", "estado_actual": "Activa"},
            {"nombre_linea": "Línea Corte Láser", "estado_actual": "Parada"},
            {"nombre_linea": "Línea Empaque", "estado_actual": "Mantenimiento"}
        ]
        """
        return Response(list(lineas))
    
class ReporteFactorCalidadOEE(APIView):
    """
    API para calcular el Factor de Calidad del OEE.
    
    AHORA UTILIZA: Producción Bruta (la cantidad total fabricada) como el volumen total.
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        rango_fecha_filtro = (fecha_desde, fecha_hasta)
        
        # 1. CALCULAR LA PRODUCCIÓN BRUTA TOTAL (VOLUMEN REAL) - Denominador
        # Filtra OTs completadas y en el rango, y suma el campo 'produccion_bruta'.
        produccion_bruta_total_query = OrdenDeTrabajo.objects.filter(
            hora_inicio_programada__range=rango_fecha_filtro,
            id_estado_orden_trabajo__descripcion='Completada'
        ).aggregate(
            produccion_bruta_total=Coalesce(
                Sum('produccion_bruta'),  # ⬅️ CAMBIO CLAVE: Usamos el nuevo campo
                Value(0.0),
                output_field=FloatField()
            )
        )
        produccion_bruta_total = produccion_bruta_total_query.get('produccion_bruta_total', 0.0)

        # 2. CALCULAR EL TOTAL DESPERDICIADO (PÉRDIDAS) - Numerador (Mantenido)
        # Filtra el desperdicio asociado a OTs completadas en el rango.
        total_desperdiciado_query = NoConformidad.objects.filter(
            id_orden_trabajo__hora_inicio_programada__range=rango_fecha_filtro,
            id_orden_trabajo__id_estado_orden_trabajo__descripcion='Completada'
        ).aggregate(
            total_desperdiciado=Coalesce(
                Sum('cant_desperdiciada'), 
                Value(0.0), 
                output_field=FloatField()
            )
        )
        total_desperdiciado = total_desperdiciado_query.get('total_desperdiciado', 0.0)

        # 3. CÁLCULO DEL FACTOR CALIDAD
        factor_calidad = 0.0
        # 🛑 CORRECCIÓN: Inicializar la variable aquí para que siempre exista.
        piezas_buenas_seguro = 0.0 
        
        if produccion_bruta_total > 0:
            # Piezas Buenas = Producción Bruta Total - Total Desperdiciado
            piezas_buenas = produccion_bruta_total - total_desperdiciado
            
            # Se calcula la versión segura dentro del IF
            piezas_buenas_seguro = max(0, piezas_buenas) 
            
            # Factor Calidad = (Piezas Buenas / Producción Bruta Total) * 100
            factor_calidad = (piezas_buenas_seguro / produccion_bruta_total) * 100.0
        
        # 4. PREPARAR RESPUESTA
        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "produccion_bruta_total": produccion_bruta_total,
            "total_desperdiciado": total_desperdiciado,
            "piezas_buenas_calculadas": piezas_buenas_seguro, # <--- Ahora la variable existe
            "factor_calidad_oee": round(factor_calidad, 2)
        }

        return Response(resultado)
    

class ReporteDisponibilidadAjustada(APIView):
    """
    API que calcula el indicador de Disponibilidad Ajustada (Eficacia Operativa).
    
    Características clave:
    1. Ignora el retraso en el inicio.
    2. Penaliza las pausas/paradas registradas.
    3. Penaliza al 100% las OTs que terminaron un día después de lo programado.
    """
    def get(self, request, *args, **kwargs):
        fecha_desde, fecha_hasta = parsear_fechas(request)
        if fecha_desde is None:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        rango_fecha_filtro = (fecha_desde, fecha_hasta)
        
        # 1. Conjunto Base: OTs Completadas y con tiempos reales en el rango
        ots_base = OrdenDeTrabajo.objects.filter(
            id_estado_orden_trabajo__descripcion='Completada',
            hora_inicio_real__isnull=False,
            hora_fin_real__isnull=False,
            hora_inicio_programada__range=rango_fecha_filtro
        )
        
        # 2. Anotar el Tiempo de Carga Ajustado y el indicador de penalización
        ots_anotadas = ots_base.annotate(
            # 2.1. Tiempo de Carga Ajustado (Tiempo Transcurrido Bruto)
            tiempo_carga_ajustado_td=ExpressionWrapper(
                F('hora_fin_real') - F('hora_inicio_real'),
                output_field=DurationField()
            ),
            
            # 2.2. Diferencia de Fechas (DurationField)
            retraso_fecha_td=ExpressionWrapper(
                F('hora_fin_real__date') - F('hora_fin_programada__date'),
                output_field=DurationField()
            ),
            
        ).annotate(
            # 🚨 CORRECCIÓN: Indicador de Tarde: Verificamos si la duración es mayor a 0 segundos (es decir, al menos 1 día)
            termino_tarde=Case(
                When(
                    # Filtra directamente sobre la Duración, que es un objeto seguro para comparación > 0 segundos
                    retraso_fecha_td__gt=timedelta(seconds=0), 
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            )
        )

        # 3. Agregación de Totales (Sumas)
        reporte_agregado = ots_anotadas.aggregate(
            # 3.1. Total de Pausas (Pérdidas por Paradas) en minutos
            total_perdida_pausas_minutos=Coalesce(
                Sum('pausas__duracion_minutos'),
                Value(0),
                output_field=FloatField()
            ),
            
            # 3.2. Suma del Tiempo de Carga Ajustado Total (Denominador Bruto) en segundos
            total_tiempo_carga_segundos=Coalesce(
                Sum(F('tiempo_carga_ajustado_td')),
                Value(timedelta(0)),
                output_field=DurationField()
            ),
            
            # 3.3. TIEMPO PERDIDO POR DISCIPLINIDAD DE FECHA (Penalización al 100% de la OT tardía)
            total_penalizado_tarde_segundos=Coalesce(
                Sum(
                    Case(
                        When(termino_tarde=True, then='tiempo_carga_ajustado_td'),
                        default=Value(timedelta(0)),
                        output_field=DurationField()
                    )
                ),
                Value(timedelta(0)),
                output_field=DurationField()
            )
        )

        # 4. Cálculo final y Conversión a Minutos
        total_tiempo_carga_segundos = reporte_agregado['total_tiempo_carga_segundos'].total_seconds()
        total_tiempo_carga_minutos = total_tiempo_carga_segundos / 60.0
        
        total_perdida_pausas = reporte_agregado['total_perdida_pausas_minutos']
        total_penalizado_tarde = reporte_agregado['total_penalizado_tarde_segundos'].total_seconds() / 60.0

        # Pérdidas Totales = Pausas + Penalización por Tarde
        perdidas_totales = total_perdida_pausas + total_penalizado_tarde

        # Tiempo Operación Neto = Tiempo Carga Bruto - Pérdidas Totales
        tiempo_operacion_neto = total_tiempo_carga_minutos - perdidas_totales
        
        # Tasa de Disponibilidad Ajustada
        disponibilidad_ajustada = 0.0
        if total_tiempo_carga_minutos > 0:
            disponibilidad_ajustada = (tiempo_operacion_neto / total_tiempo_carga_minutos) * 100.0
            
        resultado = {
            "fecha_desde": fecha_desde.strftime('%Y-%m-%d'),
            "fecha_hasta": fecha_hasta.strftime('%Y-%m-%d'),
            "total_tiempo_ejecucion_minutos": round(total_tiempo_carga_minutos, 2),
            "total_tiempo_perdido_pausas_minutos": round(total_perdida_pausas, 2),
            "total_penalizado_por_fecha_minutos": round(total_penalizado_tarde, 2),
            "total_tiempo_operacion_neto_minutos": round(tiempo_operacion_neto, 2),
            "disponibilidad_ajustada_porcentaje": round(disponibilidad_ajustada, 2)
        }

        return Response(resultado)