import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.core.mail import mail_admins
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from tenant_app.forms import RegistroTiendaForm
from tenant_app.models import Orden, ProductoGlobal, ProductoTienda, RadarPrecio, Tienda

logger = logging.getLogger(__name__)

def index(request):
    """
    Vista principal.
    Si el middleware inyectó a `request.tenant` y NO es None (estamos en un subdominio válido), 
    se debe renderizar la tienda (White Label).
    De lo contrario, cargamos la vista estática del Landig / Home.
    """
    if getattr(request, 'tenant', None):
        return render_vista_tienda(request)
    else:
        return render_vista_landing(request)


def render_vista_tienda(request):
    """
    Renderiza el catálogo público de un subcontratista específico (request.tenant).
    """
    tienda = request.tenant
    productos = ProductoTienda.objects.filter(tienda=tienda)
    
    context = {
        'tienda': tienda,
        'productos': productos,
    }
    return render(request, 'tenant_app/tienda_base.html', context)


def render_vista_landing(request):
    """
    Renderiza la Landing Page principal (Riflero / PrintFlow).
    Inyecta las tiendas más destacadas (Verificadas y con mejor PrintScore).
    """
    todas_tiendas = list(Tienda.objects.select_related('printscore').all())
    
    # Ordenamos en memoria usando la property `puntaje_global` y bajamos las que no tienen local físico
    todas_tiendas.sort(
        key=lambda t: (t.puntaje_global, t.taller_fisico), 
        reverse=True
    )
    
    # Top 6 imprentas para el Home
    top_tiendas = todas_tiendas[:6]

    context = {
        'top_tiendas': top_tiendas
    }
    return render(request, 'tenant_app/landing_page.html', context)


def buscar_view(request):
    """
    Motor de Búsqueda Público (Marketplace).
    Filtra productos según el query ingresado y ordena las tiendas según su `puntaje_global`.
    """
    query = request.GET.get('q', '').strip()
    comuna_cliente = request.GET.get('comuna', '').strip()

    productos = []
    
    if query:
        # Búsqueda simple: buscaremos "query" dentro de los metadatos o nombre del producto.
        # Filtramos primero la existencia de algo en los metadatos.
        base_qs = ProductoTienda.objects.filter(
            Q(metadatos__icontains=query) | Q(tienda__nombre_tienda__icontains=query)
        ).select_related('tienda', 'tienda__printscore')

        # Ahora necesitamos inyectar el multiplicador geográfico y ordenar en memoria (O por BD si hubiese GIS, pero usaremos list sorting por ahora).
        resultados = []
        for p in base_qs:
            # Calcular el multiplicador geoespacial al vuelo:
            multiplicador = p.tienda.coincidencia_geografica(comuna_cliente)
            
            # Score final para el ranking de búsqueda
            score_busqueda = float(p.tienda.puntaje_global) * multiplicador
            
            resultados.append({
                'producto': p,
                'tienda': p.tienda,
                'score_busqueda': score_busqueda,
                'es_local': multiplicador > 1.0  # Flag booleano para UI
            })
            
        # Ordenar resultados descendente según el score real (Evita guerra de precios pura)
        resultados.sort(key=lambda x: x['score_busqueda'], reverse=True)
        productos = resultados

    context = {
        'query': query,
        'comuna_cliente': comuna_cliente,
        'resultados': productos,
    }
    return render(request, 'tenant_app/buscar.html', context)


# ===========================================================================
# VISTAS PRIVADAS (SAAS / DASHBOARD SUBCONTRATISTA)
# ===========================================================================

def registro_view(request):
    """
    Controlador para crear un nuevo usuario y su tienda.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = RegistroTiendaForm(request.POST)
        if form.is_valid():
            user, tienda = form.save()
            # Notificar al staff de la nueva tienda
            try:
                mail_admins(
                    subject=f"Nueva Tienda Registrada: {tienda.nombre_tienda}",
                    message=f"El taller {tienda.nombre_tienda} ({tienda.subdominio}.riflero.cl) se ha registrado. Email: {user.email}. Por favor revisa el admin para aprobarla.",
                    fail_silently=True
                )
            except Exception:
                pass # Evitar que falle el registro si el SMTP falla
                
            # Loguear automáticamente
            login(request, user)
            messages.success(request, '¡Registro exitoso! Estamos revisando su cuenta.')
            return redirect('pendiente_aprobacion')
    else:
        form = RegistroTiendaForm()
        
    return render(request, 'tenant_app/registro.html', {'form': form})

@login_required(login_url='login')
def pendiente_aprobacion_view(request):
    """
    Vista de bloqueo ("holding page") para tiendas esperando aprobación admin.
    """
    try:
        if request.user.tienda.aprobada:
            return redirect('dashboard')
    except AttributeError:
        # No tiene tienda o es admin
        pass
        
    return render(request, 'tenant_app/pendiente_aprobacion.html')

def login_view(request):
    """
    Vista de inicio de sesión para los dueños de los talleres.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Credenciales inválidas.')
            
    return render(request, 'tenant_app/login.html')

def logout_view(request):
    """
    Cierra la sesión del usuario actual.
    """
    logout(request)
    return redirect('login')

@login_required(login_url='login')
def dashboard_view(request):
    """
    Panel central del subcontratista (Dashboard Inicio). Muestra sus métricas clave.
    """
    try:
        tienda = request.user.tienda
        if not tienda.aprobada:
            return redirect('pendiente_aprobacion')
    except AttributeError:
        messages.error(request, 'No tienes un Taller vinculado a esta cuenta.')
        return redirect('index')

    ordenes_pagadas = Orden.objects.filter(tienda=tienda, estado_pago='completado')
    ventas_totales = sum(o.monto_total for o in ordenes_pagadas)
    
    # Listado de productos para el filtro del radar
    listado_productos = ProductoTienda.objects.filter(tienda=tienda).order_by('nombre')
    
    # Obtener las últimas 5 detecciones de precios competitivos para los productos de esta tienda
    radar_query = RadarPrecio.objects.filter(producto__tienda=tienda).select_related('producto')
    
    filtro_producto_id = request.GET.get('producto_id')
    if filtro_producto_id and filtro_producto_id.isdigit():
        radar_query = radar_query.filter(producto_id=filtro_producto_id)
        
    radar_reciente = radar_query.order_by('-fecha_extraccion')[:5]
    
    context = {
        'tienda': tienda,
        'ventas_totales': ventas_totales,
        'radar_reciente': radar_reciente,
        'listado_productos': listado_productos,
    }
    return render(request, 'tenant_app/dashboard.html', context)


@login_required(login_url='login')
def productos_view(request):
    try:
        tienda = request.user.tienda
    except AttributeError:
        return redirect('index')
        
    productos = ProductoTienda.objects.filter(tienda=tienda)
    return render(request, 'tenant_app/productos.html', {'tienda': tienda, 'productos': productos})

@login_required(login_url='login')
def eliminar_producto(request, producto_id):
    try:
        tienda = request.user.tienda
    except AttributeError:
        return redirect('index')
        
    producto = get_object_or_404(ProductoTienda, id=producto_id, tienda=tienda)
    if request.method == 'POST':
        producto.delete()
        messages.success(request, 'Producto eliminado correctamente.')
    return redirect('dashboard_productos')

@login_required(login_url='login')
def editar_producto(request, producto_id):
    try:
        tienda = request.user.tienda
    except AttributeError:
        return redirect('index')
        
    producto = get_object_or_404(ProductoTienda, id=producto_id, tienda=tienda)
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        precio_base = request.POST.get('precio_base', '')
        if nombre:
            producto.nombre = nombre
        if precio_base:
            try:
                producto.precio_base = float(precio_base)
            except ValueError:
                pass
        
        # Manejo de Imagen
        nueva_imagen = request.FILES.get('imagen')
        if nueva_imagen:
            producto.imagen = nueva_imagen
            
        producto.save()
        messages.success(request, 'Producto actualizado correctamente.')
        return redirect('dashboard_productos')
        
    return render(request, 'tenant_app/editar_producto.html', {'producto': producto})

@login_required(login_url='login')
def ventas_view(request):
    try:
        tienda = request.user.tienda
    except AttributeError:
        return redirect('index')
        
    ordenes = Orden.objects.filter(tienda=tienda).order_by('-creado_en')[:50]
    return render(request, 'tenant_app/ventas.html', {'tienda': tienda, 'ordenes': ordenes})


@login_required(login_url='login')
def ajustes_view(request):
    try:
        tienda = request.user.tienda
    except AttributeError:
        return redirect('index')
    
    from tenant_app.models import Comuna
    
    if request.method == 'POST':
        nombre = request.POST.get('nombre_tienda', '').strip()
        comuna_id = request.POST.get('comuna_id')
        direccion = request.POST.get('direccion', '').strip()
        
        if nombre:
            tienda.nombre_tienda = nombre
        if comuna_id:
            tienda.comuna_id = comuna_id
        tienda.direccion = direccion
        tienda.save()
        messages.success(request, 'Ajustes del taller actualizados correctamente.')
        return redirect('dashboard_ajustes')
        
    comunas = Comuna.objects.all().order_by('nombre')
    return render(request, 'tenant_app/ajustes.html', {
        'tienda': tienda,
        'comunas': comunas
    })

class CustomPasswordChangeView(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = 'tenant_app/password_change.html'
    success_url = reverse_lazy('dashboard_ajustes')
    success_message = "Tu contraseña ha sido actualizada exitosamente."
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context['tienda'] = self.request.user.tienda
        except AttributeError:
            pass
        return context


@login_required(login_url='login')
@require_POST
def api_reordenar_productos(request):
    """
    Recibe un array JSON de IDs de productos y actualiza su orden visual en bloque.
    """
    try:
        data = json.loads(request.body)
        orden_ids = data.get('orden', [])
        
        # Validar y actualizar en bloque 
        # (Para pocos productos un bucle es suficiente, para gran escala usar bulk_update)
        for idx, p_id in enumerate(orden_ids, start=1):
            ProductoTienda.objects.filter(id=p_id, tienda=request.user.tienda).update(orden_visual=idx)
            
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required(login_url='login')
def vincular_mp(request):
    """
    Recibe por POST las credenciales de Mercado Pago y las guarda en el modelo Tienda.
    """
    if request.method == 'POST':
        try:
            tienda = request.user.tienda
            tienda.mp_vendedor_id = request.POST.get('mp_vendedor_id', '').strip()
            tienda.mp_access_token = request.POST.get('mp_access_token', '').strip()
            tienda.save()
            messages.success(request, '¡Cuenta de Mercado Pago vinculada exitosamente!')
        except Exception as e:
            messages.error(request, 'Error guardando datos de Mercado Pago.')
    
    return redirect('dashboard')

@login_required(login_url='login')
def actualizar_margen(request, producto_id):
    """
    Actualiza el margen de ganancia de un producto y recalcula indirectamente su precio_final.
    """
    if request.method == 'POST':
        try:
            tienda = request.user.tienda
            producto = ProductoTienda.objects.get(id=producto_id, tienda=tienda)
            nuevo_margen = float(request.POST.get('margen_ganancia', 0))
            producto.margen_ganancia = nuevo_margen
            producto.save(update_fields=['margen_ganancia', 'actualizado_en'])
            messages.success(request, f'Margen de {producto.nombre} actualizado a {nuevo_margen}%.')
        except Exception:
            messages.error(request, 'Error al actualizar el margen.')
            
    return redirect('dashboard')


@login_required(login_url='login')
def agregar_producto_catalogo_view(request):
    """
    Muestra los productos globales que la tienda AÚN NO tiene agregados a su catálogo.
    """
    tienda = request.user.tienda
    
    # Obtener los IDs de los productos globales que la tienda ya tiene
    productos_actuales_ids = ProductoTienda.objects.filter(
        tienda=tienda, 
        producto_global__isnull=False
    ).values_list('producto_global_id', flat=True)
    
    # Buscar todos los productos globales ACTIVOS que NO estén en la lista anterior
    productos_disponibles = ProductoGlobal.objects.filter(
        activo=True
    ).exclude(id__in=productos_actuales_ids)
    
    context = {
        'tienda': tienda,
        'productos_globales': productos_disponibles
    }
    
    return render(request, 'tenant_app/agregar_catalogo.html', context)


@login_required(login_url='login')
def agregar_producto_catalogo_post(request, global_id):
    """
    Recibe la orden de agregar un producto global específico al catálogo de la tienda.
    """
    if request.method == 'POST':
        try:
            tienda = request.user.tienda
            global_prod = ProductoGlobal.objects.get(id=global_id, activo=True)
            
            # Verificar que no lo tenga ya
            if ProductoTienda.objects.filter(tienda=tienda, producto_global=global_prod).exists():
                messages.warning(request, f'El producto {global_prod.nombre} ya está en tu catálogo.')
                return redirect('agregar_producto_catalogo')
                
            # Clonarlo a la tienda
            ProductoTienda.objects.create(
                tienda=tienda,
                nombre=global_prod.nombre,
                precio_base=global_prod.precio_costo,
                margen_ganancia=10.00,  # 10% por defecto
                producto_global=global_prod,
                metadatos={
                    'nombre': global_prod.nombre,
                    'categoria': global_prod.categoria, 
                    'scraper': global_prod.origen_url
                }
            )
            
            messages.success(request, f'¡{global_prod.nombre} agregado a tu catálogo exitosamente!')
            return redirect('dashboard')
            
        except ProductoGlobal.DoesNotExist:
            messages.error(request, 'El producto maestro no existe o ya no está disponible.')
        except Exception as e:
            messages.error(request, f'Error al agregar el producto: {str(e)}')
            
    return redirect('agregar_producto_catalogo')


@login_required(login_url='login')
def crear_producto_personalizado(request):
    """
    Crea un producto 100% personalizado para la tienda del subcontratista,
    sin vincularlo a ningún producto global del catálogo base.
    """
    if request.method == 'POST':
        try:
            tienda = request.user.tienda
        except AttributeError:
            return redirect('index')

        nombre = request.POST.get('nombre', '').strip()
        precio_base_raw = request.POST.get('precio_base', '0').strip()
        margen_raw = request.POST.get('margen_ganancia', '10').strip()
        termino = request.POST.get('termino_busqueda', '').strip()

        if not nombre:
            messages.error(request, 'El nombre del producto es obligatorio.')
            return redirect('agregar_producto_catalogo')

        # Parsear precio — soporte para "25.000" (formato chileno) y "25000"
        try:
            precio_limpio = precio_base_raw.replace('.', '').replace(',', '').strip()
            precio_base = Decimal(precio_limpio) if precio_limpio else Decimal('0')
        except InvalidOperation:
            precio_base = Decimal('0')

        try:
            margen_val = Decimal(margen_raw.replace(',', '.')) if margen_raw else Decimal('10')
        except InvalidOperation:
            margen_val = Decimal('10')

        try:
            ProductoTienda.objects.create(
                tienda=tienda,
                nombre=nombre,
                precio_base=precio_base,
                margen_ganancia=margen_val,
                termino_busqueda=termino or None,
            )
            messages.success(request, f'✅ Producto "{nombre}" creado exitosamente en tu catálogo.')
            return redirect('dashboard_productos')

        except Exception as e:
            messages.error(request, f'Error al guardar el producto: {str(e)}')
            return redirect('agregar_producto_catalogo')

    return redirect('agregar_producto_catalogo')
