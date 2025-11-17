from django.db import transaction
from .models import OrdenVentaProducto, EstadoVenta, OrdenVenta, Factura, NotaCredito
from stock.models import LoteProduccion, ReservaStock, EstadoLoteProduccion, EstadoReserva 
from stock.services import verificar_stock_y_enviar_alerta
from stock.models import ReservaStock
from django.db.models import Sum, F, Q
from collections import defaultdict
from datetime import date, timedelta
from django.utils import timezone
import math

# Importar modelos
from productos.models import Producto
from recetas.models import Receta, RecetaMateriaPrima, ProductoLinea
from produccion.models import CalendarioProduccion, EstadoOrdenProduccion
from stock.services import get_stock_disponible_para_producto, get_stock_disponible_para_materia_prima

# Constantes (Las mismas de tu planificador)
HORAS_LABORABLES_POR_DIA = 16
DIAS_BUFFER_ENTREGA_PT = 1
DIAS_BUFFER_RECEPCION_MP = 1


 
@transaction.atomic
def registrar_orden_venta_y_actualizar_estado(orden_venta: OrdenVenta):
    """
    Simplemente guarda la orden de venta y la pone en estado 'Creada'.
    No reserva stock ni crea Órdenes de Producción.
    Deja la orden lista para que el planificador (MRP) la procese.
    """
    # Obtenemos el estado "Creada"
    estado_creada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Creada")
    
    # Asignamos el estado a la orden
    orden_venta.id_estado_venta = estado_creada
    orden_venta.save()
    
    print(f"Orden Venta #{orden_venta.pk} guardada. Estado -> Creada. Esperando al planificador.")


@transaction.atomic
def facturar_orden_y_descontar_stock(orden_venta: OrdenVenta):
    """
    (Esta función se mantiene como estaba)
    Descuenta el stock físico que el PLANIFICADOR ya reservó.
    """
    print(f"Iniciando facturación y descuento físico para la Orden #{orden_venta.pk}...")
    
    reservas = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva__descripcion="Activa"
    ).select_related('id_lote_produccion', 'id_orden_venta_producto__id_producto')
    
    # ... (El resto de la función sigue igual) ...
    estado_agotado, _ = EstadoLoteProduccion.objects.get_or_create(descripcion="Agotado")
    productos_afectados = set()

    for reserva in reservas:
        lote = reserva.id_lote_produccion
        cantidad_a_descontar = reserva.cantidad_reservada
        lote.cantidad -= cantidad_a_descontar
        if lote.cantidad <= 0:
            lote.cantidad = 0 # Asegurar que no sea negativo
            lote.id_estado_lote_produccion = estado_agotado
        lote.save()
        productos_afectados.add(reserva.id_orden_venta_producto.id_producto.pk)

    estado_utilizada, _ = EstadoReserva.objects.get_or_create(descripcion="Utilizada")
    reservas.update(id_estado_reserva=estado_utilizada)
    
    estado_facturada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Pagada")
    orden_venta.id_estado_venta = estado_facturada
    orden_venta.save()

    print("Verificando umbrales de stock post-facturación...")
    for producto_id in productos_afectados:
        verificar_stock_y_enviar_alerta(producto_id)

    print(f"Orden #{orden_venta.pk} facturada y stock físico descontado exitosamente.")


@transaction.atomic
def cancelar_orden_venta(orden_venta):
    """
    (Esta función se mantiene como estaba)
    Cancela una orden y libera las reservas que el PLANIFICADOR hizo.
    """
    print(f"Cancelando Orden Venta #{orden_venta.pk}...")
    estado_activa, _ = EstadoReserva.objects.get_or_create(descripcion="Activa")
    estado_cancelada, _ = EstadoReserva.objects.get_or_create(descripcion="Cancelada")

    reservas_a_cancelar = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_activa
    )
    

    reservas_a_cancelar.update(id_estado_reserva=estado_cancelada)
    
    estado_orden_cancelada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Cancelada")
    orden_venta.id_estado_venta = estado_orden_cancelada
    orden_venta.save()
    
    print(f"Orden #{orden_venta.pk} cancelada y stock liberado.")
    
 


@transaction.atomic
def crear_nota_credito_y_devolver_stock(orden_venta: OrdenVenta, motivo: str = None):
    """
    1. Crea una Nota de Crédito para la factura de la orden.
    2. Encuentra las reservas 'Utilizadas' de esa orden.
    3. Devuelve el stock físico (cantidad) a los lotes correspondientes.
    4. Cambia el estado de los lotes a 'Disponible' si estaban 'Agotados'.
    5. Cambia el estado de las reservas a 'Devolución NC'.
    6. Cambia el estado de la orden a 'Devolución NC'.
    7. Dispara la re-evaluación de stock para otras órdenes pendientes.
    """
    print(f"Iniciando creación de Nota de Crédito para Orden #{orden_venta.pk}...")

    # 1. Validar estado de la orden y encontrar factura
    estado_facturada, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Pagada")
    if orden_venta.id_estado_venta != estado_facturada:
        raise Exception(f"La orden #{orden_venta.pk} no está 'Pagada'. No se puede crear nota de crédito.")

    try:
        factura = Factura.objects.get(id_orden_venta=orden_venta)
    except Factura.DoesNotExist:
        raise Exception(f"No se encontró una factura para la orden #{orden_venta.pk}.")

    # 2. Validar que no exista ya una NC
    if NotaCredito.objects.filter(id_factura=factura).exists():
        raise Exception(f"Ya existe una nota de crédito para la factura #{factura.pk}.")

    # 3. Obtener estados necesarios
    estado_utilizada = EstadoReserva.objects.get(descripcion="Utilizada")
    estado_devuelta_nc, _ = EstadoReserva.objects.get_or_create(descripcion="Devolución NC")
    estado_disponible, _ = EstadoLoteProduccion.objects.get_or_create(descripcion="Disponible")
    estado_orden_devuelta, _ = EstadoVenta.objects.get_or_create(descripcion="Devolución NC")

    # 4. Encontrar las reservas que se usaron para esta orden
    reservas_utilizadas = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_utilizada
    ).select_related('id_lote_produccion', 'id_orden_venta_producto__id_producto')

    if not reservas_utilizadas.exists():
        raise Exception(f"No se encontraron reservas 'Utilizadas' para la orden #{orden_venta.pk}. No se puede revertir el stock.")

    # 5. Crear la Nota de Crédito
    nota_credito = NotaCredito.objects.create(
        id_factura=factura,
        motivo=motivo or "Devolución de cliente"
    )

    productos_afectados = set()

    # 6. Devolver el stock a los lotes
    for reserva in reservas_utilizadas:
        lote = reserva.id_lote_produccion
        cantidad_a_devolver = reserva.cantidad_reservada

        print(f"  > Devolviendo {cantidad_a_devolver} unidades al Lote #{lote.pk} (Producto: {reserva.id_orden_venta_producto.id_producto.nombre})")

        # Devolvemos la cantidad
        lote.cantidad = F('cantidad') + cantidad_a_devolver
        
        # Si el lote estaba 'Agotado', vuelve a estar 'Disponible'
        lote.id_estado_lote_produccion = estado_disponible
        
        lote.save()
        productos_afectados.add(reserva.id_orden_venta_producto.id_producto)

    # 7. Actualizar estado de las reservas
    reservas_utilizadas.update(id_estado_reserva=estado_devuelta_nc)

    # 8. Actualizar estado de la Orden de Venta
    orden_venta.id_estado_venta = estado_orden_devuelta
    orden_venta.save()


    return nota_credito






def verificar_orden_completa(items):
    """
    Recibe: [{"producto_id": 1, "cantidad": 100}, {"producto_id": 2, "cantidad": 50}]
    Devuelve: Global status y detalles por ítem.
    """
    hoy = timezone.now().date()
    
    # --- 1. Inicializar "Memoria Virtual" de la Simulación ---
    # Esto rastrea cuánto stock hemos "imaginado" que consumimos en esta orden
    virtual_stock_pt_consumido = defaultdict(int)
    virtual_stock_mp_consumido = defaultdict(int)
    
    # Para la capacidad, rastreamos cuándo se libera cada línea
    # { linea_id: fecha_liberacion_estimada }
    virtual_calendario_lineas = defaultdict(lambda: hoy)

    fecha_final_orden = hoy
    detalles_items = []
    es_toda_factible = True
    warning_global = None

    for item in items:
        p_id = item['producto_id']
        cant_solicitada = int(item['cantidad'])
        
        # --- A. Consumo de Stock PT ---
        stock_real_pt = get_stock_disponible_para_producto(p_id)
        stock_virtual_disponible = max(0, stock_real_pt - virtual_stock_pt_consumido[p_id])
        
        tomar_de_stock = min(stock_virtual_disponible, cant_solicitada)
        a_producir = cant_solicitada - tomar_de_stock
        
        # Registramos el consumo virtual
        virtual_stock_pt_consumido[p_id] += tomar_de_stock

        fecha_entrega_item = hoy
        origen = "Stock"

        # --- B. Simulación de Producción (Si falta stock) ---
        if a_producir > 0:
            origen = "Producción"
            max_lead_time_mp = 0
            
            # 1. Chequeo MP (Acumulativo)
            try:
                receta = Receta.objects.get(id_producto=p_id)
                ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)
                
                for ing in ingredientes:
                    mp_id = ing.id_materia_prima.id_materia_prima
                    cant_necesaria = ing.cantidad * a_producir
                    
                    stock_real_mp = get_stock_disponible_para_materia_prima(mp_id)
                    # Restamos lo que ya consumieron los items anteriores de esta lista
                    stock_mp_virtual = max(0, stock_real_mp - virtual_stock_mp_consumido[mp_id])
                    
                    if stock_mp_virtual < cant_necesaria:
                        # Falta MP, calculamos Lead Time
                        lt = ing.id_materia_prima.id_proveedor.lead_time_days
                        max_lead_time_mp = max(max_lead_time_mp, lt)
                        # Asumimos que compramos lo que falta, no consumimos del virtual negativo
                    else:
                        # Hay stock, lo consumimos virtualmente
                        virtual_stock_mp_consumido[mp_id] += cant_necesaria
                        
            except Receta.DoesNotExist:
                warning_global = f"Producto {p_id} sin receta."
            
            # 2. Calcular Fechas MP
            fecha_llegada_mp = hoy + timedelta(days=max_lead_time_mp)
            while fecha_llegada_mp.weekday() >= 5: fecha_llegada_mp += timedelta(days=1)
            
            fecha_inicio_prod = fecha_llegada_mp + timedelta(days=DIAS_BUFFER_RECEPCION_MP)
            while fecha_inicio_prod.weekday() >= 5: fecha_inicio_prod += timedelta(days=1)

            # 3. Calcular Tiempo Máquina (Acumulativo sobre la línea)
            capacidades = ProductoLinea.objects.filter(id_producto=p_id)
            if capacidades.exists():
                cap_total = capacidades.aggregate(total=Sum('cant_por_hora'))['total'] or 1
                horas_nec = math.ceil(a_producir / cap_total)
                dias_prod = math.ceil(horas_nec / HORAS_LABORABLES_POR_DIA)
                
                # Buscamos cuándo se libera la línea más ocupada
                fecha_base_linea = fecha_inicio_prod
                for cap in capacidades:
                    fecha_linea = virtual_calendario_lineas[cap.id_linea_produccion]
                    if fecha_linea > fecha_base_linea:
                        fecha_base_linea = fecha_linea
                
                # Sumamos días de trabajo
                fecha_fin_prod = fecha_base_linea + timedelta(days=dias_prod)
                while fecha_fin_prod.weekday() >= 5: fecha_fin_prod += timedelta(days=1)
                
                # Actualizamos el calendario virtual de esas líneas
                # (El próximo producto que use esta línea tendrá que esperar a esta fecha)
                for cap in capacidades:
                    virtual_calendario_lineas[cap.id_linea_produccion] = fecha_fin_prod
                
                fecha_entrega_item = fecha_fin_prod + timedelta(days=DIAS_BUFFER_ENTREGA_PT + 1)
            else:
                fecha_entrega_item = fecha_inicio_prod # Fallback sin lineas

        # Ajuste final fines de semana
        while fecha_entrega_item.weekday() >= 5: fecha_entrega_item += timedelta(days=1)

        # Actualizar fecha global de la orden
        if fecha_entrega_item > fecha_final_orden:
            fecha_final_orden = fecha_entrega_item

        detalles_items.append({
            "producto_id": p_id,
            "cantidad": cant_solicitada,
            "origen": origen,
            "fecha_item": fecha_entrega_item
        })

    return {
        "fecha_sugerida_total": fecha_final_orden,
        "detalles": detalles_items,
        "items_analizados": len(items)
    }