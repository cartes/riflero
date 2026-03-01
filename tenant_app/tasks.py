import re
from decimal import Decimal
from celery import shared_task
from django.utils import timezone
from playwright.sync_api import sync_playwright

from .models import ProductoTienda, RadarPrecio


@shared_task(bind=True, max_retries=3)
def extraer_precio_competidor(self, producto_id, competidor_nombre, url_objetivo, selector_css):
    """
    Tarea asincrónica de Celery que utiliza Playwright para navegar a la URL
    de un competidor, extraer el precio usando un selector CSS, y guardar
    el resultado en RadarPrecio.
    
    Al guardar RadarPrecio, el Signal `actualizar_precio_dinamico` se
    disparará automáticamente ajustando el precio del ProductoTienda.
    """
    try:
        producto = ProductoTienda.objects.get(id=producto_id)
        
        # Solo ejecutamos si la tienda tiene habilitado el scraping
        if not producto.tienda.scraping_activado:
            return f"Scraping deshabilitado para la tienda {producto.tienda.nombre_tienda}"

        precio_extraido = None

        # Iniciamos Playwright en modo headless
        with sync_playwright() as p:
            # Usamos Chromium por defecto
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Navegar a la URL con un timeout de 30s
            page.goto(url_objetivo, timeout=30000)
            
            # Esperar a que el elemento con el precio esté visible
            elemento_precio = page.wait_for_selector(selector_css, timeout=10000)
            
            if elemento_precio:
                texto_precio = elemento_precio.inner_text()
                
                # Limpiamos el texto para asegurar que sea un número (ej: "$ 15.000" -> "15000")
                # Extraer solo dígitos y opcionalmente puntos/comas
                limpio = re.sub(r'[^\d]', '', texto_precio)
                
                if limpio:
                    precio_extraido = Decimal(limpio)

            browser.close()

        if precio_extraido is not None:
            # Creamos el registro en el Radar de Precios
            # Esto dispara automáticamente el Signal en models.py
            RadarPrecio.objects.create(
                producto=producto,
                competidor_nombre=competidor_nombre,
                producto_referencia=url_objetivo,
                precio_extraido=precio_extraido
            )
            return f"Éxito: extraído {precio_extraido} de {competidor_nombre}"
        else:
            return f"Error: No se pudo extraer el precio usando '{selector_css}'"

    except ProductoTienda.DoesNotExist:
        return f"Error: ProductoTienda ID {producto_id} no existe"
    except Exception as exc:
        # Reintentar la tarea en caso de error temporal (timeout, caída rápida)
        raise self.retry(exc=exc, countdown=60)
