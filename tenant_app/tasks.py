import re
import urllib.parse
from decimal import Decimal
from celery import shared_task
from playwright.sync_api import sync_playwright

from .models import ProductoTienda, RadarPrecio


# ============================================================
# SELECTORES CSS DE PRECIO (en orden de prioridad)
# Cubre WooCommerce, Shopify, PrestaShop y sitios genéricos
# ============================================================
PRICE_SELECTORS = [
    # WooCommerce (el más común en Chile)
    '.woocommerce-Price-amount bdi',
    'ins .woocommerce-Price-amount bdi',   # precio con descuento
    '.woocommerce-Price-amount',
    # Shopify
    '.price__current',
    '[data-product-price]',
    '.product__price',
    # PrestaShop
    '.current-price-value',
    '.product-price .product-price',
    # Genérico
    '[class*="price"][class*="current"]',
    '[class*="precio"][class*="actual"]',
    '[itemprop="price"]',
    '[data-price]',
    '.price',
    '.precio',
]

# Patrones de buscador comunes (en orden de probabilidad)
SEARCH_URL_PATTERNS = [
    '?s={q}',           # WooCommerce default
    '?search={q}',
    '/search?q={q}',    # Shopify / modern
    '/buscar?q={q}',
    '/productos?buscar={q}',
    '/?buscar={q}',
    '/search/{q}',
]


def _limpiar_precio(texto: str) -> Decimal | None:
    """Extrae el primer número de precio válido de un texto."""
    if not texto:
        return None
    # Limpia símbolos y espacios
    limpio = re.sub(r'[^\d\.,]', '', texto.strip())
    # Normaliza separadores chilenos (punto=miles, coma=decimal)
    limpio = limpio.replace('.', '').replace(',', '')
    if limpio.isdigit() and len(limpio) >= 2:
        return Decimal(limpio)
    return None


def _extraer_precio_pagina(page) -> tuple[Decimal | None, str]:
    """
    Intenta extraer un precio de una página usando selectores CSS inteligentes.
    Devuelve (precio, método_usado).
    """
    # Intento 1: Selectores CSS conocidos por plataforma
    for selector in PRICE_SELECTORS:
        try:
            elementos = page.locator(selector).all()
            for el in elementos:
                texto = el.inner_text(timeout=2000).strip()
                precio = _limpiar_precio(texto)
                if precio and precio > 0:
                    return precio, f"CSS: {selector}"
        except Exception:
            continue

    # Intento 2: Regex contextual — busca precio CERCA de palabras clave
    try:
        texto_completo = page.locator('body').inner_text(timeout=8000)
        # Buscar precio que esté en la misma línea que palabras de precio
        for patron in [
            r'(?:precio|valor|price|costo)[^\d\n]{0,20}([\d\.]{3,})',
            r'\$\s*([\d\.]+(?:,\d+)?)',
        ]:
            match = re.search(patron, texto_completo, re.IGNORECASE)
            if match:
                precio = _limpiar_precio(match.group(1))
                if precio and precio > 100:  # filtrar precios absurdamente bajos
                    return precio, "Regex contextual"
    except Exception:
        pass

    return None, "no encontrado"


def _buscar_url_producto(page, sitio_web: str, termino: str, patron_custom: str | None) -> str | None:
    """
    Navega al buscador del sitio y devuelve la URL de la página del producto
    más relevante encontrada. Retorna None si no encuentra nada.
    """
    termino_encoded = urllib.parse.quote_plus(termino)
    candidatos = []

    # Construir candidatos de URL de búsqueda
    if patron_custom:
        candidatos.append(sitio_web.rstrip('/') + patron_custom.replace('{q}', termino_encoded))
    
    for patron in SEARCH_URL_PATTERNS:
        candidatos.append(sitio_web.rstrip('/') + patron.replace('{q}', termino_encoded))

    # Probar cada URL candidata
    for url_busqueda in candidatos:
        try:
            response = page.goto(url_busqueda, wait_until='domcontentloaded', timeout=20000)
            # Si la respuesta es válida y no redirige a home, intentar extraer resultados
            if response and response.status < 400 and page.url != sitio_web:
                # Buscar links de productos en resultados
                links = page.locator('a[href]').all()
                for link in links[:30]:  # Revisar los primeros 30 links
                    try:
                        href = link.get_attribute('href') or ''
                        texto_link = (link.inner_text(timeout=500) or '').lower().strip()
                        
                        # Construir URL absoluta si es relativa
                        if href.startswith('/'):
                            parsed = urllib.parse.urlparse(sitio_web)
                            href = f"{parsed.scheme}://{parsed.netloc}{href}"
                        elif not href.startswith('http'):
                            continue
                        
                        # Verificar si el texto del link es relevante
                        palabras = [p.lower() for p in termino.split() if len(p) > 3]
                        coincidencias = sum(1 for p in palabras if p in texto_link or p in href.lower())
                        
                        if coincidencias >= max(1, len(palabras) // 2):
                            return href
                    except Exception:
                        continue
                
                # Si encontramos una página de resultados pero sin match, salir del loop
                # para no probar más patrones (ya encontramos el buscador)
                break
        except Exception:
            continue

    return None


@shared_task(bind=True, max_retries=3)
def scraping_precios_graficos(self, producto_id):
    """
    Motor de Scraping Inteligente en 2 Pasos:
    1. Busca el producto por palabras clave en el buscador del proveedor.
    2. Entra a la página del producto y extrae el precio con CSS selectores inteligentes.
    """
    try:
        producto = ProductoTienda.objects.get(id=producto_id)
        
        # Obtenemos los competidores activos para este producto
        from .models import CompetidorScraping, ProveedorCompetencia
        competidores = producto.competidores_scraping.filter(activo=True).select_related('proveedor')
        
        if not competidores.exists():
            return f"No hay competidores configurados o activos para el producto {producto.id}"

        # Término de búsqueda: usa el campo específico o el nombre del producto
        termino_busqueda = (producto.termino_busqueda or producto.nombre).strip()

        urls_semilla = []
        for comp in competidores:
            sitio_web = comp.proveedor.sitio_web
            if not sitio_web:
                urls_semilla.append((comp.id, comp.proveedor.nombre, None, None, comp.proveedor.id))
            else:
                urls_semilla.append((
                    comp.id,
                    comp.proveedor.nombre,
                    sitio_web,
                    comp.proveedor.url_patron_busqueda,
                    comp.proveedor.id
                ))

        resultados = []
        precios_a_guardar = []
        contactos_a_guardar = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ))

            for comp_id, proveedor_nombre, sitio_web, patron_custom, proveedor_id in urls_semilla:
                texto_extraido = ""

                # Sin sitio_web configurado → avisar y saltar
                if not sitio_web:
                    resultados.append(
                        f"⚠ {proveedor_nombre}: sin 'Sitio Web' configurado en Proveedores Competencia."
                    )
                    continue

                # --- Caso especial: URL termina en PDF ---
                if sitio_web.lower().endswith('.pdf'):
                    try:
                        import requests
                        import io
                        from pypdf import PdfReader

                        res = requests.get(sitio_web, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
                        res.raise_for_status()
                        reader = PdfReader(io.BytesIO(res.content))
                        for pdf_page in reader.pages:
                            texto_extraido += (pdf_page.extract_text() or "") + " "

                        match = re.search(r'\$\s*([\d\.]+)', texto_extraido)
                        if match:
                            precio = _limpiar_precio(match.group(1))
                            if precio:
                                precios_a_guardar.append({
                                    'proveedor': proveedor_nombre,
                                    'url_producto': sitio_web,
                                    'precio': precio,
                                })
                                resultados.append(f"✅ {proveedor_nombre} (PDF): ${precio:,.0f}")
                            else:
                                resultados.append(f"⚠ {proveedor_nombre} (PDF): precio no parseable")
                        else:
                            resultados.append(f"⚠ {proveedor_nombre} (PDF): no se encontró precio")
                    except Exception as e:
                        resultados.append(f"❌ {proveedor_nombre} (PDF): {str(e)[:80]}")
                    continue

                # --- Paso 1: Buscar el producto en el sitio del proveedor ---
                try:
                    page = ctx.new_page()
                    resultados.append(f"🔍 Buscando '{termino_busqueda}' en {proveedor_nombre}...")

                    url_producto = _buscar_url_producto(page, sitio_web, termino_busqueda, patron_custom)

                    if not url_producto:
                        resultados.append(
                            f"⚠ {proveedor_nombre}: no se encontró una página de producto para '{termino_busqueda}'"
                        )
                        # Guardar el cuerpo para buscar contacto igualmente
                        try:
                            page.goto(sitio_web, wait_until='domcontentloaded', timeout=15000)
                            texto_extraido = page.locator('body').inner_text(timeout=5000)
                        except Exception:
                            pass
                        page.close()
                        # Buscar contacto aunque no hayamos encontrado el producto
                        if texto_extraido:
                            _detectar_contacto(texto_extraido, comp_id, proveedor_id, contactos_a_guardar)
                        continue

                    resultados.append(f"   → Navegando a: {url_producto}")

                    # --- Paso 2: Extraer precio en la página del producto ---
                    page.goto(url_producto, wait_until='domcontentloaded', timeout=20000)
                    precio, metodo = _extraer_precio_pagina(page)

                    if precio:
                        precios_a_guardar.append({
                            'proveedor': proveedor_nombre,
                            'url_producto': url_producto,
                            'precio': precio,
                        })
                        resultados.append(f"✅ {proveedor_nombre}: ${precio:,.0f}  [{metodo}]")
                    else:
                        resultados.append(f"⚠ {proveedor_nombre}: precio no encontrado en {url_producto}")

                    # Guardar texto para detectar contacto
                    try:
                        texto_extraido = page.locator('body').inner_text(timeout=3000)
                    except Exception:
                        pass

                    page.close()
                except Exception as e:
                    resultados.append(f"❌ {proveedor_nombre}: {str(e)[:100]}")

                # Detectar datos de contacto en el texto
                if texto_extraido:
                    _detectar_contacto(texto_extraido, comp_id, proveedor_id, contactos_a_guardar)

            ctx.close()
            browser.close()

        # --- Guardar resultados fuera del contexto async de Playwright ---
        for data in precios_a_guardar:
            RadarPrecio.objects.create(
                producto=producto,
                competidor_nombre=data['proveedor'],
                producto_referencia=data['url_producto'],   # ← URL exacta del producto
                precio_extraido=data['precio']
            )

        for data in contactos_a_guardar:
            try:
                prov = ProveedorCompetencia.objects.get(id=data['proveedor_id'])
                cambio = False
                if data['whatsapp'] and not prov.whatsapp_detectado:
                    prov.whatsapp_detectado = data['whatsapp'][:50]
                    cambio = True
                if data['email'] and not prov.email_detectado:
                    prov.email_detectado = data['email'][:254]
                    cambio = True
                if cambio:
                    prov.save()
                    resultados.append(f"✉ Contacto guardado para '{prov.nombre}'")
            except Exception:
                pass

        from .models import HistorialScraping
        errores = sum(1 for r in resultados if r.startswith('❌'))
        avisos  = sum(1 for r in resultados if r.startswith('⚠'))
        estado_final = 'ERROR' if errores == len(urls_semilla) else ('ADVERTENCIA' if (errores + avisos) > 0 else 'EXITO')

        HistorialScraping.objects.create(
            producto=producto,
            estado=estado_final,
            log='\n'.join(resultados)
        )

        return '\n'.join(resultados)

    except Exception as e:
        raise self.retry(exc=e, countdown=60)


def _detectar_contacto(texto: str, comp_id: int, proveedor_id: int, lista: list):
    """Extrae WhatsApp y Email del texto y los agrega a la lista de contactos."""
    email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', texto)
    wa_match = re.search(r'(?:\+?56\s*9|0?9)\s*\d{4}\s*\d{4}', texto)
    found_wa = wa_match.group(0).strip() if wa_match else None
    found_email = email_match.group(0).strip() if email_match else None
    if found_wa or found_email:
        lista.append({'id': comp_id, 'proveedor_id': proveedor_id, 'whatsapp': found_wa, 'email': found_email})
