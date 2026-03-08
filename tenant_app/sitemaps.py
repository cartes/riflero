"""
Sitemaps dinámicos multi-tenant para riflero.cl.

Cada subdominio ({tienda}.riflero.cl/sitemap.xml) expone únicamente los
ProductoTienda que pertenecen a esa tienda, aislando el SEO por tenant.
El middleware TenantMiddleware ya habrá inyectado request.tenant antes
de que el sitemap sea generado.
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from tenant_app.models import ProductoTienda


class TiendaProductosSitemap(Sitemap):
    """
    Sitemap que lista los productos del tenant activo.

    Cada URL apunta a la raíz de la tienda con un anchor de producto,
    ya que el catálogo es una single-page con todos los productos visibles.
    Si en el futuro cada producto tiene su propia URL, basta con actualizar
    ``location()``.
    """

    changefreq = 'weekly'
    priority = 0.8
    protocol = 'https'

    def __init__(self, request=None):
        self._request = request
        super().__init__()

    def get_urls(self, page=1, site=None, protocol=None):
        # Sobreescribimos get_urls para inyectar el request en cada item.
        return super().get_urls(page=page, site=site, protocol=protocol)

    def items(self):
        if self._request is None:
            return ProductoTienda.objects.none()

        tienda = getattr(self._request, 'tenant', None)
        if tienda is None:
            return ProductoTienda.objects.none()

        return (
            ProductoTienda.objects
            .filter(tienda=tienda)
            .select_related('tienda')
            .order_by('orden_visual')
        )

    def location(self, producto):
        # La tienda es single-page; cada producto se referencia como /#producto-{id}
        return f'/#producto-{producto.pk}'

    def lastmod(self, producto):
        return producto.actualizado_en
