from django.core.mail import send_mail
from productos.models import Producto
from .models import LoteProduccion
from django.db.models import Sum
from django.conf import settings
import threading
import requests

def cantidad_total_disponible_producto(id_producto):
    """
    Devuelve la cantidad total disponible de un producto sumando
    los lotes en estado 'Disponible'.
    """
    total = (
        LoteProduccion.objects
        .filter(
            id_producto_id=id_producto,
            id_estado_lote_produccion__descripcion="Disponible"
        )
        .aggregate(total=Sum("cantidad"))
        .get("total") or 0
    )
    return total

def verificar_stock_y_enviar_alerta(id_producto, email):
    try:
        producto = Producto.objects.get(pk=id_producto)
    except Producto.DoesNotExist:
        return {"error": f"El producto con ID {id_producto} no existe."}

    total_disponible = cantidad_total_disponible_producto(id_producto)
    umbral = producto.umbral_minimo
    alerta = total_disponible < umbral

    mensaje = (
        f"⚠️ Stock por debajo del umbral mínimo ({total_disponible} < {umbral})"
        if alerta else
        f"✅ Stock suficiente ({total_disponible} ≥ {umbral})"
    )

    # Si hay alerta, enviar ambas notificaciones en segundo plano
    if alerta:
        asunto_email = f"⚠️ Alerta de stock bajo - {producto.nombre}"
        cuerpo_notificacion = (
            f"Producto: {producto.nombre}\n"
            f"Cantidad disponible: {total_disponible}\n"
            f"Umbral mínimo: {umbral}\n\n"
            "Por favor, revisar el stock o generar nuevo lote de producción."
        )
        # 1. Enviar correo (tu código existente)
    #    _enviar_correo_async(asunto_email, cuerpo_notificacion, email)
        
        # 2. Enviar mensaje de Telegram (nueva llamada)
        _enviar_telegram_async(cuerpo_notificacion)

    return {
        "id_producto": id_producto,
        "nombre": producto.nombre,
        "cantidad_disponible": total_disponible,
        "umbral_minimo": umbral,
        "alerta": alerta,
        "mensaje": mensaje,
        "email_notificado": email if alerta else None
    }

def _enviar_correo_async(asunto, cuerpo, destinatario):
    """
    Envía un correo en un hilo aparte para no bloquear la vista.
    """
    threading.Thread(
        target=send_mail,
        args=(asunto, cuerpo, None, [destinatario]),
        kwargs={"fail_silently": False}
    ).start()



# --- NUEVA FUNCIÓN PARA TELEGRAM ---
def _enviar_telegram_async(mensaje):
    """
    Envía un mensaje de Telegram en un hilo aparte.
    """
    def send_request():
        token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID

        # Salir si no están configuradas las credenciales
        if not token or not chat_id:
            print("ADVERTENCIA: Credenciales de Telegram no configuradas en settings.py")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": mensaje,
            "parse_mode": "Markdown" # Opcional, para formato
        }
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()  # Lanza un error si la petición falla
        except requests.exceptions.RequestException as e:
            print(f"Error al enviar mensaje de Telegram: {e}")

    # Ejecutar el envío en un hilo separado
    threading.Thread(target=send_request).start()