from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from kantin_online.models import Menu, ProfilSiswa, Pesanan, PesananItem, Payment
from django.utils import timezone
from datetime import timedelta
import random

class Command(BaseCommand):
    help = 'Seed database with initial data'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding data...')

        # Create Users
        budi, _ = User.objects.get_or_create(username='budi', defaults={
            'first_name': 'Budi',
            'last_name': 'Santoso',
            'email': 'budi@sekolah.com'
        })
        if not budi.has_usable_password():
            budi.set_password('budi1234')
            budi.save()
        
        siti, _ = User.objects.get_or_create(username='siti', defaults={
            'first_name': 'Siti',
            'last_name': 'Rahayu',
            'email': 'siti@sekolah.com'
        })
        if not siti.has_usable_password():
            siti.set_password('siti1234')
            siti.save()

        # Create ProfilSiswa
        ProfilSiswa.objects.get_or_create(user=budi, defaults={'kelas': '10A', 'saldo': 25000})
        ProfilSiswa.objects.get_or_create(user=siti, defaults={'kelas': '11B', 'saldo': 30000})

        # Create Menus
        menus_data = [
            {'nama': 'Nasi Goreng Spesial', 'harga': 15000, 'kategori': 'makanan_berat', 'stok': 20, 'is_bestseller': True, 'deskripsi': 'Nasi goreng dengan telur, sosis, dan bakso.'},
            {'nama': 'Mie Goreng Jumbo', 'harga': 12000, 'kategori': 'makanan_berat', 'stok': 15, 'is_bestseller': True, 'deskripsi': 'Mie goreng porsi besar, bikin kenyang.'},
            {'nama': 'Nasi Ayam Bakar', 'harga': 18000, 'kategori': 'makanan_berat', 'stok': 10, 'is_bestseller': False, 'deskripsi': 'Ayam bakar madu lengkap dengan nasi dan lalapan.'},
            {'nama': 'Bakso Kuah', 'harga': 10000, 'kategori': 'makanan_berat', 'stok': 25, 'is_bestseller': False, 'deskripsi': 'Bakso urat kuah segar dengan mie kuning.'},
            {'nama': 'Tahu Goreng', 'harga': 2000, 'kategori': 'jajanan_ringan', 'stok': 50, 'is_bestseller': False, 'deskripsi': 'Tahu isi sayuran digoreng renyah.'},
            {'nama': 'Risoles Mayo', 'harga': 3000, 'kategori': 'jajanan_ringan', 'stok': 30, 'is_bestseller': True, 'deskripsi': 'Risoles isi telur, sosis, dan mayo lumer.'},
            {'nama': 'Cireng Isi', 'harga': 5000, 'kategori': 'jajanan_ringan', 'stok': 40, 'is_bestseller': False, 'deskripsi': 'Cireng isi ayam pedas mercon.'},
            {'nama': 'Pisang Goreng', 'harga': 2000, 'kategori': 'jajanan_ringan', 'stok': 30, 'is_bestseller': False, 'deskripsi': 'Pisang tanduk goreng manis dan krispi.'},
            {'nama': 'Es Teh Manis', 'harga': 3000, 'kategori': 'minuman', 'stok': 100, 'is_bestseller': True, 'deskripsi': 'Es teh manis segar pelepas dahaga.'},
            {'nama': 'Jus Jeruk', 'harga': 5000, 'kategori': 'minuman', 'stok': 40, 'is_bestseller': False, 'deskripsi': 'Jus jeruk peras asli kaya vitamin C.'},
            {'nama': 'Es Campur', 'harga': 8000, 'kategori': 'minuman', 'stok': 20, 'is_bestseller': True, 'deskripsi': 'Es campur manis isi cincau, cendol, dan nangka.'},
            {'nama': 'Air Mineral', 'harga': 3000, 'kategori': 'minuman', 'stok': 50, 'is_bestseller': False, 'deskripsi': 'Air mineral 600ml.'},
        ]

        menus = []
        for md in menus_data:
            menu, _ = Menu.objects.get_or_create(nama=md['nama'], defaults=md)
            menus.append(menu)

        # Create Pesanan Riwayat for Budi
        # 1 Done pesanan
        if not Pesanan.objects.filter(user=budi, status='done').exists():
            pesanan1 = Pesanan.objects.create(
                user=budi,
                nomor_antrean=Pesanan.generate_nomor_antrean(),
                total=20000,
                status='done',
                metode_bayar='tunai',
                catatan='',
            )
            # update timestamp
            Pesanan.objects.filter(id=pesanan1.id).update(created_at=timezone.now() - timedelta(days=1))
            
            # items
            PesananItem.objects.create(pesanan=pesanan1, menu=menus[0], nama_menu=menus[0].nama, qty=1, harga_saat_pesan=15000)
            PesananItem.objects.create(pesanan=pesanan1, menu=menus[9], nama_menu=menus[9].nama, qty=1, harga_saat_pesan=5000)

            # payment
            Payment.objects.create(pesanan=pesanan1, metode='tunai', jumlah=20000, status='paid', referensi=Payment.generate_referensi(), paid_at=timezone.now() - timedelta(days=1))

        self.stdout.write(self.style.SUCCESS('Successfully seeded data'))
