import re
from django.conf import settings
from django.http import Http404
from tenant_app.models import Tienda

class TenantMiddleware:
    """
    Middleware para arquitectura Multi-tenant basada en subdominios.
    Captura el subdominio de la request y lo inyecta en `request.tenant`.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().lower()  # Ej: mitaller.riflero.cl:8000 o localhost:8000

        # Limpiar puerto si existe
        if ':' in host:
            host = host.split(':')[0]

        # Extraer dominios base (ej: riflero.cl, localhost)
        dominios_base = [d.split(':')[0] for d in settings.ALLOWED_HOSTS if not d.startswith('.')]
        
        # Identificar subdominio
        subdominio = None
        for dominio in dominios_base:
            if host.endswith(f".{dominio}"):
                # Extraer la parte antes de .riflero.cl
                subdominio = host[:-len(f".{dominio}")]
                break
        
        # Excepciones que no son tiendas (www, app, admin, api, etc)
        subdominios_reservados = ['www', 'app', 'admin', 'api']

        if subdominio and subdominio not in subdominios_reservados:
            try:
                # Guardar el tenant en el request para que las vistas puedan usarlo
                request.tenant = Tienda.objects.get(subdominio=subdominio)
            except Tienda.DoesNotExist:
                # Si el subdominio no existe en la base de datos, mostramos 404
                raise Http404(f"La tienda '{subdominio}' no existe.")
        else:
            # Es el dominio principal (o un subdominio reservado)
            request.tenant = None

        response = self.get_response(request)
        return response
