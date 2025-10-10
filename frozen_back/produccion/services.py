
from django.db import transaction
from django.db.models import Sum
from .models import OrdenProduccion, EstadoOrdenProduccion
from stock.models import LoteMateriaPrima, EstadoLoteMateriaPrima, LoteProduccionMateria
from recetas.models import Receta, RecetaMateriaPrima


@transaction.atomic
def procesar_ordenes_en_espera(materia_prima_ingresada):
    """
    Busca órdenes de producción 'En espera' que necesiten la materia prima que acaba de ingresar.
    Si ahora tienen stock suficiente para TODOS sus ingredientes, las pasa a 'Pendiente de inicio'
    y descuenta el stock correspondiente.
    """
    print(f"Iniciando revisión de órdenes en espera por ingreso de: {materia_prima_ingresada.nombre}")

    # 1. Obtener los estados que vamos a necesitar
    try:
        estado_en_espera = EstadoOrdenProduccion.objects.get(descripcion__iexact="En espera")
        estado_pendiente = EstadoOrdenProduccion.objects.get(descripcion__iexact="Pendiente de inicio")
        estado_disponible_mp = EstadoLoteMateriaPrima.objects.get(descripcion__iexact="Disponible")
    except (EstadoOrdenProduccion.DoesNotExist, EstadoLoteMateriaPrima.DoesNotExist) as e:
        print(f"Error: No se encontraron los estados necesarios en la BBDD. {e}")
        return

    # 2. Encontrar órdenes 'En espera' que usen esta materia prima en su receta
    ordenes_a_revisar = OrdenProduccion.objects.filter(
        id_estado_orden_produccion=estado_en_espera,
        id_producto__receta__recetamateriaprima__id_materia_prima=materia_prima_ingresada
    ).distinct()

    if not ordenes_a_revisar.exists():
        print("No hay órdenes en espera que requieran esta materia prima.")
        return

    print(f"Se encontraron {ordenes_a_revisar.count()} órdenes para revisar.")

    # 3. Iterar sobre cada orden y verificar si AHORA tiene stock completo
    for orden in ordenes_a_revisar:
        print(f"Revisando stock para la Orden de Producción #{orden.id_orden_produccion}...")
        
        try:
            receta = Receta.objects.get(id_producto=orden.id_producto)
            ingredientes = RecetaMateriaPrima.objects.filter(id_receta=receta)
            
            stock_suficiente = True
            # Volvemos a chequear el stock para TODOS los ingredientes de la orden
            for ingrediente in ingredientes:
                materia = ingrediente.id_materia_prima
                cantidad_necesaria = ingrediente.cantidad * orden.cantidad
                
                stock_total = LoteMateriaPrima.objects.filter(
                    id_materia_prima=materia,
                    id_estado_lote_materia_prima=estado_disponible_mp
                ).aggregate(total=Sum("cantidad"))["total"] or 0

                if stock_total < cantidad_necesaria:
                    stock_suficiente = False
                    print(f"Falta stock para {materia.nombre}. Se necesitan {cantidad_necesaria}, hay {stock_total}.")
                    break # Si falta un ingrediente, no hace falta seguir revisando

            # 4. Si hay stock para todo, cambiamos el estado y descontamos
            if stock_suficiente:
                print(f"¡Stock suficiente para la Orden #{orden.id_orden_produccion}! Procesando...")
                
                # Cambiar estado de la orden
                orden.id_estado_orden_produccion = estado_pendiente
                orden.save()
                
                # Descontar stock (lógica FIFO)
                for ingrediente in ingredientes:
                    materia = ingrediente.id_materia_prima
                    cantidad_a_descontar = ingrediente.cantidad * orden.cantidad
                    
                    lotes_mp = LoteMateriaPrima.objects.filter(
                        id_materia_prima=materia,
                        id_estado_lote_materia_prima=estado_disponible_mp
                    ).order_by('fecha_vencimiento')

                    for lote in lotes_mp:
                        if cantidad_a_descontar <= 0: break
                        
                        cantidad_tomada = min(lote.cantidad, cantidad_a_descontar)
                        
                        LoteProduccionMateria.objects.create(
                            id_lote_produccion=orden.id_lote_produccion,
                            id_lote_materia_prima=lote,
                            cantidad_usada=cantidad_tomada
                        )
                        
                        lote.cantidad -= cantidad_tomada
                        lote.save()
                        
                        cantidad_a_descontar -= cantidad_tomada
                
                print(f"Orden #{orden.id_orden_produccion} actualizada a 'Pendiente de inicio' y stock descontado.")

        except Receta.DoesNotExist:
            print(f"Advertencia: La orden #{orden.id_orden_produccion} no tiene receta asociada. Se omite.")
            continue