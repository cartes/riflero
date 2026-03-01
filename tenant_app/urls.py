from django.urls import path
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
    path('dashboard/vincular-mp/', views.vincular_mp, name='vincular_mp'),
    path('dashboard/margen/<int:producto_id>/', views.actualizar_margen, name='actualizar_margen'),
    
    # API endpoints (Checkout & Fetchs)
    path('api/checkout/', api_views.api_checkout_transparent, name='api_checkout'),
    path('api/comunas/', api_views.api_get_comunas, name='api_comunas'),
]

