from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from tenant_app.models import Tienda, ProductoTienda, Orden
from decimal import Decimal
import random

class Command(BaseCommand):
    help = 'Genera un usuario subcontratista de prueba (admin/admin), su tienda y órdenes simuladas.'

    def handle(self, *args, **kwargs):
        # 1. Crear el User (si no existe)
        username = 'admin'
        password = 'admin'
        
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f'Usuario creado: {username} / {password}'))
        else:
            self.stdout.write(self.style.WARNING(f'Usuario {username} ya existe, actualizando password a "admin"...'))
            user.set_password(password)
            user.save()

        # 2. Crear la Tienda
        subdominio_test = 'taller-demo'
        tienda, tienda_created = Tienda.objects.get_or_create(
            usuario=user,
            defaults={
                'nombre_tienda': 'Gráfica Demo SPA',
                'subdominio': subdominio_test,
                'comuna_base': 'Santiago',
                'taller_fisico': True,
                'scraping_activado': True,
                'mp_vendedor_id': '1122334455'
            }
        )
        
        if not tienda_created:
            tienda.nombre_tienda = 'Gráfica Demo SPA'
            tienda.subdominio = subdominio_test
            tienda.save()
            self.stdout.write(self.style.WARNING('Tienda ya estaba asociada a este usuario.'))
        else:
            self.stdout.write(self.style.SUCCESS('Tienda de prueba vinculada exitosamente.'))

        # 3. Productos de Muestra
        prod1, _ = ProductoTienda.objects.get_or_create(
            tienda=tienda,
            precio_base=Decimal('10000.00'),
            defaults={
                'margen_ganancia': 15.0,
                'metadatos': {'nombre': 'Pendón Roller 80x200cm', 'descripcion': 'Tela PVC Alta Resolución'}
            }
        )
        prod2, _ = ProductoTienda.objects.get_or_create(
            tienda=tienda,
            precio_base=Decimal('5500.00'),
            defaults={
                'margen_ganancia': 25.0,
                'metadatos': {'nombre': '1000 Tarjetas de Presentación', 'descripcion': 'Papel Couche 300g, termolaminado mate'}
            }
        )

        # 4. Generar algunas Órdenes dummy
        nombres = ['Carlos Martínez', 'Ana López', 'Empresa Tech Ltda', 'Juan Pérez', 'Startup Chile SPA']
        estados = ['completado', 'completado', 'completado', 'pendiente', 'rechazado']
        
        if Orden.objects.filter(tienda=tienda).count() < 5:
            self.stdout.write('Generando 5 órdenes históricas...')
            for i in range(5):
                producto_random = random.choice([prod1, prod2])
                estado_random = random.choice(estados)
                
                Orden.objects.create(
                    tienda=tienda,
                    producto=producto_random,
                    monto_total=producto_random.precio_final, # Usa la property actual
                    estado_pago=estado_random,
                    nombre_cliente=random.choice(nombres),
                    email_cliente=f'cliente{i}@correo.cl',
                    mp_payment_id=f"MP-TEST-{random.randint(10000, 99999)}" if estado_random == 'completado' else ''
                )
            self.stdout.write(self.style.SUCCESS('5 Órdenes de prueba creadas.'))

        self.stdout.write(self.style.SUCCESS(f'\n======================================================='))
        self.stdout.write(self.style.SUCCESS(f'✅ DATOS DE PRUEBA INSTALADOS'))
        self.stdout.write(self.style.SUCCESS(f' URL Dashboard: http://localhost:8000/login'))
        self.stdout.write(self.style.SUCCESS(f' URL Catálogo:  http://{subdominio_test}.localhost:8000/'))
        self.stdout.write(self.style.SUCCESS(f' Usuario:       admin'))
        self.stdout.write(self.style.SUCCESS(f' Password:      admin'))
        self.stdout.write(self.style.SUCCESS(f'======================================================='))
