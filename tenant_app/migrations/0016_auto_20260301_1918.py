from django.db import migrations

def migrate_competidores_a_proveedores(apps, schema_editor):
    CompetidorScraping = apps.get_model('tenant_app', 'CompetidorScraping')
    ProveedorCompetencia = apps.get_model('tenant_app', 'ProveedorCompetencia')
    
    for comp in CompetidorScraping.objects.all():
        # Buscamos o creamos el proveedor matriz basado en el nombre que se usaba antes
        proveedor, created = ProveedorCompetencia.objects.get_or_create(
            nombre=comp.nombre.strip()
        )
        
        # Si recién se crea, y el competidor antiguo tenía wa o email, los salvamos ahí.
        # Si ya existía, pero está vacío, se los pasamos también.
        actualizado = False
        if comp.whatsapp_detectado and not proveedor.whatsapp_detectado:
            proveedor.whatsapp_detectado = comp.whatsapp_detectado
            actualizado = True
        
        if comp.email_detectado and not proveedor.email_detectado:
            proveedor.email_detectado = comp.email_detectado
            actualizado = True
            
        if actualizado:
            proveedor.save()
            
        # Asignar la FK al competidor
        comp.proveedor = proveedor
        comp.save()

def reverse_migrate(apps, schema_editor):
    CompetidorScraping = apps.get_model('tenant_app', 'CompetidorScraping')
    
    for comp in CompetidorScraping.objects.all():
        if comp.proveedor:
            comp.nombre = comp.proveedor.nombre
            comp.whatsapp_detectado = comp.proveedor.whatsapp_detectado
            comp.email_detectado = comp.proveedor.email_detectado
            comp.proveedor = None
            comp.save()


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_app', '0015_proveedorcompetencia_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_competidores_a_proveedores, reverse_migrate),
    ]
