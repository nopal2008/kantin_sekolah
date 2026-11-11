from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create a vendor account without granting Django admin access.'

    def handle(self, *args, **options):
        user_model = get_user_model()
        username = input('Username vendor: ').strip()
        if not username:
            raise CommandError('Username tidak boleh kosong.')
        if user_model.objects.filter(username=username).exists():
            raise CommandError('Username tersebut sudah digunakan.')

        email = input('Email (opsional): ').strip()
        password = getpass('Password: ')
        password_confirmation = getpass('Ulangi password: ')
        if password != password_confirmation:
            raise CommandError('Konfirmasi password tidak cocok.')

        user = user_model(username=username, email=email)
        try:
            validate_password(password, user=user)
        except ValidationError as error:
            raise CommandError('; '.join(error.messages)) from error

        vendor_group, _ = Group.objects.get_or_create(name='vendor')
        user.set_password(password)
        user.save()
        user.groups.add(vendor_group)

        self.stdout.write(self.style.SUCCESS(
            f'Akun vendor "{username}" berhasil dibuat. Login di /login/.'
        ))
