"""
Modelos de tenant_app.

Tienda representa a cada subcontratista (tienda/taller) que opera
dentro de la plataforma riflero.cl.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User

# ===========================================================================
# GEOGRAFÍA (DPA CHILE)
# ===========================================================================
class Region(models.Model):
    nombre = models.CharField(_('nombre de la región'), max_length=150)
    orden = models.IntegerField(_('orden geoespacial'), default=0)

    class Meta:
        verbose_name = _('región')
        verbose_name_plural = _('regiones')
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class Provincia(models.Model):
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='provincias')
    nombre = models.CharField(_('nombre de la provincia'), max_length=150)

    class Meta:
        verbose_name = _('provincia')
        verbose_name_plural = _('provincias')
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Comuna(models.Model):
    provincia = models.ForeignKey(Provincia, on_delete=models.CASCADE, related_name='comunas')
    nombre = models.CharField(_('nombre de la comuna'), max_length=150)

    class Meta:
        verbose_name = _('comuna')
        verbose_name_plural = _('comunas')
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


# ===========================================================================
# TENANT
# ===========================================================================
class Tienda(models.Model):
    """
    Representa un subcontratista (tienda/taller) dentro de la plataforma.

    Cada Tienda opera bajo su propio subdominio (multi-tenant) y puede
    configurar su presencia física y su capacidad de scraping de precios.
    """

    usuario = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='tienda',
        verbose_name=_('usuario administrador'),
        null=True, blank=True,
        help_text=_('Usuario de Django que administra este taller.')
    )

    nombre_tienda = models.CharField(
        _('nombre de la tienda'),
        max_length=150,
        help_text=_('Nombre visible de la tienda o taller.'),
    )

    subdominio = models.SlugField(
        _('subdominio'),
        max_length=63,          # RFC 1035: máximo 63 chars por etiqueta DNS
        unique=True,
        db_index=True,
        help_text=_(
            'Subdominio único para esta tienda (ej: "mitaller"). '
            'Solo letras minúsculas, números y guiones.'
        ),
    )

    comuna = models.ForeignKey(
        Comuna,
        on_delete=models.SET_NULL,
        verbose_name=_('comuna base'),
        related_name='tiendas',
        null=True, blank=True,
        help_text=_('Comuna donde opera principalmente la tienda.'),
    )

    direccion = models.CharField(
        _('dirección'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Dirección física para retiro de pedidos.'),
    )

    taller_fisico = models.BooleanField(
        _('tiene taller físico'),
        default=True,
        help_text=_('Indica si la tienda cuenta con un local físico.'),
    )

    aprobada = models.BooleanField(
        _('aprobada por admin'),
        default=False,
        help_text=_('Indica si la tienda fue revisada y autorizada por la administración central para operar.')
    )

    scraping_activado = models.BooleanField(
        _('scraping activado'),
        default=False,
        help_text=_(
            'Habilita el scraping automático de precios para esta tienda. '
            'Requiere configuración adicional de Celery y Playwright.'
        ),
    )

    # Configuración Mercado Pago (Marketplace / Split Payments)
    mp_vendedor_id = models.CharField(
        _('ID de vendedor en Mercado Pago'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('ID de usuario del subcontratista en Mercado Pago para recibir Split de Pagos.')
    )
    mp_access_token = models.CharField(
        _('access token de Mercado Pago'),
        max_length=255,
        blank=True,
        null=True,
        help_text=_('Token OAuth necesario para cobrar a su nombre u operar pagos de forma delegada.')
    )

    # Auditoría automática
    creado_en = models.DateTimeField(_('creado en'), auto_now_add=True)
    actualizado_en = models.DateTimeField(_('actualizado en'), auto_now=True)

    class Meta:
        verbose_name = _('tienda')
        verbose_name_plural = _('tiendas')
        ordering = ['nombre_tienda']
        indexes = [
            models.Index(fields=['subdominio']),
            models.Index(fields=['scraping_activado']),
        ]

    def __str__(self) -> str:
        return f'{self.nombre_tienda} ({self.subdominio})'

    @property
    def factor_confianza(self):
        """
        Multiplicador o Puntos extra otorgados por verificaciones de calidad (Sello de Verificación).
        """
        puntos = 0.0
        if self.taller_fisico:
            puntos += 0.5  # Sello de Verificación: Al tener locación real (Taller Físico).
        if self.scraping_activado:
            puntos += 0.2  # Bonus por mantener precios nivelados al mercado.
        return puntos

    @property
    def puntaje_global(self):
        """
        El peso SEO interno de PrintFlow. Pondera su reputación base (PrintScore) + factor de confianza.
        """
        base_score = 5.0
        if hasattr(self, 'printscore'):
            base_score = self.printscore.calcular_puntaje_base()
            
        return round(min(5.0, base_score + self.factor_confianza), 1)

    def coincidencia_geografica(self, comuna_cliente_nombre):
        """
        Devuelve un ratio de matching geoespacial. Coincidencia exacta por texto de comuna.
        """
        if self.comuna and comuna_cliente_nombre and self.comuna.nombre.strip().lower() == comuna_cliente_nombre.strip().lower():
            return 1.5  # 50% de Boost si el comprador y la imprenta están en la misma comuna
        return 1.0

    @property
    def url_base(self) -> str:
        """Retorna la URL base del subdominio de esta tienda."""
        return f'https://{self.subdominio}.riflero.cl'

    @property
    def puede_scrapear(self) -> bool:
        """True solo si el scraping está habilitado para esta tienda."""
        return self.scraping_activado


class ProductoGlobal(models.Model):
    """
    Catálogo Maestro alimentado por los procesos de Web Scraping de proveedores.
    Sirve como plantilla o precio de referencia (costo) para los talleres.
    """
    nombre = models.CharField(_('nombre de producto'), max_length=150)
    precio_costo = models.DecimalField(
        _('precio de costo'),
        max_digits=10, decimal_places=2,
        help_text=_('Precio real (costo proveedor) extraído vía scraping.')
    )
    categoria = models.CharField(_('categoría'), max_length=100, default='General')
    origen_url = models.URLField(_('url origen scraper'), blank=True, null=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nombre} (${self.precio_costo})"

class ProductoTienda(models.Model):
    """
    Representa un producto o servicio ofrecido por una Tienda (subcontratista).
    """
    tienda = models.ForeignKey(
        Tienda,
        on_delete=models.CASCADE,
        related_name='productos',
        verbose_name=_('tienda'),
        help_text=_('Tienda a la que pertenece este producto.'),
    )
    
    nombre = models.CharField(
        _('nombre del producto'),
        max_length=150,
        default='Producto Nuevo',
        help_text=_('Nombre de venta del producto (ej: Tarjetas de presentación 300g).'),
    )

    termino_busqueda = models.CharField(
        _('término de búsqueda para scraping'),
        max_length=200,
        blank=True,
        null=True,
        help_text=_('Palabras clave que el bot usará para buscar este producto en la competencia. '
                    'Si está vacío, se usa el nombre del producto. '
                    'Ej: "pendón roller 80x200 cm doble cara"'),
    )

    precio_base = models.DecimalField(
        _('precio base'),
        max_digits=10,
        decimal_places=2,
        help_text=_('Precio base del producto/servicio.'),
    )
    
    producto_global = models.ForeignKey(
        ProductoGlobal,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='derivados',
        help_text=_('Referencia al producto maestro del que heredó este artículo.')
    )
    
    margen_ganancia = models.DecimalField(
        _('margen de ganancia'),
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text=_('Margen de ganancia aplicado al precio base (ej: 15.50 para 15.5%).'),
    )

    metadatos = models.JSONField(
        _('metadatos'),
        default=dict,
        blank=True,
        help_text=_('Atributos dinámicos del producto (colores, tamaños, características extra).'),
    )

    imagen = models.ImageField(
        _('imagen de vista previa'),
        upload_to='productos/',
        null=True,
        blank=True,
        help_text=_('Imagen para mostrar en el catálogo de la tienda.')
    )

    orden_visual = models.IntegerField(
        _('orden en catálogo'),
        default=0,
        help_text=_('Define la posición manual del producto en la tienda (Drag & Drop).')
    )

    # Auditoría automática
    creado_en = models.DateTimeField(_('creado en'), auto_now_add=True)
    actualizado_en = models.DateTimeField(_('actualizado en'), auto_now=True)

    class Meta:
        verbose_name = _('producto de tienda')
        verbose_name_plural = _('productos de tienda')
        ordering = ['orden_visual', '-creado_en']
        indexes = [
            models.Index(fields=['tienda']),
        ]

    def __str__(self) -> str:
        return f'{self.nombre} - {self.tienda.nombre_tienda} (${self.precio_final})'

    @property
    def precio_final(self):
        """Calcula el precio final incluyendo el margen de ganancia."""
        from decimal import Decimal
        if self.precio_base is None:
            return Decimal('0.00')
        return self.precio_base * Decimal(str(1 + (float(self.margen_ganancia) / 100.0)))


class RadarPrecio(models.Model):
    """
    Motor de Inteligencia de Mercado.
    Almacena los precios extraídos de competidores para un producto específico.
    """
    producto = models.ForeignKey(
        ProductoTienda,
        on_delete=models.CASCADE,
        related_name='precios_radar',
        verbose_name=_('producto'),
    )
    competidor_nombre = models.CharField(
        _('nombre del competidor'),
        max_length=150,
        help_text=_('Ej: Imprenta Okey, Gráfica VM'),
    )
    producto_referencia = models.CharField(
        _('referencia del producto'),
        max_length=255,
        help_text=_('URL o nombre exacto del producto en el sitio del competidor'),
    )
    precio_extraido = models.DecimalField(
        _('precio base extraído'),
        max_digits=10,
        decimal_places=2,
    )
    fecha_extraccion = models.DateTimeField(
        _('fecha de extracción'),
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _('radar de precio')
        verbose_name_plural = _('radares de precios')
        ordering = ['-fecha_extraccion']
        indexes = [
            models.Index(fields=['producto', '-fecha_extraccion']),
        ]

    def __str__(self) -> str:
        return f'{self.competidor_nombre} - {self.precio_extraido}'


class ProveedorCompetencia(models.Model):
    """
    Tabla maestra de las imprentas o competidores.
    Evita que cada producto deba escribir el "nombre" y mantiene los contactos.
    """
    nombre = models.CharField(
        _('nombre del competidor'),
        max_length=150,
        unique=True,
        help_text=_('Nombre genérico de la empresa (Ej: Imprenta Okey).')
    )
    sitio_web = models.URLField(
        _('sitio web principal'),
        blank=True,
        null=True,
        help_text=_('URL general de la imprenta. El bot navegará desde aquí.')
    )
    url_patron_busqueda = models.CharField(
        _('patrón de URL del buscador'),
        max_length=300,
        blank=True,
        null=True,
        help_text=_('Patrón personalizado con {q} como marcador para el término. '
                    'Ej: "?s={q}" o "/search?query={q}". '
                    'Si está vacío, el bot intentará patrones comúnes automáticamente.')
    )
    whatsapp_detectado = models.CharField(
        _('WhatsApp detectado'),
        max_length=50,
        blank=True,
        null=True,
        help_text=_('Número extraído automáticamente.')
    )
    email_detectado = models.EmailField(
        _('Email detectado'),
        blank=True,
        null=True,
        help_text=_('Correo electrónico extraído automáticamente.')
    )
    creado_en = models.DateTimeField(_('creado en'), auto_now_add=True)

    class Meta:
        verbose_name = _('proveedor competencia')
        verbose_name_plural = _('proveedores competencia')
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

class CompetidorScraping(models.Model):
    """
    Vincula un producto propio con un proveedor competidor para el radar de precios.
    El bot visitará el `sitio_web` del proveedor para buscar el precio de este producto.
    """
    producto = models.ForeignKey(
        ProductoTienda,
        on_delete=models.CASCADE,
        related_name='competidores_scraping',
        verbose_name=_('producto objetivo'),
        help_text=_('Producto propio al que se le buscarán precios competidores.')
    )
    
    proveedor = models.ForeignKey(
        ProveedorCompetencia,
        on_delete=models.CASCADE,
        related_name='scrapings',
        verbose_name=_('Proveedor competidor'),
    )
    
    activo = models.BooleanField(
        _('activo'),
        default=True,
        help_text=_('Indica si el bot debe visitar la URL de este proveedor o si está pausado.')
    )
    
    creado_en = models.DateTimeField(_('creado en'), auto_now_add=True)
    actualizado_en = models.DateTimeField(_('actualizado en'), auto_now=True)

    class Meta:
        verbose_name = _('competidor para scraping')
        verbose_name_plural = _('competidores para scraping')
        ordering = ['producto', 'proveedor__nombre']
        unique_together = ('producto', 'proveedor')

    def __str__(self):
        proveedor_nombre = self.proveedor.nombre if self.proveedor else '(sin proveedor)'
        return f"{proveedor_nombre} ↔ {self.producto}"


# ===========================================================================
# SIGNALS (Lógica de Pricing Dinámico)
# ===========================================================================
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=RadarPrecio)
def actualizar_precio_dinamico(sender, instance, created, **kwargs):
    """
    Pricing Dinámico: 
    Cada vez que entra un nuevo registro de RadarPrecio (scraping),
    tomamos el precio más bajo registrado en RadarPrecio para ese producto,
    y actualizamos el precio_base del ProductoTienda vinculado.

    El precio final de venta al público (propiedad `precio_final`) 
    calculará automáticamente incluyendo el `margen_ganancia`.
    """
    if created:
        producto = instance.producto
        
        # Tomamos el precio más bajo registrado en RadarPrecio
        from django.db.models import Min
        precio_mas_bajo = RadarPrecio.objects.filter(producto=producto).aggregate(
            min_precio=Min('precio_extraido')
        )['min_precio']
        
        if precio_mas_bajo is not None:
            producto.precio_base = precio_mas_bajo
            # save(update_fields) es más rápido y evita triggers secundarios innecesarios
            producto.save(update_fields=['precio_base', 'actualizado_en'])

            # (Opcional) Propagar a todas las demás tiendas con scraping activado que tengan este producto base
            if producto.producto_global:
                ProductoTienda.objects.filter(
                    producto_global=producto.producto_global,
                    tienda__scraping_activado=True
                ).exclude(id=producto.id).update(
                    precio_base=precio_mas_bajo
                )


# ===========================================================================
# ORDENES / COMPRAS
# ===========================================================================
class Orden(models.Model):
    """
    Transacción de compra de un producto por un cliente final, usando Mercado Pago en el subdominio.
    """
    ESTADOS_PAGO = [
        ('pendiente', 'Pendiente'),
        ('completado', 'Completado'),
        ('fallido', 'Fallido'),
        ('rechazado', 'Rechazado'),
    ]

    tienda = models.ForeignKey(
        Tienda, 
        on_delete=models.CASCADE, 
        related_name='ordenes',
        verbose_name=_('tienda')
    )
    producto = models.ForeignKey(
        ProductoTienda, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='ordenes_asociadas',
        verbose_name=_('producto')
    )
    monto_total = models.DecimalField(
        _('monto total pagado'), 
        max_digits=10, 
        decimal_places=2
    )
    estado_pago = models.CharField(
        _('estado del pago'), 
        max_length=20, 
        choices=ESTADOS_PAGO, 
        default='pendiente'
    )
    mp_payment_id = models.CharField(
        _('ID de pago MP'), 
        max_length=150, 
        blank=True, 
        null=True
    )
    nombre_cliente = models.CharField(
        _('nombre del cliente'), 
        max_length=150
    )
    email_cliente = models.EmailField(
        _('email del cliente')
    )
    
    # Auditoría
    creado_en = models.DateTimeField(_('creado en'), auto_now_add=True)
    actualizado_en = models.DateTimeField(_('actualizado en'), auto_now=True)

    class Meta:
        verbose_name = _('orden')
        verbose_name_plural = _('órdenes')
        ordering = ['-creado_en']
        indexes = [
            models.Index(fields=['tienda', '-creado_en']),
            models.Index(fields=['estado_pago']),
            models.Index(fields=['mp_payment_id']),
        ]

    def __str__(self):
        return f"Orden #{self.id} de {self.tienda.nombre_tienda} ({self.get_estado_pago_display()})"


class PrintScore(models.Model):
    """
    Sistema de evaluación de calidad para talleres subcontratistas.
    Evita la guerra de precios midiendo el valor real de su servicio.
    """
    tienda = models.OneToOneField(Tienda, on_delete=models.CASCADE, related_name='printscore')
    cumplimiento_plazos = models.FloatField(default=5.0, help_text=_('Puntuación de 0 a 5 por entregar a tiempo.'))
    calidad_impresion = models.FloatField(default=5.0, help_text=_('Puntuación de 0 a 5 por calidad del producto final.'))
    tasa_retorno = models.FloatField(default=0.0, help_text=_('Porcentaje de trabajos devueltos o rechazados.'))
    
    actualizado_en = models.DateTimeField(auto_now=True)

    def calcular_puntaje_base(self):
        # Fórmula simple: Promedio de notas menos penalización por retornos
        promedio_notas = (self.cumplimiento_plazos + self.calidad_impresion) / 2.0
        penalizacion = (self.tasa_retorno / 100.0) * 5.0
        return max(0.0, min(5.0, promedio_notas - penalizacion))

    def __str__(self):
        return f"Score de {self.tienda.nombre_tienda}: {self.calcular_puntaje_base():.1f}"


class HistorialScraping(models.Model):
    """
    Registro visual para que el administrador pueda ver en el panel de Django
    cuándo terminó un scraping y qué resultados obtuvo.
    """
    ESTADOS_SCRAPING = [
        ('EXITO', 'Éxito'),
        ('ADVERTENCIA', 'Éxito parcial / Advertencias'),
        ('ERROR', 'Error'),
    ]

    fecha = models.DateTimeField(_('fecha de ejecución'), auto_now_add=True)
    producto_scrapeado = models.CharField(_('producto scrapeado'), max_length=255)
    estado = models.CharField(_('estado final'), max_length=50, choices=ESTADOS_SCRAPING, default='EXITO')
    detalles = models.TextField(_('detalles de la ejecución'), blank=True)

    class Meta:
        verbose_name = _('historial de scraping')
        verbose_name_plural = _('historial de scrapings')
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.fecha.strftime('%d/%m/%Y %H:%M')} - {self.producto_scrapeado} ({self.get_estado_display()})"


