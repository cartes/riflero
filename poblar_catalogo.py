import os
import sys
import django

# Configurar entorno de Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "printflow_core.settings")
django.setup()

from tenant_app.models import ProductoGlobal

# Catálogo simulado extraido desde imprentas grandes
productos_scraper = [
    {"nombre": "Pendón Roller 80x200 cm", "costo": 14990, "categoria": "Gran Formato"},
    {"nombre": "Pendón Roller 100x200 cm", "costo": 18990, "categoria": "Gran Formato"},
    {" employment": "Tarjetas de Presentación (1000u)", "costo": 8500, "nombre": "Tarjetas de Presentación (1000u Couche 300g)", "categoria": "Ofset Corporativo"},
    {"nombre": "Flyers Tamaño Carta (Cien unidades)", "costo": 12500, "categoria": "Digital Corporativo"},
    {"nombre": "Lienzo PVC 1x1 Metro con Ojetillos", "costo": 7500, "categoria": "Gran Formato"},
    {"nombre": "Tazón Blanco Sublimado (10u)", "costo": 15000, "categoria": "Merchandising"},
    {"nombre": "Polera Algodón Estampada DTF (Unidad)", "costo": 6800, "categoria": "Vestuario Corporativo"},
    {"nombre": "Rollos Etiquetas Autoadhesivas 5x5cm (1000u)", "costo": 22000, "categoria": "Etiquetas y Packaging"},
]

def poblar_catalogo_maestro():
    print("Iniciando inyección de Catálogo Maestro de Scrapping...")
    
    # Limpiamos si queremos regenerar limpio (opcional, lo haremos en este caso base)
    ProductoGlobal.objects.all().delete()
    print("Catálogo antiguo borrado.")

    creados = 0
    for prod in productos_scraper:
        ProductoGlobal.objects.create(
            nombre=prod['nombre'],
            precio_costo=prod['costo'],
            categoria=prod['categoria'],
            origen_url="https://scraper.printflow.internal/proveedor-xyz"
        )
        creados += 1
        
    print(f"¡Catálogo Maestro actualizado con éxito! {creados} productos base disponibles.")

if __name__ == "__main__":
    poblar_catalogo_maestro()
