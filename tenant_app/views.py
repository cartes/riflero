from django.shortcuts import render
from tenant_app.models import ProductoTienda

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
    from tenant_app.models import Tienda
    
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
        from django.db.models import Q
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
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages
from django.core.mail import mail_admins
from tenant_app.models import Orden, ProductoTienda
from tenant_app.forms import RegistroTiendaForm

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
    except Exception:
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
    Panel central del subcontratista. Muestra sus métricas, órdenes y permite configurar Mercado Pago.
    """
    try:
        tienda = request.user.tienda
        if not tienda.aprobada:
            return redirect('pendiente_aprobacion')
    except Exception:
        # El usuario no tiene una tienda vinculada (puede ser superadmin genérico)
        messages.error(request, 'No tienes un Taller vinculado a esta cuenta.')
        return redirect('index')

    ordenes = Orden.objects.filter(tienda=tienda).order_by('-creado_en')[:20] # Últimas 20
    productos = ProductoTienda.objects.filter(tienda=tienda)
    ventas_totales = sum(o.monto_total for o in ordenes if o.estado_pago == 'completado')
    
    context = {
        'tienda': tienda,
        'ordenes': ordenes,
        'productos': productos,
        'ventas_totales': ventas_totales
    }
    return render(request, 'tenant_app/dashboard.html', context)

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
            messages.success(request, f'Margen de {producto.metadatos.get("nombre", "Producto")} actualizado a {nuevo_margen}%.')
        except Exception:
            messages.error(request, 'Error al actualizar el margen.')
            
    return redirect('dashboard')
