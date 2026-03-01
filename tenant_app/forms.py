from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import re
from .models import Tienda, Region, Comuna

class RegistroTiendaForm(forms.Form):
    """
    Agrupa la creación del Usuario (User) y su Tienda (Tenant) en un solo paso.
    """
    # Clase CSS compartida
    base_class = 'appearance-none block w-full px-4 py-3 border border-slate-200 rounded-xl shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200 sm:text-sm bg-slate-50 hover:bg-white'

    # Datos de Usuario
    email = forms.EmailField(
        label='Correo Electrónico',
        widget=forms.EmailInput(attrs={'placeholder': 'tu@email.com', 'class': base_class})
    )
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'placeholder': 'Mínimo 8 caracteres', 'class': base_class})
    )
    confirm_password = forms.CharField(
        label='Confirmar Contraseña',
        widget=forms.PasswordInput(attrs={'placeholder': 'Repite tu contraseña', 'class': base_class})
    )
    
    # Datos de Tienda / Taller
    nombre_tienda = forms.CharField(
        label='Nombre de tu Imprenta / Taller',
        max_length=150,
        widget=forms.TextInput(attrs={'placeholder': 'Ej: Gráfica del Sol', 'class': base_class})
    )
    subdominio = forms.CharField(
        label='Subdominio',
        max_length=63,
        help_text='Solo letras minúsculas, números y guiones. Ej: grafica-sol',
        widget=forms.TextInput(attrs={'placeholder': 'grafica-sol', 'class': base_class})
    )
    region = forms.ModelChoiceField(
        queryset=Region.objects.all(),
        label="Región",
        empty_label="Selecciona una región",
        widget=forms.Select(attrs={'class': base_class, 'id': 'id_region'})
    )
    
    comuna = forms.ModelChoiceField(
        queryset=Comuna.objects.none(),
        label="Comuna Base",
        empty_label="Selecciona una comuna",
        widget=forms.Select(attrs={'class': base_class, 'id': 'id_comuna'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Si vienen datos en el POST, cargamos las comunas de esa región
        if 'region' in self.data:
            try:
                region_id = int(self.data.get('region'))
                self.fields['comuna'].queryset = Comuna.objects.filter(provincia__region_id=region_id).order_by('nombre')
            except (ValueError, TypeError):
                pass
        
    def clean_email(self):
        email = self.cleaned_data.get('email')
        # Verificar que el email no exista como usuario
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise ValidationError("Ya existe un usuario registrado con este correo electrónico.")
        return email

    def clean_subdominio(self):
        subdominio = self.cleaned_data.get('subdominio').lower()
        if not re.match(r'^[a-z0-9-]+$', subdominio):
            raise ValidationError("El subdominio solo puede contener letras minúsculas, números y guiones.")
            
        reservados = ['www', 'app', 'admin', 'api']
        if subdominio in reservados:
            raise ValidationError("Este subdominio es inválido o está reservado.")
            
        if Tienda.objects.filter(subdominio=subdominio).exists():
            raise ValidationError("Este subdominio ya está en uso. Por favor, elige otro.")
        return subdominio

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Las contraseñas no coinciden.")
            
        if password and len(password) < 8:
            self.add_error('password', "La contraseña debe tener al menos 8 caracteres.")

        return cleaned_data

    def save(self):
        """
        Guarda el User y la Tienda.
        El user no tiene permisos staff y la tienda nace inactiva (aprobada=False).
        """
        email = self.cleaned_data['email']
        password = self.cleaned_data['password']
        
        # 1. Crear el User de Django
        # Usamos el email como username (o una variación si se requiere).
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password
        )
        
        # 2. Crear la Tienda vinculada
        tienda = Tienda.objects.create(
            usuario=user,
            nombre_tienda=self.cleaned_data['nombre_tienda'],
            subdominio=self.cleaned_data['subdominio'],
            comuna=self.cleaned_data['comuna'],
            aprobada=False  # Nace inhabilitada, requiere aprobación
        )
        
        return user, tienda
