from django.conf import settings
from django.urls import reverse


def sidebar_context(request):
    """
    Context processor that provides sidebar link URLs, active states
    for layout_panel.html, and SITE_DOMAIN for subdomain URL construction.
    """
    url_name = getattr(getattr(request, 'resolver_match', None), 'url_name', '')

    return {
        'SITE_DOMAIN': settings.SITE_DOMAIN,
        'dashboard_url': reverse('dashboard'),
        'productos_url': reverse('dashboard_productos'),
        'ventas_url': reverse('dashboard_ventas'),
        'ajustes_url': reverse('dashboard_ajustes'),
        'is_dashboard': url_name == 'dashboard',
        'is_productos': url_name in ('dashboard_productos', 'agregar_producto_catalogo', 'editar_producto'),
        'is_ventas': url_name == 'dashboard_ventas',
        'is_ajustes': url_name in ('dashboard_ajustes', 'password_change'),
        'is_apariencia': url_name == 'ajustes_apariencia',
        'is_ajustes_group': url_name in ('dashboard_ajustes', 'password_change', 'ajustes_apariencia'),
    }
