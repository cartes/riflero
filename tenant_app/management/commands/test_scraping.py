import time
from decimal import Decimal
from django.core.management.base import BaseCommand
from tenant_app.models import Tienda, ProductoTienda, RadarPrecio
from tenant_app.tasks import extraer_precio_competidor

class Command(BaseCommand):
    help = 'Genera datos de prueba (Fixtures) y ejecuta el test local de Scraping con Playwright'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS("=== Iniciando Test de Inteligencia de Mercado ==="))
        
        # 1. Crear Tienda de prueba
        tienda, created = Tienda.objects.get_or_create(
            subdominio='mitaller',
            defaults={
                'nombre_tienda': 'Mi Taller Gráfico',
                'comuna_base': 'Santiago Centro',
                'taller_fisico': True,
                'scraping_activado': True
            }
        )
        if created:
            self.stdout.write(f"[*] Creada Tienda: {tienda.nombre_tienda} ({tienda.subdominio})")
        else:
            self.stdout.write(f"[*] Usando Tienda existente: {tienda.nombre_tienda}")
            # Aseguramos que tenga scraping activo
            tienda.scraping_activado = True
            tienda.save()

        # 2. Crear Productos de prueba
        p_flyers, created = ProductoTienda.objects.get_or_create(
            tienda=tienda,
            defaults={'precio_base': Decimal('0.00'), 'margen_ganancia': Decimal('20.00')}
        )
        if created:
            self.stdout.write(f"[*] Creado ProductoTienda: Flyers 10x15 (Margen: {p_flyers.margen_ganancia}%)")
        else:
            p_flyers.margen_ganancia = Decimal('20.00')
            p_flyers.precio_base = Decimal('0.00') # Reset for testing
            p_flyers.save()
            self.stdout.write(f"[*] Reseteado ProductoTienda: Flyers 10x15 (Base: 0, Margen: {p_flyers.margen_ganancia}%)")

        p_tarjetas, created = ProductoTienda.objects.get_or_create(
            tienda=tienda,
            defaults={'precio_base': Decimal('0.00'), 'margen_ganancia': Decimal('15.00')}
        )
        if created:
            self.stdout.write(f"[*] Creado ProductoTienda: Tarjetas de Presentación (Margen: {p_tarjetas.margen_ganancia}%)")
        else:
            p_tarjetas.margen_ganancia = Decimal('15.00')
            p_tarjetas.precio_base = Decimal('0.00')
            p_tarjetas.save()
            self.stdout.write(f"[*] Reseteado ProductoTienda: Tarjetas de Presentación (Base: 0, Margen: {p_tarjetas.margen_ganancia}%)")


        # 3. Datos de Scraping (Ejemplo real usando graficavm.cl)
        # Asumiendo que graficavm.cl es WooCommerce y su selector de precio principal contiene '.price'
        competidores = [
            {
                'producto_id': p_flyers.id,
                'nombre': 'Gráfica VM',
                'url': 'https://www.graficavm.cl/producto/volantes-10x15-cm-impresion-1-cara/',
                'selector': 'p.price'
            },
            {
                'producto_id': p_tarjetas.id,
                'nombre': 'Gráfica VM',
                'url': 'https://www.graficavm.cl/producto/tarjetas-de-presentacion/',
                'selector': 'p.price'
            }
        ]

        self.stdout.write(self.style.WARNING("\n=== Ejecutando Scraping Local con Playwright (Esto tomará unos segundos) ==="))
        
        # 4. Ejecutar las tareas síncronamente (llamando la función en vez de .delay() para testear enseguida)
        for comp in competidores:
            self.stdout.write(f"Navegando a: {comp['url']}...")
            try:
                # Llamada sincrónica para el script de consola (testing mode)
                # En producción se usaría extraer_precio_competidor.delay(...)
                resultado = extraer_precio_competidor(
                    comp['producto_id'], 
                    comp['nombre'], 
                    comp['url'], 
                    comp['selector']
                )
                self.stdout.write(self.style.SUCCESS(f">> Tarea Finalizada: {resultado}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f">> Error en scraping: {e}"))
        
        # 5. Validar los resultados de Pricing Dinámico
        self.stdout.write(self.style.WARNING("\n=== Validación de Pricing Dinámico (Signals) ==="))
        
        # Refrescar desde DB
        p_flyers.refresh_from_db()
        p_tarjetas.refresh_from_db()

        for p, nombre in [(p_flyers, "Flyers 10x15"), (p_tarjetas, "Tarjetas de Presentación")]:
            radar = RadarPrecio.objects.filter(producto=p).order_by('-fecha_extraccion').first()
            if radar:
                self.stdout.write(self.style.SUCCESS(f"\n[{nombre}]"))
                self.stdout.write(f"  - Extraído por Celery: ${radar.precio_extraido}")
                self.stdout.write(f"  - Base actualizado en Tienda: ${p.precio_base}")
                self.stdout.write(f"  - Margen de Ganancia local: {p.margen_ganancia}%")
                self.stdout.write(self.style.SUCCESS(f"  -> PRECIO FINAL AL PÚBLICO: ${p.precio_final}"))
            else:
                self.stdout.write(self.style.ERROR(f"\n[{nombre}] No se registró precio en RadarPrecio. Revise los logs de Playwright."))
        
        self.stdout.write("\nTest finalizado.")
