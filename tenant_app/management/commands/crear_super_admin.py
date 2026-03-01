import logging
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Crea o asegura la existencia de un superusuario administrador global (cartescris)'

    def handle(self, *args, **kwargs):
        username = 'cartescris'
        password = 'admin'
        email = 'contacto@riflero.cl'  # Default email

        self.stdout.write(self.style.WARNING(f'Verificando existencia del superuser {username}...'))

        # Comprueba si existe
        if User.objects.filter(username=username).exists():
            usuario = User.objects.get(username=username)
            # Asegura permisos
            if not usuario.is_superuser or not usuario.is_staff:
                usuario.is_superuser = True
                usuario.is_staff = True
                usuario.set_password(password)
                usuario.save()
                self.stdout.write(self.style.SUCCESS(f'OK: Los permisos de {username} se actualizaron a superuser/staff y la clave se reseteó a "admin"'))
            else:
                self.stdout.write(self.style.SUCCESS(f'OK: El superusuario {username} ya existe y tiene los permisos correctos.'))
        else:
            # Lo crea nuevo
            try:
                usuario = User.objects.create_superuser(
                    username=username, 
                    email=email, 
                    password=password
                )
                self.stdout.write(self.style.SUCCESS(f'ÉXITO: Superusuario creado. Usuario: {username}, Password: {password}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'ERROR: No se pudo crear el superusuario. {e}'))
