from django.contrib import admin

from .models import Tienda, ProductoTienda, RadarPrecio, Orden, ProductoGlobal



from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages

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
    search_fields = ('tienda__nombre_tienda',)
    readonly_fields = ('creado_en', 'actualizado_en')
    ordering = ('-creado_en',)

    fieldsets = (
        (None, {
            'fields': ('tienda', 'precio_base', 'margen_ganancia', 'metadatos'),
        }),
        ('Auditoría', {
            'classes': ('collapse',),
            'fields': ('creado_en', 'actualizado_en'),
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

