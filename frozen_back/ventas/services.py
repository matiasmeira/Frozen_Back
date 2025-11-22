from django.db import transaction
from .models import OrdenVentaProducto, EstadoVenta, OrdenVenta, Factura, NotaCredito
from stock.models import LoteProduccion, ReservaStock, EstadoLoteProduccion, EstadoReserva 
from stock.services import verificar_stock_y_enviar_alerta
from stock.models import ReservaStock
from django.db.models import Sum, F, Q, ExpressionWrapper, FloatField
from collections import defaultdict
from datetime import date, timedelta
from django.utils import timezone
import math
from django.db.models.functions import Coalesce

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
    Recibe una OrdenVenta, busca su factura, y genera la NC + Devolución de stock a Cuarentena.
    """
    print(f"Iniciando proceso de NC para Orden #{orden_venta.pk}...")

    # 1. Validar estado 'Pagada'
    estado_facturada = EstadoVenta.objects.filter(descripcion__iexact="Pagada").first()
    if not estado_facturada or orden_venta.id_estado_venta != estado_facturada:
        raise Exception(f"La orden #{orden_venta.pk} no está en estado 'Pagada'.")

    # 2. Buscar la Factura asociada a esta Orden
    #    (Esto es lo que permite que el usuario solo envíe el ID de la orden)
    try:
        factura = Factura.objects.get(id_orden_venta=orden_venta)
    except Factura.DoesNotExist:
        raise Exception(f"La Orden #{orden_venta.pk} no tiene una factura generada asociada.")

    # 3. Validar que no exista NC previa
    if NotaCredito.objects.filter(id_factura=factura).exists():
        raise Exception(f"Ya existe una Nota de Crédito para la factura de la Orden #{orden_venta.pk}.")

    # 4. Obtener Estados
    estado_reserva_utilizada = EstadoReserva.objects.get(descripcion="Utilizada")
    estado_reserva_devuelta, _ = EstadoReserva.objects.get_or_create(descripcion="Devolución NC")
    estado_orden_devuelta, _ = EstadoVenta.objects.get_or_create(descripcion="Devolución NC")
    estado_lote_cuarentena, _ = EstadoLoteProduccion.objects.get_or_create(descripcion="Cuarentena")

    # 5. Buscar Reservas Utilizadas
    reservas_utilizadas = ReservaStock.objects.filter(
        id_orden_venta_producto__id_orden_venta=orden_venta,
        id_estado_reserva=estado_reserva_utilizada
    ).select_related('id_lote_produccion', 'id_orden_venta_producto__id_producto')

    if not reservas_utilizadas.exists():
        raise Exception("No hay stock reservado/utilizado para devolver en esta orden.")

    # 6. Crear Nota de Crédito
    nota_credito = NotaCredito.objects.create(
        id_factura=factura,
        motivo=motivo or f"Devolución Ref. Orden #{orden_venta.pk}"
    )

    # 7. Generar NUEVOS lotes en Cuarentena
    for reserva in reservas_utilizadas:
        lote_origen = reserva.id_lote_produccion
        cantidad_a_devolver = reserva.cantidad_reservada
        
        LoteProduccion.objects.create(
            id_producto=lote_origen.id_producto,
            fecha_produccion=lote_origen.fecha_produccion,
            fecha_vencimiento=lote_origen.fecha_vencimiento,
            cantidad=cantidad_a_devolver,
            id_estado_lote_produccion=estado_lote_cuarentena
            # Recuerda: si tienes campos obligatorios extra en la BD, agrégalos aquí.
        )

    # 8. Actualizar Reservas y Orden
    reservas_utilizadas.update(id_estado_reserva=estado_reserva_devuelta)
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







def procesar_orden_venta_online(orden_venta: OrdenVenta):
    """
    Lógica específica para VENTAS ONLINE:
    1. Intenta reservar stock existente inmediatamente.
    2. Cambia el estado a 'Pendiente de Pago' (o 'Sin Stock' si falla).
    """
    print(f"🛒 Procesando Venta Online #{orden_venta.pk}...")
    
    # 1. Obtener estados necesarios
    estado_pendiente_pago, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Pendiente de Pago")
    estado_sin_stock, _ = EstadoVenta.objects.get_or_create(descripcion__iexact="Cancelada por Stock") # O el estado que prefieras
    estado_reserva_activa, _ = EstadoReserva.objects.get_or_create(descripcion__iexact="Activa")

    todas_reservadas = True
    errores = []

    # 2. Iterar productos y reservar
    for linea in orden_venta.ordenventaproducto_set.all():
        exito_reserva = _reservar_stock_inmediato(linea, estado_reserva_activa)
        if not exito_reserva:
            todas_reservadas = False
            errores.append(f"Falta stock para {linea.id_producto.descripcion}")

    # 3. Actualizar Estado de la Venta
    if todas_reservadas:
        orden_venta.id_estado_venta = estado_pendiente_pago
        orden_venta.save()
        print(f"✅ Venta Online #{orden_venta.pk} -> Reservada y Pendiente de Pago")
        return {'exito': True, 'mensaje': 'Stock reservado'}
    else:
        # Aquí decides: ¿La dejas en 'Creada' para que produccion la vea? 
        # ¿O le avisas al usuario que no hay stock? 
        # Asumamos que para Online, si no hay stock, no se procesa el pago:
        print(f"❌ Venta Online #{orden_venta.pk} -> Falta stock")
        return {'exito': False, 'mensaje': ", ".join(errores)}

def _reservar_stock_inmediato(linea_ov: OrdenVentaProducto, estado_activa: EstadoReserva) -> bool:
    """
    Intenta reservar el 100% de la cantidad solicitada.
    Retorna True si logró reservar todo, False si falta algo.
    """
    cantidad_necesaria = linea_ov.cantidad
    
    filtro_reservas_activas = Q(reservas__id_estado_reserva__descripcion='Activa')
    
    lotes_disponibles = LoteProduccion.objects.filter(
        id_producto=linea_ov.id_producto,
        id_estado_lote_produccion__descripcion="Disponible"
    ).annotate(
        total_reservado=Coalesce(Sum('reservas__cantidad_reservada', filter=filtro_reservas_activas), 0)
    ).annotate(
        # --- CORRECCIÓN AQUÍ ---
        # Usamos ExpressionWrapper para manejar la resta entre Entero y Flotante
        disponible_real=ExpressionWrapper(
            F('cantidad') - F('total_reservado'),
            output_field=FloatField()
        )
    ).filter(
        disponible_real__gt=0
    ).order_by('fecha_vencimiento')

    # Verificamos si hay suficiente stock TOTAL antes de empezar a reservar
    total_existente = sum(l.disponible_real for l in lotes_disponibles)
    
    # Nota: Al comparar floats, es bueno tener cuidado, pero para stock suele funcionar directo
    if total_existente < cantidad_necesaria:
        return False 

    cantidad_pendiente = cantidad_necesaria
    
    for lote in lotes_disponibles:
        if cantidad_pendiente <= 0: break
        
        a_tomar = min(lote.disponible_real, cantidad_pendiente)
        
        ReservaStock.objects.create(
            id_orden_venta_producto=linea_ov,
            id_lote_produccion=lote,
            cantidad_reservada=a_tomar,
            id_estado_reserva=estado_activa
        )
        cantidad_pendiente -= a_tomar

    # Usamos una pequeña tolerancia para comparación de floats si es necesario, 
    # o simplemente comparamos con 0 si tus cantidades son enteras.
    return cantidad_pendiente <= 0