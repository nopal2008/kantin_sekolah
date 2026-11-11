from django.conf import settings
from django.db import migrations


def create_student_role_and_vendor_orders(apps, schema_editor):
    database = schema_editor.connection.alias
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    Pesanan = apps.get_model('kantin_online', 'Pesanan')
    PesananPedagang = apps.get_model('kantin_online', 'PesananPedagang')

    student_group, _ = Group.objects.using(database).get_or_create(name='siswa')
    vendor_group = Group.objects.using(database).filter(name='vendor').first()
    vendor_user_ids = set()
    if vendor_group:
        vendor_user_ids = set(
            User.groups.through.objects.using(database)
            .filter(group_id=vendor_group.pk)
            .values_list('user_id', flat=True)
        )

    student_memberships = User.groups.through.objects.using(database)
    student_memberships.bulk_create(
        [
            User.groups.through(user_id=user_id, group_id=student_group.pk)
            for user_id in User.objects.using(database)
            .filter(is_staff=False, is_superuser=False)
            .exclude(pk__in=vendor_user_ids)
            .values_list('pk', flat=True)
        ],
        ignore_conflicts=True,
    )

    for pesanan in Pesanan.objects.using(database).iterator():
        vendor_ids = list(
            pesanan.items.using(database)
            .values_list('menu__vendor_id', flat=True)
            .distinct()
        ) or [None]
        PesananPedagang.objects.using(database).bulk_create([
            PesananPedagang(
                pesanan_id=pesanan.pk,
                vendor_id=vendor_id,
                status=pesanan.status,
            )
            for vendor_id in vendor_ids
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('kantin_online', '0004_payment_bukti_transfer_payment_referensi_transfer_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(
            create_student_role_and_vendor_orders,
            migrations.RunPython.noop,
        ),
    ]
