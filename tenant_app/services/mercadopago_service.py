import mercadopago
from django.conf import settings
from decimal import Decimal

# Variables de entorno ideales (agregamos provisorios para desarrollo local si no existen en config)
# MP_ACCESS_TOKEN_PRINTFLOW será el generador principal de pagos
from decouple import config

class MercadoPagoService:
    def __init__(self):
        # El Access Token de Producción/Test de la cuenta Master (PrintFlow)
        # Quien genera la preferencia y corta el 'application_fee'
        self.access_token = config('MP_ACCESS_TOKEN', default='TEST-9003504959400262-022410-b74ccbb1d50e88383a15dc2d677610fa-1123456789')
        self.sdk = mercadopago.SDK(self.access_token)
        
        # Porcentaje del 'Success Fee' automático que se queda PrintFlow (ej. 3%)
        self.split_fee_percentage = Decimal(config('MP_SPLIT_FEE_PERCENTAGE', default='3.00'))

    def crear_pago_split(self, token_tarjeta, monto_total, email_pagador, nombre_producto, orden_id, mp_vendedor_id=None):
        """
        Crea un pago (Payment) en Mercado Pago usando el Checkout Transparente.
        Aplica Split Payments si la tienda tiene un mp_vendedor_id vinculado.
        """
        
        # 1. Payload base del pago
        payment_data = {
            "transaction_amount": float(monto_total),
            "token": token_tarjeta,
            "description": f"Compra de {nombre_producto}",
            "installments": 1,
            "payment_method_id": "visa",  # Simplificado para el MVP, el frontend enviaría el método real
            "payer": {
                "email": email_pagador
            },
            "external_reference": str(orden_id)
        }

        # 2. Configurar Split Payment si el vendedor está registrado
        # En la API v1 de MercadoPago, el Marketplace divide los fondos usando 'application_fee'
        # o 'sponsor_id' + enviando los fondos a un seller específico.
        # Aquí configuramos una porción (fee_amount) que va a la cuenta principal (PrintFlow).
        if mp_vendedor_id:
            fee_amount = (monto_total * (self.split_fee_percentage / 100))
            # Ojo: la documentación de MP Checkout Custom/Split varía por país,
            # pero el atributo `application_fee` o los arrays de fees son el standard.
            payment_data["application_fee"] = float(fee_amount)
            # Y se vincularía el pago al collector final (el subcontratista)
            # payment_data["sponsor_id"] = ...
            # En la vida real haríamos la llamada completa de OAuth al momento de vincular la Tienda.

        try:
            # 3. Llamada sincrónica a la API (/v1/payments)
            payment_response = self.sdk.payment().create(payment_data)
            pago = payment_response["response"]
            
            return {
                "status": pago.get("status"), # 'approved', 'in_process', 'rejected'
                "status_detail": pago.get("status_detail"), 
                "id": str(pago.get("id")),
                "raw_response": pago
            }
        except Exception as e:
            return {
                "status": "error",
                "status_detail": str(e),
                "id": None
            }
