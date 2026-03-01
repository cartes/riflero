import json
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from tenant_app.models import Tienda, ProductoTienda, Orden
from tenant_app.services.mercadopago_service import MercadoPagoService

@csrf_exempt
def api_checkout_transparent(request):
    """
    Endpoint POST para recibir el token de tarjeta (generado por MP.js en el frontend)
    y crear el pago y la Orden vinculada al subcontratista.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)

    # El Middleware inyecta el tenant (subcontratista) si venimos de un subdominio válido
    tienda = getattr(request, 'tenant', None)
    if not tienda:
        return JsonResponse({"error": "No se identificó el taller/tienda origen"}, status=400)

    try:
        data = json.loads(request.body)
        
        # Parámetros básicos esperados desde el frontend
        token_tarjeta = data.get("token")
        producto_id = data.get("producto_id")
        email_cliente = data.get("payer_email")
        nombre_cliente = data.get("payer_name", "Cliente")
        
        if not all([token_tarjeta, producto_id, email_cliente]):
            return JsonResponse({"error": "Faltan parámetros obligatorios"}, status=400)

        # Buscar el producto que se va a comprar
        try:
            producto = ProductoTienda.objects.get(id=producto_id, tienda=tienda)
        except ProductoTienda.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado en este catálogo"}, status=404)

        # El precio_final es calculado on-the-fly (precio_base * (1 + margen_ganancia/100))
        monto_total = producto.precio_final
        
        # 1. Crear Orden en estado pendiente en nuestra Base de Datos local
        orden = Orden.objects.create(
            tienda=tienda,
            producto=producto,
            monto_total=monto_total,
            estado_pago='pendiente',
            nombre_cliente=nombre_cliente,
            email_cliente=email_cliente
        )

        # 2. Llamar al servicio de Mercado Pago para procesar tarjeta + aplicar Split de pagos
        mp_service = MercadoPagoService()
        
        # Le enviamos el mp_vendedor_id_id de este subcontratista específico 
        # para que "PrintFlow" envíe el dinero a la cuenta del subcontratista 
        # y "PrintFlow" se quede con el `application_fee` configurado.
        resultado_mp = mp_service.crear_pago_split(
            token_tarjeta=token_tarjeta,
            monto_total=monto_total,
            email_pagador=email_cliente,
            nombre_producto=str(producto),
            orden_id=orden.id,
            mp_vendedor_id=tienda.mp_vendedor_id
        )

        # 3. Evaluar respuesta del Checkout de MP
        if resultado_mp["status"] in ["approved", "in_process"]:
            orden.estado_pago = 'completado' if resultado_mp["status"] == "approved" else 'pendiente'
            orden.mp_payment_id = resultado_mp["id"]
            orden.save(update_fields=['estado_pago', 'mp_payment_id', 'actualizado_en'])
            
            return JsonResponse({
                "message": "Pago procesado exitosamente",
                "orden_id": orden.id,
                "estado_mp": resultado_mp["status"]
            })
        else:
            # Fallo o rechazo de tarjeta
            orden.estado_pago = 'rechazado' if resultado_mp["status"] == "rejected" else 'fallido'
            if resultado_mp["id"]:
                orden.mp_payment_id = resultado_mp["id"]
            orden.save(update_fields=['estado_pago', 'mp_payment_id', 'actualizado_en'])
            
            return JsonResponse({
                "error": "El pago no pudo ser procesado",
                "detalle_mp": resultado_mp["status_detail"]
            }, status=400)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def api_get_comunas(request):
    """
    Endpoint GET para obtener la lista de comunas de una región específica.
    Usado por JavaScript en el formulario de registro (Cascading Dropdowns).
    """
    region_id = request.GET.get('region_id')
    comunas = []
    if region_id:
        from tenant_app.models import Comuna
        try:
            comunas = list(Comuna.objects.filter(provincia__region_id=region_id).values('id', 'nombre').order_by('nombre'))
        except ValueError:
            pass # ID inválido
    return JsonResponse({'comunas': comunas})
