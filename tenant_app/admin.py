from django.contrib import admin

from .models import Tienda, ProductoTienda, RadarPrecio, Orden, ProductoGlobal, CompetidorScraping, HistorialScraping, ProveedorCompetencia



from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from .tasks import scraping_precios_graficos

@admin.action(description="Ejecutar Scraping (Buscar precios ahora)")
def ejecutar_scraping_manual(modeladmin, request, queryset):
    contador = 0
    for producto in queryset:
        if producto.tienda.scraping_activado:
            # Enviar la tarea a Celery de forma asíncrona
            scraping_precios_graficos.delay(producto.id)
            contador += 1
            
    if contador > 0:
        messages.success(request, f'Se ha enviado la orden de scraping para {contador} productos. Los resultados aparecerán en Radar de Precios en unos minutos.')
    else:
        messages.warning(request, 'No se ejecutó scraping. Asegúrate de que las tiendas de los productos seleccionados tengan el "Scraping activado".')

@admin.action(description="Aprobar Tiendas Seleccionadas")
def aprobar_tiendas(modeladmin, request, queryset):
    tiendas_pendientes = queryset.filter(aprobada=False)
    contador = 0
    
    for tienda in tiendas_pendientes:
        tienda.aprobada = True
        tienda.save(update_fields=['aprobada', 'actualizado_en'])
        
        # Inyectar Catálogo Global a la Tienda (Si aún no lo tiene)
        if not ProductoTienda.objects.filter(tienda=tienda).exists():
            productos_globales = ProductoGlobal.objects.filter(activo=True)
            nuevos_productos = []
            for global_prod in productos_globales:
                nuevos_productos.append(
                    ProductoTienda(
                        tienda=tienda,
                        precio_base=global_prod.precio_costo,
                        margen_ganancia=10.00,  # 10% de ganancia defecto
                        producto_global=global_prod,
                        metadatos={
                            'nombre': global_prod.nombre,
                            'categoria': global_prod.categoria, 
                            'scraper': global_prod.origen_url
                        }
                    )
                )
            # Bulk create para eficiencia en Base de datos
            if nuevos_productos:
                ProductoTienda.objects.bulk_create(nuevos_productos)
        
        # Enviar correo de bienvenida al subcontratista
        try:
            send_mail(
                subject='¡Bienvenido a PrintFlow! Tu taller ha sido activado.',
                message=(
                    f"Hola {tienda.nombre_tienda},\n\n"
                    f"¡Buenas noticias! Tu cuenta en PrintFlow fue revisada y autorizada por la administración.\n\n"
                    f"Ya puedes iniciar sesión en tu panel de control, conectar tu cuenta de Mercado Pago y recibir ventas.\n\n"
                    f"Accede en cualquier momento desde tu propio subdominio:\n"
                    f"https://{tienda.subdominio}.riflero.cl/dashboard\n\n"
                    f"Mucho éxito con las ventas,\n"
                    f"El equipo de PrintFlow."
                ),
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@riflero.cl'),
                recipient_list=[tienda.usuario.email],
                fail_silently=True,
            )
        except Exception:
            pass
        contador += 1
        
    messages.success(request, f'{contador} tiendas fueron aprobadas y se les notificó por email.')

@admin.register(Tienda)
class TiendaAdmin(admin.ModelAdmin):
    list_display = (
        'nombre_tienda',
        'subdominio',
        'aprobada',
        'comuna',
        'taller_fisico',
        'scraping_activado',
        'creado_en',
    )
    list_filter = ('aprobada', 'taller_fisico', 'scraping_activado', 'creado_en')
    search_fields = ('nombre_tienda', 'subdominio', 'comuna__nombre')
    prepopulated_fields = {'subdominio': ('nombre_tienda',)}
    readonly_fields = ('creado_en', 'actualizado_en')
    ordering = ('nombre_tienda',)
    actions = [aprobar_tiendas]

    fieldsets = (
        (None, {
            'fields': ('usuario', 'nombre_tienda', 'subdominio', 'comuna'),
        }),
        ('Configuración', {
            'fields': ('aprobada', 'taller_fisico', 'scraping_activado'),
        }),
        ('Integración Marketplace', {
            'classes': ('collapse',),
            'fields': ('mp_vendedor_id', 'mp_access_token'),
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('creado_en', 'actualizado_en'),
        }),
    )

@admin.register(ProductoTienda)
class ProductoTiendaAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'tienda',
        'precio_base',
        'margen_ganancia',
        'creado_en',
    )
    list_filter = ('tienda', 'creado_en')
    search_fields = ('nombre', 'tienda__nombre_tienda',)
    readonly_fields = ('creado_en', 'actualizado_en')
    ordering = ('-creado_en',)
    actions = [ejecutar_scraping_manual]

    fieldsets = (
        (None, {
            'fields': ('tienda', 'nombre', 'precio_base', 'margen_ganancia', 'metadatos'),
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('creado_en', 'actualizado_en'),
        }),
    )


@admin.action(description="Ejecutar Scraping (Buscar precios para estos competidores)")
def ejecutar_scraping_manual_competidor(modeladmin, request, queryset):
    import json
    from django.urls import reverse
    from django.http import HttpResponseRedirect
    
    # Agrupar por producto para no ejecutar la tarea múltiples veces para el mismo producto
    productos_a_scrapear = list()
    for competidor in queryset:
        if competidor.activo and competidor.producto.tienda.scraping_activado:
            if competidor.producto.id not in productos_a_scrapear:
                productos_a_scrapear.append(competidor.producto.id)
            
    if not productos_a_scrapear:
        messages.warning(request, 'No se ejecutó scraping. Asegúrate de que los competidores estén activos y sus tiendas tengan el "Scraping activado".')
        return

    # Redirigimos a una vista especial en el admin para correr el scraping y ver los logs
    # Pasamos los IDs como argumento GET
    ids_str = ",".join(str(p) for p in productos_a_scrapear)
    url = reverse('admin:ejecutar_scraping_log') + f"?ids={ids_str}"
    return HttpResponseRedirect(url)


@admin.register(CompetidorScraping)
class CompetidorScrapingAdmin(admin.ModelAdmin):
    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('ejecutar-scraping-log/', self.admin_site.admin_view(self.ejecutar_scraping_log_view), name='ejecutar_scraping_log'),
        ]
        return custom_urls + urls

    def ejecutar_scraping_log_view(self, request):
        from django.shortcuts import render
        from tenant_app.models import ProductoTienda
        from tenant_app.tasks import scraping_precios_graficos
        
        ids_str = request.GET.get('ids', '')
        resultados_generales = []
        
        if request.method == 'POST':
            if ids_str:
                id_list = [int(i) for i in ids_str.split(',') if i.isdigit()]
                
                # Ejecutar sincrónicamente para ver el log inmediato
                for prod_id in id_list:
                    try:
                        producto = ProductoTienda.objects.get(id=prod_id)
                        # Llamamos directo a la función subyacente de Celery
                        resultado = scraping_precios_graficos(prod_id)
                        resultados_generales.append({
                            'producto': producto.nombre,
                            'log': resultado
                        })
                    except Exception as e:
                        resultados_generales.append({
                            'producto': f'ID {prod_id}',
                            'log': f'Error fatal de ejecución: {str(e)}'
                        })
                        
        context = dict(
            self.admin_site.each_context(request),
            title='Ejecución de Scraping en Vivo',
            ids_str=ids_str,
            resultados=resultados_generales
        )
        return render(request, 'admin/tenant_app/competidorscraping/scraping_log.html', context)

    list_display = (
        'proveedor',
        'producto',
        'activo',
        'creado_en',
    )
    list_filter = ('activo', 'producto__tienda', 'proveedor')
    search_fields = ('proveedor__nombre', 'producto__nombre')
    readonly_fields = ('creado_en', 'actualizado_en')
    ordering = ('producto', 'proveedor')
    autocomplete_fields = ['proveedor']
    actions = [ejecutar_scraping_manual_competidor]

    fieldsets = (
        (None, {
            'fields': ('producto', 'proveedor', 'activo'),
            'description': 'Selecciona el producto y el proveedor. El bot usará el sitio web del proveedor para buscar el precio.',
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('creado_en', 'actualizado_en'),
        }),
    )


@admin.register(ProveedorCompetencia)
class ProveedorCompetenciaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'sitio_web', 'whatsapp_detectado', 'email_detectado', 'creado_en')
    search_fields = ('nombre', 'sitio_web', 'whatsapp_detectado', 'email_detectado')
    ordering = ('nombre',)
    fieldsets = (
        ('Datos Generales', {
            'fields': ('nombre', 'sitio_web', 'url_patron_busqueda'),
            'description': (
                'El bot buscará el producto en <strong>Sitio Web</strong> usando el <strong>Patrón de búsqueda</strong>. '
                'Ej: si el buscador es <code>graficavm.cl/?s=pendón</code>, el patrón es <code>?s={q}</code>. '
                'Si lo dejas vacío, el bot probará los patrones más comunes automáticamente.'
            ),
        }),
        ('Contacto Detectado por el Bot', {
            'fields': ('whatsapp_detectado', 'email_detectado'),
            'description': 'Información extraída automáticamente por el radar de precios. Puedes editarla manualmente.',
        }),
    )


@admin.register(RadarPrecio)
class RadarPrecioAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'producto',
        'precio_extraido',
        'fecha_extraccion',
    )
    list_filter = ('competidor_nombre', 'fecha_extraccion')
    search_fields = ('competidor_nombre', 'producto_referencia', 'producto__tienda__nombre_tienda')
    readonly_fields = ('fecha_extraccion',)
    ordering = ('-fecha_extraccion',)

    fieldsets = (
        (None, {
            'fields': ('producto', 'competidor_nombre', 'producto_referencia', 'precio_extraido'),
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('fecha_extraccion',),
        }),
    )


@admin.register(Orden)
class OrdenAdmin(admin.ModelAdmin):
    list_display = (
        '__str__',
        'monto_total',
        'estado_pago',
        'nombre_cliente',
        'creado_en',
    )
    list_filter = ('estado_pago', 'tienda', 'creado_en')
    search_fields = ('nombre_cliente', 'email_cliente', 'mp_payment_id', 'tienda__nombre_tienda')
    readonly_fields = ('creado_en', 'actualizado_en')
    ordering = ('-creado_en',)

    fieldsets = (
        ('Datos Venta', {
            'fields': ('tienda', 'producto', 'monto_total', 'estado_pago', 'mp_payment_id'),
        }),
        ('Datos Cliente', {
            'fields': ('nombre_cliente', 'email_cliente'),
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('creado_en', 'actualizado_en'),
        }),
    )

@admin.register(HistorialScraping)
class HistorialScrapingAdmin(admin.ModelAdmin):
    list_display = (
        'fecha',
        'producto_scrapeado',
        'estado',
    )
    list_filter = ('estado', 'fecha')
    search_fields = ('producto_scrapeado', 'detalles')
    readonly_fields = ('fecha', 'producto_scrapeado', 'estado', 'detalles')
    
    # Prevenir que se agreguen o modifiquen manualmente desde el panel de admin
    def has_add_permission(self, request):
        return False
        
    def has_change_permission(self, request, obj=None):
        return False

