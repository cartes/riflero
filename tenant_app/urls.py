from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views
from . import api_views

urlpatterns = [
    # Ruta raíz atrapada por el middleware
    path('', views.index, name='index'),
    path('buscar/', views.buscar_view, name='buscar'),
    
    # Rutas privadas (Registro / Interfaz / Dashboard)
    path('login/', views.login_view, name='login'),
    path('registro/', views.registro_view, name='registro'),
    path('logout/', views.logout_view, name='logout'),
    path('pendiente-aprobacion/', views.pendiente_aprobacion_view, name='pendiente_aprobacion'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('dashboard/productos/', views.productos_view, name='dashboard_productos'),
    path('dashboard/productos/editar/<int:producto_id>/', views.editar_producto, name='editar_producto'),
    path('dashboard/productos/eliminar/<int:producto_id>/', views.eliminar_producto, name='eliminar_producto'),
    path('dashboard/productos/reordenar/', views.api_reordenar_productos, name='api_reordenar_productos'),
    path('dashboard/ventas/', views.ventas_view, name='dashboard_ventas'),
    path('dashboard/ajustes/', views.ajustes_view, name='dashboard_ajustes'),
    path('dashboard/ajustes/password/', views.CustomPasswordChangeView.as_view(), name='password_change'),
    
    path('dashboard/vincular-mp/', views.vincular_mp, name='vincular_mp'),
    path('dashboard/margen/<int:producto_id>/', views.actualizar_margen, name='actualizar_margen'),
    path('dashboard/agregar-catalogo/', views.agregar_producto_catalogo_view, name='agregar_producto_catalogo'),
    path('dashboard/agregar-catalogo/<int:global_id>/', views.agregar_producto_catalogo_post, name='agregar_producto_catalogo_post'),
    path('dashboard/agregar-catalogo/personalizado/', views.crear_producto_personalizado, name='crear_producto_personalizado'),
    
    # API endpoints (Checkout & Fetchs)
    path('api/checkout/', api_views.api_checkout_transparent, name='api_checkout'),
    path('api/comunas/', api_views.api_get_comunas, name='api_comunas'),
]

