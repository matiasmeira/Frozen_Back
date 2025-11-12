from django.shortcuts import render

# Create your views here.
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from compras.models import OrdenCompra
from produccion.models import OrdenProduccion
from planificacion.planner_service import ejecutar_planificador, replanificar_produccion
from planificacion.planificador import ejecutar_planificacion_diaria_mrp
import traceback
from datetime import timedelta, date, datetime
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import F, Case, When, Value, CharField
from django.utils import timezone
from datetime import timedelta, datetime

@api_view(['POST']) # Define que esta vista solo acepta POST
def ejecutar_planificacion_view(request):
    """
    Endpoint para disparar el script de planificación de Google OR-Tools.
    """
    try:
        print("Iniciando planificador desde el endpoint /planificacion/...")
        
        # Llama a tu función principal del planner_service
        ejecutar_planificador() 
        
        return Response(
            {"mensaje": "Planificador ejecutado exitosamente. Se crearon las Órdenes de Trabajo."}, 
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        print(f"Error al ejecutar el planificador desde API: {str(e)}")
        return Response(
            {"error": f"Ocurrió un error al ejecutar el planificador: {str(e)}"}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

@api_view(['POST']) # Define que esta vista solo acepta POST
def replanificar_produccion_view(request):
    """
    Endpoint para disparar el script de planificación de Google OR-Tools.
    """
    try:
        print("Iniciando planificador desde el endpoint /planificacion/...")
        
        # Llama a tu función principal del planner_service
        replanificar_produccion() 
        
        return Response(
            {"mensaje": "Planificador ejecutado exitosamente. Se crearon las Órdenes de Trabajo."}, 
            status=status.HTTP_200_OK
        )
    
    except Exception as e:
        print(f"Error al ejecutar el planificador desde API: {str(e)}")
        return Response(
            {"error": f"Ocurrió un error al ejecutar el planificador: {str(e)}"}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    



@api_view(['POST'])
def ejecutar_planificador_view(request):
    """
    Endpoint para disparar manualmente el Planificador MRP Diario.
    
    Opcionalmente, acepta un JSON para simular una fecha:
    {
        "fecha": "YYYY-MM-DD"
    }
    """
    
    fecha_a_usar = None
    fecha_enviada = request.data.get('fecha')

    if fecha_enviada:
        # Si el usuario envía una fecha, la usamos para simular
        try:
            fecha_a_usar = datetime.strptime(fecha_enviada, "%Y-%m-%d").date()
            print(f"Simulando ejecución del planificador para la fecha: {fecha_a_usar}")
        except ValueError:
            return Response(
                {"status": "error", "message": "Formato de fecha inválido. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        # Si no se envía fecha, usa el día real (para producción)
        fecha_a_usar = timezone.localdate()
        print(f"Ejecutando planificador para la fecha actual: {fecha_a_usar}")

    try:
       # --- INICIO DE LÓGICA MODIFICADA ---
        
        # 1. Primero, corre el MRP para determinar QUÉ producir y CUÁNDO (Crea OPs "Pendiente de inicio")
        print("\n--- INICIANDO FASE 1: MRP (Planificación de Materiales) ---")
        ejecutar_planificacion_diaria_mrp(fecha_a_usar)
        print("--- FASE 1: MRP COMPLETADA ---")

        # 2. Segundo, corre el Scheduler para planificar el día de MAÑANA
        #    (Toma las OPs "Pendiente de inicio" para mañana y crea las OTs)
        print("\n--- INICIANDO FASE 2: SCHEDULER (Planificación de Taller) ---")
        # Nota: El scheduler usa 'timezone.localdate() + 1' internamente,
        # así que no necesita la fecha simulada (a menos que quieras cambiarlo).
        ejecutar_planificador(fecha_a_usar)
        print("--- FASE 2: SCHEDULER COMPLETADA ---")
        
        # --- FIN DE LÓGICA MODIFICADA ---
        print("Planificador MRP ejecutado exitosamente desde la API.")
        return Response(
            {"status": "ok", "message": f"Planificador MRP ejecutado para {fecha_a_usar}." },
            status=status.HTTP_200_OK
        )
    except Exception as e:
        # Captura cualquier error que ocurra durante la planificación
        print(f"ERROR al ejecutar planificador desde API: {e}")
        traceback.print_exc() # Imprime el error completo en la consola del servidor
        return Response(
            {"status": "error", "message": f"Error al ejecutar el planificador: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
class CalendarioPlanificacionView(APIView):
    """
    API para obtener un feed de eventos de planificación (OPs y OCs) para un calendario.
    Filtra eventos por fecha de inicio/entrega.
    """
    def get(self, request):
        # 1. Obtener rango de fechas (aunque no se use en el filtro de la DB, es buena práctica)
        # Aquí puedes agregar lógica para parsear fechas si tu calendario las envía
        # Ejemplo: /api/calendario/?start_date=2025-10-01&end_date=2025-12-31
        
        eventos = []

        # --- A. EVENTOS DE PRODUCCIÓN (OrdenProduccion - OPs) ---
        
        # Filtramos todas las OPs que no están finalizadas ni canceladas
        ops_pendientes = OrdenProduccion.objects.filter(
            id_estado_orden_produccion__descripcion__in=['En espera', 'Pendiente de inicio', 'En proceso']
        ).select_related('id_producto', 'id_estado_orden_produccion')
        
        for op in ops_pendientes:
            # Asumimos que la duración de la OP es su tiempo planificado + tiempo total de lead time.
            # Aquí, solo usamos la fecha_inicio para el start y una estimación simple para el end.
            
            # Usaremos el campo fecha_inicio (DateTimePicker) y añadiremos 1 día como duración mínima.
            start_dt = op.fecha_inicio
            
            # NOTA: Para un END preciso, necesitarías el tiempo de producción total,
            # pero para el calendario, estimamos el final del día de inicio o el día siguiente.
            end_dt = start_dt + timedelta(hours=8) # Estimamos 8 horas de duración para la visualización

            eventos.append({
                "id": f"OP-{op.id_orden_produccion}",
                "title": f"OP-{op.id_orden_produccion}: {op.id_producto.nombre} ({op.cantidad} u.)",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "type": "Produccion",
                "status": op.id_estado_orden_produccion.descripcion,
                "quantity": op.cantidad
            })

        # --- B. EVENTOS DE COMPRA (OrdenCompra - OCs) ---
        
        # Filtramos las OCs que están "En proceso" (stock en camino)
        ocs_pendientes = OrdenCompra.objects.filter(
            id_estado_orden_compra__descripcion='En proceso',
            fecha_entrega_estimada__isnull=False # Debe tener una fecha estimada para mostrar
        ).select_related('id_proveedor', 'id_estado_orden_compra')
        
        for oc in ocs_pendientes:
            # La fecha de inicio es la fecha estimada de recepción (fecha_entrega_estimada)
            delivery_date = oc.fecha_entrega_estimada
            
            # 🚨 LÍNEA CORREGIDA: Usar el nombre por defecto de Django si no hay related_name
            try:
                # Intenta usar el related_name por defecto (nombre del modelo en minúsculas + _set)
                items_count = oc.ordencompramateriaprima_set.count() 
            except AttributeError:
                # Si el related_name es 'ordencompra_materias_primas' y ese es el error,
                # significa que la relación no existe o la app no se migró correctamente.
                # Para evitar fallar, asignamos 0.
                items_count = 0
                
            
            eventos.append({
                "id": f"OC-{oc.id_orden_compra}",
                "title": f"OC-{oc.id_orden_compra}: Recepción MP ({items_count} ítems)",
                "start": delivery_date.isoformat(),
                "end": (delivery_date + timedelta(hours=2)).isoformat(), # Asumimos 2h de recepción
                "type": "Compra (Recepción)",
                "status": oc.id_estado_orden_compra.descripcion,
                "proveedor": oc.id_proveedor.nombre
            })

        return Response(eventos, status=status.HTTP_200_OK)