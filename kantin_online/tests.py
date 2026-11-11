from io import BytesIO
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import (
    CartItem,
    Menu,
    Payment,
    Pesanan,
    PesananItem,
    PesananPedagang,
    ProfilSiswa,
    Voucher,
)
from .order_services import review_manual_payment


def payment_image(name='bukti.png'):
    output = BytesIO()
    Image.new('RGB', (2, 2), color='blue').save(output, format='PNG')
    return SimpleUploadedFile(
        name,
        output.getvalue(),
        content_type='image/png',
    )


class VendorPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.vendor_group = Group.objects.get(name='vendor')
        cls.vendor = User.objects.create_user(username='vendor-one', password='test-password')
        cls.vendor.groups.add(cls.vendor_group)
        cls.other_vendor = User.objects.create_user(username='vendor-two', password='test-password')
        cls.other_vendor.groups.add(cls.vendor_group)
        cls.customer = User.objects.create_user(username='customer', password='test-password')

    def setUp(self):
        cache.clear()

    def create_menu(self, vendor, name='Menu uji', price=5000, stock=10):
        return Menu.objects.create(
            nama=name,
            harga=price,
            kategori='makanan_berat',
            stok=stock,
            vendor=vendor,
        )

    def test_vendor_can_create_and_manage_only_owned_menu(self):
        self.client.force_login(self.vendor)
        response = self.client.post(reverse('vendor_menu_create'), {
            'nama': 'Nasi Uji',
            'harga': 12000,
            'kategori': 'makanan_berat',
            'stok': 8,
            'deskripsi': 'Menu untuk uji CRUD',
            'is_active': 'on',
        })
        self.assertRedirects(response, reverse('vendor_menu_list'))
        menu = Menu.objects.get(nama='Nasi Uji')
        self.assertEqual(menu.vendor, self.vendor)

        other_menu = self.create_menu(self.other_vendor)
        response = self.client.get(reverse('vendor_menu_update', args=[other_menu.pk]))
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse('vendor_menu_delete', args=[other_menu.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Menu.objects.filter(pk=other_menu.pk).exists())

        response = self.client.post(reverse('vendor_menu_update', args=[menu.pk]), {
            'nama': 'Nasi Uji Diperbarui',
            'harga': 13000,
            'kategori': 'makanan_berat',
            'stok': 7,
            'deskripsi': 'Diperbarui',
            'is_active': 'on',
        })
        self.assertRedirects(response, reverse('vendor_menu_list'))
        menu.refresh_from_db()
        self.assertEqual(menu.nama, 'Nasi Uji Diperbarui')
        self.assertEqual(menu.vendor, self.vendor)

        response = self.client.post(reverse('vendor_menu_delete', args=[menu.pk]))
        self.assertRedirects(response, reverse('vendor_menu_list'))
        self.assertFalse(Menu.objects.filter(pk=menu.pk).exists())

    def test_vendor_login_redirects_to_vendor_dashboard(self):
        response = self.client.post(reverse('login'), {
            'username': 'vendor-one',
            'password': 'test-password',
            'next': '/',
        })
        self.assertRedirects(response, reverse('vendor_dashboard'))

    def test_create_vendor_management_command_creates_non_staff_vendor(self):
        with (
            patch('builtins.input', side_effect=['new-vendor', '']),
            patch(
                'kantin_online.management.commands.create_vendor.getpass',
                side_effect=['valid-passphrase-93', 'valid-passphrase-93'],
            ),
        ):
            call_command('create_vendor', stdout=StringIO())

        vendor = User.objects.get(username='new-vendor')
        self.assertTrue(vendor.check_password('valid-passphrase-93'))
        self.assertFalse(vendor.is_staff)
        self.assertTrue(vendor.groups.filter(name='vendor').exists())

    def test_customer_order_history_is_paginated_by_ten(self):
        for index in range(12):
            Pesanan.objects.create(
                user=self.customer,
                nomor_antrean=f'#H{index:02}',
                status='done',
            )
        self.client.force_login(self.customer)

        response = self.client.get(reverse('pesananku'), {'history_page': '2'})

        self.assertEqual(len(response.context['pesanan_riwayat'].object_list), 2)
        self.assertEqual(response.context['pesanan_riwayat'].paginator.count, 12)
        content = response.content.decode()
        self.assertLess(
            content.index('id="tab-riwayat"'),
            content.index('aria-label="Navigasi riwayat pesanan"'),
        )

    def test_customer_order_pages_render_when_vendor_is_missing(self):
        active_order = Pesanan.objects.create(
            user=self.customer,
            nomor_antrean='#N10',
            status='waiting',
        )
        history_order = Pesanan.objects.create(
            user=self.customer,
            nomor_antrean='#N11',
            status='done',
        )
        PesananPedagang.objects.create(
            pesanan=active_order,
            vendor=None,
            status='waiting',
        )
        PesananPedagang.objects.create(
            pesanan=history_order,
            vendor=None,
            status='done',
        )
        self.client.force_login(self.customer)

        active_response = self.client.get(reverse('pesananku'))
        self.assertEqual(active_response.status_code, 200)
        self.assertContains(active_response, 'Pedagang: Menunggu Konfirmasi')

        history_response = self.client.get(
            reverse('pesananku'),
            {'history_page': '1'},
        )
        self.assertEqual(history_response.status_code, 200)
        self.assertContains(history_response, 'Pedagang: Selesai')

    def test_vendor_menu_list_is_paginated_by_ten(self):
        Menu.objects.bulk_create([
            Menu(
                nama=f'Menu {index}',
                harga=5000,
                kategori='makanan_berat',
                vendor=self.vendor,
            )
            for index in range(12)
        ])
        self.client.force_login(self.vendor)

        response = self.client.get(reverse('vendor_menu_list'))

        self.assertEqual(len(response.context['page_obj'].object_list), 10)
        self.assertEqual(response.context['page_obj'].paginator.count, 12)

    def test_dashboard_only_counts_vendor_data(self):
        owned_menu = self.create_menu(self.vendor, price=3500)
        other_menu = self.create_menu(self.other_vendor, price=9000)
        order = Pesanan.objects.create(
            user=self.customer,
            nomor_antrean='#A10',
            total=12500,
        )
        PesananItem.objects.create(
            pesanan=order,
            menu=owned_menu,
            nama_menu=owned_menu.nama,
            qty=1,
            harga_saat_pesan=3500,
        )
        PesananItem.objects.create(
            pesanan=order,
            menu=other_menu,
            nama_menu=other_menu.nama,
            qty=1,
            harga_saat_pesan=9000,
        )
        self.client.force_login(self.vendor)

        response = self.client.get(reverse('vendor_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['dashboard']['menu_count'], 1)
        self.assertEqual(response.context['dashboard']['order_count_today'], 1)
        self.assertEqual(response.context['dashboard']['revenue_today'], 3500)
        self.assertEqual(sum(response.context['dashboard']['revenue_series']), 3500)
        analytics = response.context['dashboard']['sales_analytics']
        self.assertEqual(analytics['weekly']['metrics']['orders']['total'], 1)
        self.assertEqual(analytics['weekly']['metrics']['revenue']['total'], 3500)
        self.assertEqual(analytics['weekly']['metrics']['units']['total'], 1)
        self.assertEqual(analytics['yearly']['revenue'], 3500)
        self.assertEqual(analytics['weekly']['best_seller']['name'], owned_menu.nama)
        self.assertContains(response, 'vendor-weekly-sales-chart')
        self.assertContains(response, 'vendor-monthly-sales-chart')

    def test_vendor_order_list_hides_other_vendor_items_and_totals(self):
        own_menu = self.create_menu(self.vendor, name='Menu milik saya', price=2000)
        other_menu = self.create_menu(self.other_vendor, name='Menu vendor lain', price=7000)
        order = Pesanan.objects.create(
            user=self.customer,
            nomor_antrean='#B20',
            total=9000,
        )
        PesananItem.objects.create(
            pesanan=order,
            menu=own_menu,
            nama_menu=own_menu.nama,
            qty=1,
            harga_saat_pesan=2000,
        )
        PesananItem.objects.create(
            pesanan=order,
            menu=other_menu,
            nama_menu=other_menu.nama,
            qty=1,
            harga_saat_pesan=7000,
        )
        PesananPedagang.objects.create(pesanan=order, vendor=self.vendor)
        PesananPedagang.objects.create(pesanan=order, vendor=self.other_vendor)
        self.client.force_login(self.vendor)

        response = self.client.get(reverse('vendor_order_list'))

        self.assertContains(response, 'Menu milik saya')
        self.assertNotContains(response, 'Menu vendor lain')
        self.assertContains(response, 'Rp 2.000')
        self.assertNotContains(response, 'Rp 9.000')

    def test_non_vendor_cannot_open_vendor_pages(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse('vendor_dashboard'))
        self.assertEqual(response.status_code, 403)


class BackendPaginationAndCheckoutTests(TestCase):
    def setUp(self):
        Voucher.objects.update(is_active=False)
        self.customer = User.objects.create_user(username='buyer', password='test-password')
        self.vendor = User.objects.create_user(username='seller', password='test-password')
        self.menu = Menu.objects.create(
            nama='Menu paginasi',
            harga=5000,
            kategori='makanan_berat',
            stok=10,
            vendor=self.vendor,
        )

    def test_public_menu_page_has_ten_items_per_page(self):
        Menu.objects.bulk_create([
            Menu(
                nama=f'Menu tambahan {index}',
                harga=5000,
                kategori='makanan_berat',
                stok=10,
            )
            for index in range(11)
        ])

        response = self.client.get(reverse('menu'))

        self.assertEqual(len(response.context['page_obj'].object_list), 10)
        self.assertEqual(response.context['page_obj'].paginator.count, 12)

    def test_student_menu_does_not_show_vendor_sales_analytics(self):
        response = self.client.get(reverse('menu'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Statistik penjualan')
        self.assertNotContains(response, 'Perubahan dibanding periode sebelumnya')
        self.assertNotContains(response, 'vendor-weekly-sales-chart')
        self.assertContains(response, 'Voucher hemat')

    def test_menu_listing_eager_loads_vendor_without_per_menu_queries(self):
        Menu.objects.bulk_create([
            Menu(
                nama=f'Menu tambahan {index}',
                harga=5000,
                kategori='makanan_berat',
                stok=10,
                vendor=self.vendor,
            )
            for index in range(11)
        ])

        with self.assertNumQueries(3):
            response = self.client.get(reverse('menu'))

        self.assertContains(response, 'Pedagang: seller')

    def test_menu_api_returns_paginated_results(self):
        Menu.objects.bulk_create([
            Menu(
                nama=f'Menu API {index}',
                harga=5000,
                kategori='makanan_berat',
                stok=10,
            )
            for index in range(11)
        ])

        response = self.client.get(reverse('api_menu_filter'), {'page': '2'})
        payload = response.json()

        self.assertEqual(len(payload['menus']), 2)
        self.assertEqual(payload['count'], 12)
        self.assertEqual(payload['pages'], 2)
        self.assertFalse(payload['has_next'])
    def test_checkout_rejects_insufficient_stock_without_creating_order(self):
        self.menu.stok = 1
        self.menu.save(update_fields=['stok'])
        CartItem.objects.create(user=self.customer, menu=self.menu, qty=2)
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('api_checkout'),
            data='{"metode_bayar":"tunai","catatan":""}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Pesanan.objects.count(), 0)
        self.assertEqual(CartItem.objects.get(user=self.customer).qty, 2)
        self.menu.refresh_from_db()
        self.assertEqual(self.menu.stok, 1)

    def test_payment_status_is_visible_only_to_order_owner(self):
        order = Pesanan.objects.create(
            user=self.customer,
            nomor_antrean='#P10',
        )
        other_user = User.objects.create_user(username='other-buyer', password='test-password')
        self.client.force_login(other_user)

        response = self.client.get(
            reverse('api_payment_status', args=[order.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_checkout_creates_order_and_deducts_stock_atomically(self):
        CartItem.objects.create(user=self.customer, menu=self.menu, qty=2)
        ProfilSiswa.objects.create(user=self.customer, saldo=20000)
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('api_checkout'),
            data='{"metode_bayar":"saldo","catatan":"tanpa sambal"}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Pesanan.objects.count(), 1)
        self.assertEqual(PesananItem.objects.get().harga_saat_pesan, 5000)
        self.assertEqual(ProfilSiswa.objects.get(user=self.customer).saldo, 10000)
        self.menu.refresh_from_db()
        self.assertEqual(self.menu.stok, 8)
        self.assertFalse(CartItem.objects.filter(user=self.customer).exists())

    def test_checkout_automatically_applies_best_qualifying_voucher(self):
        self.menu.harga = 25000
        self.menu.save(update_fields=['harga'])
        other_menu = Menu.objects.create(
            nama='Minuman paginasi',
            harga=25000,
            kategori='minuman',
            stok=10,
            vendor=self.vendor,
        )
        voucher = Voucher.objects.create(
            nama='Diskon siswa',
            minimum_pembelian=40000,
            potongan=5000,
            is_active=True,
        )
        CartItem.objects.create(user=self.customer, menu=self.menu, qty=1)
        CartItem.objects.create(user=self.customer, menu=other_menu, qty=1)
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('api_checkout'),
            data='{"metode_bayar":"tunai","catatan":""}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        order = Pesanan.objects.get()
        payment = Payment.objects.get(pesanan=order)
        self.assertEqual(order.total, 45000)
        self.assertEqual(order.diskon, 5000)
        self.assertEqual(order.voucher, voucher)
        self.assertEqual(payment.jumlah, 45000)
        self.assertEqual(response.json()['subtotal_fmt'], 'Rp 50.000')
        self.assertEqual(response.json()['diskon_fmt'], 'Rp 5.000')

    def test_checkout_does_not_apply_voucher_below_minimum(self):
        self.menu.harga = 25000
        self.menu.save(update_fields=['harga'])
        voucher = Voucher.objects.create(
            nama='Diskon siswa',
            minimum_pembelian=40000,
            potongan=5000,
            is_active=True,
        )
        CartItem.objects.create(user=self.customer, menu=self.menu, qty=1)
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse('api_checkout'),
            data='{"metode_bayar":"tunai","catatan":""}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        order = Pesanan.objects.get()
        self.assertEqual(order.total, 25000)
        self.assertEqual(order.diskon, 0)
        self.assertIsNone(order.voucher)
        self.assertNotEqual(response.json()['voucher'], voucher.nama)

    def test_admin_can_create_update_and_toggle_vouchers(self):
        self.client.force_login(self.customer)
        denied = self.client.get(reverse('voucher_admin'))
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(User.objects.create_superuser(
            username='voucher-admin',
            email='voucher@example.com',
            password='test-password',
        ))
        response = self.client.post(reverse('voucher_admin'), {
            'nama': 'Voucher Awal',
            'minimum_pembelian': 40000,
            'potongan': 5000,
            'is_active': 'on',
        })
        self.assertRedirects(response, reverse('voucher_admin'))
        voucher = Voucher.objects.get(nama='Voucher Awal')
        self.assertTrue(voucher.is_active)

        response = self.client.post(reverse('voucher_toggle', args=[voucher.pk]))
        self.assertRedirects(response, reverse('voucher_admin'))
        voucher.refresh_from_db()
        self.assertFalse(voucher.is_active)

        response = self.client.post(
            reverse('voucher_admin_edit', args=[voucher.pk]),
            {
                'nama': 'Voucher Diperbarui',
                'minimum_pembelian': 60000,
                'potongan': 7000,
                'is_active': 'on',
            },
        )
        self.assertRedirects(response, reverse('voucher_admin'))
        voucher.refresh_from_db()
        self.assertEqual(voucher.nama, 'Voucher Diperbarui')
        self.assertEqual(voucher.minimum_pembelian, 60000)

    def test_students_can_view_active_vouchers(self):
        voucher = Voucher.objects.create(
            nama='Voucher Siswa',
            minimum_pembelian=40000,
            potongan=5000,
        )
        Voucher.objects.create(
            nama='Voucher Nonaktif',
            minimum_pembelian=40000,
            potongan=5000,
            is_active=False,
        )
        self.client.force_login(self.customer)

        response = self.client.get(reverse('voucher_list'))

        self.assertContains(response, voucher.nama)
        self.assertNotContains(response, 'Voucher Nonaktif')


class StudentPaymentAndVendorOrderFlowTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='student',
            password='test-password',
        )
        vendor_group, _ = Group.objects.get_or_create(name='vendor')
        self.vendor = User.objects.create_user(
            username='food-vendor',
            password='test-password',
        )
        self.vendor.groups.add(vendor_group)
        self.other_vendor = User.objects.create_user(
            username='other-food-vendor',
            password='test-password',
        )
        self.other_vendor.groups.add(vendor_group)
        self.admin = User.objects.create_superuser(
            username='payment-admin',
            email='admin@example.com',
            password='test-password',
        )
        self.menu = Menu.objects.create(
            nama='Nasi tes',
            harga=5000,
            kategori='makanan_berat',
            stok=10,
            vendor=self.vendor,
        )

    def test_default_student_voucher_is_seeded(self):
        voucher = Voucher.objects.get(nama='Diskon siswa')
        self.assertEqual(voucher.minimum_pembelian, 40000)
        self.assertEqual(voucher.potongan, 5000)
        self.assertTrue(voucher.is_active)

    def tearDown(self):
        for payment in Payment.objects.exclude(bukti_transfer=''):
            payment.bukti_transfer.delete(save=False)

    def test_student_signup_creates_student_role_and_profile(self):
        response = self.client.post(reverse('student_register'), {
            'username': 'new-student',
            'first_name': 'Siswa',
            'last_name': 'Baru',
            'kelas': '11A',
            'password1': 'Safe-password-2026',
            'password2': 'Safe-password-2026',
        })

        self.assertRedirects(response, reverse('beranda'))
        student = User.objects.get(username='new-student')
        self.assertTrue(student.groups.filter(name='siswa').exists())
        self.assertEqual(student.profil.kelas, '11A')
        self.assertEqual(int(response.wsgi_request.user.pk), student.pk)

    def test_wallet_checkout_requires_admin_verification_before_vendor_processing(self):
        CartItem.objects.create(user=self.student, menu=self.menu, qty=2)
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('api_checkout'),
            data='{"metode_bayar":"gopay","catatan":""}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        order = Pesanan.objects.get()
        payment = Payment.objects.get(pesanan=order)
        vendor_order = PesananPedagang.objects.get(pesanan=order)
        self.assertEqual(order.status, 'awaiting_payment')
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(vendor_order.status, 'awaiting_payment')
        self.assertEqual(response.json()['payment_url'], reverse(
            'payment_submit',
            args=[order.pk],
        ))

        response = self.client.get(response.json()['payment_url'])
        self.assertContains(response, '087817607300')
        self.assertContains(response, 'Muhammad Fatih Nauval Azzidan')
        self.assertContains(
            self.client.get(reverse('pesananku')),
            'Menunggu Pembayaran',
        )

        self.client.force_login(self.vendor)
        vendor_response = self.client.get(reverse('vendor_order_list'))
        self.assertContains(vendor_response, 'Menunggu verifikasi admin')
        self.assertNotContains(vendor_response, 'Konfirmasi &amp; proses')
        response = self.client.post(
            reverse('vendor_order_update', args=[vendor_order.pk]),
            {'action': 'confirm'},
        )
        self.assertRedirects(response, reverse('vendor_order_list'))
        vendor_order.refresh_from_db()
        self.assertEqual(vendor_order.status, 'awaiting_payment')

    def test_admin_can_verify_transfer_and_then_vendor_can_progress_order(self):
        order = Pesanan.objects.create(
            user=self.student,
            nomor_antrean='#W10',
            total=5000,
            status='awaiting_payment',
            metode_bayar='dana',
        )
        PesananItem.objects.create(
            pesanan=order,
            menu=self.menu,
            nama_menu=self.menu.nama,
            qty=1,
            harga_saat_pesan=self.menu.harga,
        )
        vendor_order = PesananPedagang.objects.create(
            pesanan=order,
            vendor=self.vendor,
            status='awaiting_payment',
        )
        payment = Payment.objects.create(
            pesanan=order,
            metode='dana',
            jumlah=order.total,
            status='submitted',
            bukti_transfer=payment_image(),
        )

        review_manual_payment(payment.pk, self.admin, approved=True)
        payment.refresh_from_db()
        order.refresh_from_db()
        vendor_order.refresh_from_db()
        self.assertEqual(payment.status, 'paid')
        self.assertEqual(payment.reviewed_by, self.admin)
        self.assertEqual(order.status, 'waiting')
        self.assertEqual(vendor_order.status, 'waiting')

        self.client.force_login(self.vendor)
        response = self.client.post(
            reverse('vendor_order_update', args=[vendor_order.pk]),
            {'action': 'confirm'},
        )
        self.assertRedirects(response, reverse('vendor_order_list'))
        vendor_order.refresh_from_db()
        self.assertEqual(vendor_order.status, 'cooking')

    def test_admin_can_verify_payment_from_separate_review_page(self):
        order = Pesanan.objects.create(
            user=self.student,
            nomor_antrean='#A12',
            total=5000,
            status='awaiting_payment',
            metode_bayar='gopay',
        )
        PesananPedagang.objects.create(
            pesanan=order,
            vendor=self.vendor,
            status='awaiting_payment',
        )
        payment = Payment.objects.create(
            pesanan=order,
            metode='gopay',
            jumlah=order.total,
            status='submitted',
            bukti_transfer=payment_image(),
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('payment_review_list'))
        self.assertContains(response, '#A12')
        self.assertContains(response, 'Verifikasi pembayaran')
        self.assertContains(response, reverse(
            'payment_proof_file',
            args=[payment.pk],
        ))

        response = self.client.post(
            reverse('payment_review_action', args=[payment.pk, 'approve'])
        )
        self.assertRedirects(response, reverse('payment_review_list'))
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'paid')
        self.assertEqual(payment.reviewed_by, self.admin)

    def test_help_guide_is_available_to_admin_and_vendor_only(self):
        response = self.client.get(reverse('help_guide'))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('help_guide')}",
        )

        self.client.force_login(self.vendor)
        vendor_response = self.client.get(reverse('help_guide'))
        self.assertEqual(vendor_response.status_code, 200)
        self.assertContains(vendor_response, 'Verifikasi pembayaran (Admin)')
        self.assertContains(vendor_response, 'Proses pesanan (Pedagang)')
        self.assertContains(vendor_response, reverse('vendor_order_list'))

        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse('help_guide'))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, reverse('payment_review_list'))

        self.client.force_login(self.student)
        self.assertEqual(
            self.client.get(reverse('help_guide')).status_code,
            403,
        )

    def test_payment_review_page_is_restricted_to_staff(self):
        self.client.force_login(self.vendor)
        self.assertEqual(
            self.client.get(reverse('payment_review_list')).status_code,
            403,
        )
        self.client.force_login(self.student)
        self.assertEqual(
            self.client.post(
                reverse('payment_review_action', args=[1, 'approve'])
            ).status_code,
            403,
        )

    def test_student_can_submit_transfer_proof_once(self):
        order = Pesanan.objects.create(
            user=self.student,
            nomor_antrean='#S11',
            total=5000,
            status='awaiting_payment',
            metode_bayar='gopay',
        )
        payment = Payment.objects.create(
            pesanan=order,
            metode='gopay',
            jumlah=order.total,
        )
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('payment_proof_submit', args=[order.pk]),
            {
                'referensi_transfer': 'TRX-12345',
                'bukti_transfer': payment_image(),
            },
        )

        self.assertRedirects(response, reverse('payment_submit', args=[order.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'submitted')
        self.assertEqual(payment.referensi_transfer, 'TRX-12345')
        self.assertNotEqual(
            payment.bukti_transfer.storage.location,
            settings.MEDIA_ROOT,
        )

        response = self.client.post(
            reverse('payment_proof_submit', args=[order.pk]),
            {
                'referensi_transfer': 'TRX-67890',
                'bukti_transfer': payment_image(),
            },
        )
        self.assertRedirects(response, reverse('payment_submit', args=[order.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.referensi_transfer, 'TRX-12345')

    def test_payment_proof_upload_normalizes_long_client_filename(self):
        order = Pesanan.objects.create(
            user=self.student,
            nomor_antrean='#L15',
            total=5000,
            status='awaiting_payment',
            metode_bayar='gopay',
        )
        Payment.objects.create(
            pesanan=order,
            metode='gopay',
            jumlah=order.total,
        )
        long_filename = (
            'docs_c8BZxtp.google.com_document_d_1sLpRNlwQxWMZcJoPqNkAVum9XMS-'
            'QEXl0CtZXaSmk74_edit_tabt.t9wn8zup2se8_1.png'
        )
        self.client.force_login(self.student)

        response = self.client.post(
            reverse('payment_proof_submit', args=[order.pk]),
            {
                'referensi_transfer': 'TRX-LONG-NAME',
                'bukti_transfer': payment_image(long_filename),
            },
        )

        self.assertRedirects(response, reverse('payment_submit', args=[order.pk]))
        payment = Payment.objects.get(pesanan=order)
        self.assertEqual(payment.status, 'submitted')
        saved_filename = payment.bukti_transfer.name.rsplit('/', 1)[-1]
        self.assertTrue(saved_filename.startswith('bukti-transfer'))
        self.assertTrue(saved_filename.endswith('.png'))
        self.assertLessEqual(len(saved_filename), 40)

    def test_payment_proof_is_owner_or_admin_only(self):
        order = Pesanan.objects.create(
            user=self.student,
            nomor_antrean='#P22',
            metode_bayar='ovo',
            status='awaiting_payment',
        )
        payment = Payment.objects.create(
            pesanan=order,
            metode='ovo',
            status='submitted',
            bukti_transfer=payment_image(),
        )
        proof_url = reverse('payment_proof_file', args=[payment.pk])

        self.client.force_login(self.vendor)
        response = self.client.get(proof_url)
        self.assertEqual(response.status_code, 404)
        response.close()
        self.client.force_login(self.student)
        response = self.client.get(proof_url)
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.force_login(self.admin)
        response = self.client.get(proof_url)
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_rejected_payment_cancels_order_and_restores_stock(self):
        self.menu.stok = 8
        self.menu.save(update_fields=['stok'])
        order = Pesanan.objects.create(
            user=self.student,
            nomor_antrean='#F30',
            total=10000,
            status='awaiting_payment',
            metode_bayar='ovo',
        )
        PesananItem.objects.create(
            pesanan=order,
            menu=self.menu,
            nama_menu=self.menu.nama,
            qty=2,
            harga_saat_pesan=self.menu.harga,
        )
        PesananPedagang.objects.create(
            pesanan=order,
            vendor=self.vendor,
            status='awaiting_payment',
        )
        payment = Payment.objects.create(
            pesanan=order,
            metode='ovo',
            jumlah=order.total,
            status='submitted',
            bukti_transfer=payment_image(),
        )

        review_manual_payment(payment.pk, self.admin, approved=False)
        order.refresh_from_db()
        self.menu.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertEqual(self.menu.stok, 10)

    def test_mixed_vendor_orders_have_independent_statuses(self):
        other_menu = Menu.objects.create(
            nama='Minuman tes',
            harga=3000,
            kategori='minuman',
            stok=10,
            vendor=self.other_vendor,
        )
        order = Pesanan.objects.create(
            user=self.student,
            nomor_antrean='#M40',
            total=8000,
            metode_bayar='tunai',
        )
        PesananItem.objects.create(
            pesanan=order,
            menu=self.menu,
            nama_menu=self.menu.nama,
            qty=1,
            harga_saat_pesan=5000,
        )
        PesananItem.objects.create(
            pesanan=order,
            menu=other_menu,
            nama_menu=other_menu.nama,
            qty=1,
            harga_saat_pesan=3000,
        )
        own_order = PesananPedagang.objects.create(
            pesanan=order,
            vendor=self.vendor,
        )
        other_order = PesananPedagang.objects.create(
            pesanan=order,
            vendor=self.other_vendor,
        )

        self.client.force_login(self.vendor)
        response = self.client.post(
            reverse('vendor_order_update', args=[own_order.pk]),
            {'action': 'confirm'},
        )
        self.assertRedirects(response, reverse('vendor_order_list'))
        own_order.refresh_from_db()
        other_order.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(own_order.status, 'cooking')
        self.assertEqual(other_order.status, 'waiting')
        self.assertEqual(order.status, 'waiting')
        self.assertEqual(
            self.client.post(
                reverse('vendor_order_update', args=[other_order.pk]),
                {'action': 'confirm'},
            ).status_code,
            404,
        )
        self.client.post(
            reverse('vendor_order_update', args=[own_order.pk]),
            {'action': 'ready'},
        )
        self.client.post(
            reverse('vendor_order_update', args=[own_order.pk]),
            {'action': 'complete'},
        )
        own_order.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(own_order.status, 'done')
        self.assertEqual(order.status, 'waiting')

        self.client.force_login(self.other_vendor)
        for action in ('confirm', 'ready', 'complete'):
            self.client.post(
                reverse('vendor_order_update', args=[other_order.pk]),
                {'action': action},
            )
        other_order.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(other_order.status, 'done')
        self.assertEqual(order.status, 'done')


class RoleNavigationTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            username='nav-student',
            password='test-password',
        )
        student_group, _ = Group.objects.get_or_create(name='siswa')
        self.student.groups.add(student_group)
        vendor_group, _ = Group.objects.get_or_create(name='vendor')
        self.vendor = User.objects.create_user(
            username='nav-vendor',
            password='test-password',
        )
        self.vendor.groups.add(vendor_group)
        self.admin = User.objects.create_superuser(
            username='nav-admin',
            email='nav-admin@example.com',
            password='test-password',
        )

    def test_logout_control_and_role_specific_links_are_in_navbar(self):
        role_expectations = (
            (self.student, 'Siswa', 'Profil'),
            (self.vendor, 'Pedagang', 'Dashboard pedagang'),
            (self.admin, 'Admin', 'Admin'),
        )
        for user, role, role_link in role_expectations:
            with self.subTest(role=role):
                self.client.force_login(user)
                response = self.client.get(reverse('beranda'))
                self.assertContains(response, 'Keluar')
                self.assertContains(response, role)
                self.assertContains(response, role_link)
                self.assertContains(response, f'role-{role.lower()}')

    def test_logout_requires_post_and_ends_the_session(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)

        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('beranda'))
        self.assertNotIn('_auth_user_id', self.client.session)


# Create your tests here.
