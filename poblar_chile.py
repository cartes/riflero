import os
import sys
import django
import requests
import json

# Configurar entorno de Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "printflow_core.settings")
django.setup()

from tenant_app.models import Region, Provincia, Comuna

def poblar_dpa_chile():
    print("Iniciando descarga de División Político-Administrativa de Chile desde Repositorio de Respaldo...")
    
    # Usando el JSON abierto más popular de Geo Censo Chile en GitHub
    url = "https://gist.githubusercontent.com/juanbrujo/0fd2f4d126b3ce5a95a7dd1f28b3d8dd/raw/b8575eb82dce974fd2647f46819a7568278396bd/comunas-regiones.json"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
    except Exception as e:
        print(f"Error descargando el JSON: {e}")
        return

    print("Limpiando datos geográficos existentes...")
    Comuna.objects.all().delete()
    Provincia.objects.all().delete()
    Region.objects.all().delete()

    for idx, r_data in enumerate(data.get('regiones', [])):
        nombre_region = r_data.get('region')
        
        region = Region.objects.create(
            nombre=nombre_region,
            orden=idx
        )
        print(f"Creada Región: {region.nombre}")
        
        # Como este JSON no contiene provincia, creamos una provincia de transición
        # para respetar la integridad referencial y permitir expansión a futuro.
        provincia_unica = Provincia.objects.create(
            region=region,
            nombre=f"Provincia de {nombre_region}"
        )
        
        comunas_nombres = r_data.get('comunas', [])
        for c_name in comunas_nombres:
            Comuna.objects.create(
                provincia=provincia_unica,
                nombre=c_name
            )

    print("¡Población Geográfica completada exitosamente!")
    print(f"Métricas: {Region.objects.count()} Regiones, {Provincia.objects.count()} Provincias, {Comuna.objects.count()} Comunas.")

if __name__ == "__main__":
    poblar_dpa_chile()
