import json
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import mercadopago
from django.conf import settings
from tenant_app.models import Orden

# Decouple configuration
from decouple import config

@csrf_exempt
def mercadopago_webhook(request):
    """
    Endpoint de escucha para las notificaciones webhooks (IPN) de Mercado Pago.
    Actualiza el estado de las órdenes automáticamente cuando cambian en MP.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        # MP envía un TOPIC (type) y un ID de reporte (data.id) o directamente el topic=payment / id=X en querystring
        data = request.GET.dict() if request.GET else json.loads(request.body)
        
        topic = data.get("type", data.get("topic"))
        evento_id = data.get("data", {}).get("id", data.get("id"))

        if topic == "payment" and evento_id:
            try:
                # 1. Instanciamos SDK con el token maestro
                access_token = config('MP_ACCESS_TOKEN', default='TEST-9003504959400262-022410-b74ccbb1d50e88383a15dc2d677610fa-1123456789')
                sdk = mercadopago.SDK(access_token)

                # 2. Consultar a MP por la info real del pago usando evento_id
                payment_response = sdk.payment().get(evento_id)
                pago = payment_response.get("response")

                if pago:
                    # external_reference nosotros lo definimos como str(orden_id) en el MP Service
                    orden_id = pago.get("external_reference")
                    nuevo_estado_mp = pago.get("status")

                    if orden_id:
                        try:
                            orden = Orden.objects.get(id=int(orden_id))
                            
                            # Mapeamos los estados principales de MP
                            if nuevo_estado_mp == "approved":
                                orden.estado_pago = "completado"
                            elif nuevo_estado_mp in ["rejected", "cancelled"]:
                                orden.estado_pago = "rechazado"
                            elif nuevo_estado_mp in ["in_process", "pending"]:
                                orden.estado_pago = "pendiente"
                            
                            # Validar que si guardamos el mp_vendedor_id, todo quedó trackeado
                            orden.mp_payment_id = str(evento_id)
                            orden.save(update_fields=['estado_pago', 'mp_payment_id', 'actualizado_en'])

                            return HttpResponse("Webhook procesado", status=200)

                        except Orden.DoesNotExist:
                            # Puede ser un pago viejo o no pertenece a nuestra BBDD
                            pass

            except Exception as e:
                # MP suele reintentar si mandamos 500, loguear para investigar
                print(f"Error procesando Webhook MP: {e}")
                return HttpResponse(status=500)

        # Si no es topic payment o no encontramos la orden, mandamos 200 igual para que MP deje de spamear retrys.
        return HttpResponse(status=200)

    except Exception:
        return HttpResponse(status=400)
