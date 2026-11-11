from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils import timezone
import random
import string


@deconstructible
class PrivatePaymentStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.PRIVATE_MEDIA_ROOT)


class Menu(models.Model):
    KATEGORI_CHOICES = [
        ('makanan_berat', 'Makanan Berat'),
        ('jajanan_ringan', 'Jajanan Ringan'),
        ('minuman', 'Minuman'),
    ]

    nama = models.CharField(max_length=100)
    harga = models.IntegerField()
    kategori = models.CharField(max_length=20, choices=KATEGORI_CHOICES)
    stok = models.IntegerField(default=10)
    gambar = models.ImageField(upload_to='menu/', blank=True, null=True)
    deskripsi = models.TextField(blank=True, default='')
    is_bestseller = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='menu_items',
        db_index=True,
    )

    class Meta:
        ordering = ['kategori', 'nama']
        verbose_name_plural = 'Menu'
        indexes = [
            models.Index(fields=['is_active', 'kategori', 'nama'], name='menu_active_category_idx'),
            models.Index(fields=['vendor', 'kategori', 'nama'], name='menu_vendor_category_idx'),
        ]

    def __str__(self):
        return f"{self.nama} - Rp {self.harga:,}"

    @property
    def tersedia(self):
        return self.stok > 0 and self.is_active

    @property
    def kategori_icon(self):
        icons = {
            'makanan_berat': 'food',
            'jajanan_ringan': 'snack',
            'minuman': 'drink',
        }
        return icons.get(self.kategori, 'food')

    def harga_formatted(self):
        return f"Rp {self.harga:,.0f}".replace(',', '.')


class Voucher(models.Model):
    nama = models.CharField(max_length=100)
    minimum_pembelian = models.PositiveIntegerField()
    potongan = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_vouchers',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['minimum_pembelian', 'nama']
        indexes = [
            models.Index(fields=['is_active', 'minimum_pembelian'], name='voucher_active_min_idx'),
        ]
        verbose_name = 'Voucher'
        verbose_name_plural = 'Voucher'

    def clean(self):
        super().clean()
        if self.potongan and self.minimum_pembelian and self.potongan > self.minimum_pembelian:
            raise ValidationError({
                'potongan': 'Potongan tidak boleh melebihi minimum pembelian.'
            })

    def __str__(self):
        return f'{self.nama} (potongan Rp {self.potongan:,})'


class ProfilSiswa(models.Model):
    KELAS_CHOICES = [(k, k) for k in [
        '10A', '10B', '10C', '11A', '11B', '11C', '12A', '12B', '12C'
    ]]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profil')
    kelas = models.CharField(max_length=5, choices=KELAS_CHOICES, default='10A')
    saldo = models.IntegerField(default=0)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    class Meta:
        verbose_name_plural = 'Profil Siswa'

    def __str__(self):
        return f"{self.user.get_full_name()} - Kelas {self.kelas}"

    def saldo_formatted(self):
        return f"Rp {self.saldo:,.0f}".replace(',', '.')


class CartItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cart_items')
    menu = models.ForeignKey(Menu, on_delete=models.CASCADE)
    qty = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'menu')
        verbose_name_plural = 'Cart Items'

    def __str__(self):
        return f"{self.user.username} - {self.menu.nama} x{self.qty}"

    @property
    def subtotal(self):
        return self.menu.harga * self.qty


class Pesanan(models.Model):
    STATUS_CHOICES = [
        ('awaiting_payment', 'Menunggu Pembayaran'),
        ('waiting', 'Menunggu Konfirmasi'),
        ('cooking', 'Sedang Diproses'),
        ('ready', 'Siap Diambil'),
        ('done', 'Selesai'),
        ('cancelled', 'Dibatalkan'),
    ]

    METODE_BAYAR_CHOICES = [
        ('tunai', 'Tunai'),
        ('qris', 'QRIS'),
        ('saldo', 'Saldo Sekolah'),
        ('gopay', 'GoPay'),
        ('dana', 'DANA'),
        ('ovo', 'OVO'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pesanan')
    nomor_antrean = models.CharField(max_length=10, unique=True)
    total = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    metode_bayar = models.CharField(max_length=10, choices=METODE_BAYAR_CHOICES, default='tunai')
    catatan = models.TextField(blank=True, default='')
    diskon = models.PositiveIntegerField(default=0)
    voucher = models.ForeignKey(
        Voucher,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pesanan',
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Pesanan'
        indexes = [
            models.Index(fields=['created_at', 'status'], name='pesanan_date_status_idx'),
        ]

    def __str__(self):
        return f"Pesanan {self.nomor_antrean} - {self.user.get_full_name()}"

    @staticmethod
    def generate_nomor_antrean():
        prefix = random.choice(string.ascii_uppercase)
        number = random.randint(10, 99)
        nomor = f"#{prefix}{number}"
        while Pesanan.objects.filter(nomor_antrean=nomor).exists():
            prefix = random.choice(string.ascii_uppercase)
            number = random.randint(10, 99)
            nomor = f"#{prefix}{number}"
        return nomor

    def total_formatted(self):
        return f"Rp {self.total:,.0f}".replace(',', '.')

    @property
    def is_active(self):
        return self.status in ['awaiting_payment', 'waiting', 'cooking', 'ready']


class PesananPedagang(models.Model):
    STATUS_CHOICES = Pesanan.STATUS_CHOICES

    pesanan = models.ForeignKey(
        Pesanan,
        on_delete=models.CASCADE,
        related_name='pesanan_pedagang',
    )
    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pesanan_pedagang',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['pesanan', 'vendor'],
                name='unique_pesanan_pedagang',
            ),
        ]
        ordering = ['pk']
        verbose_name = 'Pesanan Pedagang'
        verbose_name_plural = 'Pesanan Pedagang'

    def __str__(self):
        return f"{self.pesanan.nomor_antrean} - {self.vendor or 'Tanpa pedagang'}"


class PesananItem(models.Model):
    pesanan = models.ForeignKey(Pesanan, on_delete=models.CASCADE, related_name='items')
    menu = models.ForeignKey(Menu, on_delete=models.SET_NULL, null=True)
    nama_menu = models.CharField(max_length=100)
    qty = models.IntegerField(default=1)
    harga_saat_pesan = models.IntegerField(default=0)

    class Meta:
        verbose_name_plural = 'Pesanan Items'

    def __str__(self):
        return f"{self.nama_menu} x{self.qty}"

    @property
    def subtotal(self):
        return self.harga_saat_pesan * self.qty


class Payment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Menunggu Pembayaran'),
        ('submitted', 'Menunggu Verifikasi Admin'),
        ('paid', 'Terverifikasi'),
        ('failed', 'Gagal'),
        ('refunded', 'Dikembalikan'),
    ]

    pesanan = models.OneToOneField(Pesanan, on_delete=models.CASCADE, related_name='payment')
    metode = models.CharField(max_length=10, choices=Pesanan.METODE_BAYAR_CHOICES)
    jumlah = models.IntegerField(default=0)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    referensi = models.CharField(max_length=50, blank=True, default='')
    referensi_transfer = models.CharField(max_length=100, blank=True, default='')
    bukti_transfer = models.ImageField(
        storage=PrivatePaymentStorage(),
        upload_to='payment_proofs/%Y/%m/',
        blank=True,
        null=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_payments',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Payments'

    def __str__(self):
        return f"Payment {self.pesanan.nomor_antrean} - {self.get_status_display()}"

    def jumlah_formatted(self):
        return f"Rp {self.jumlah:,.0f}".replace(',', '.')

    @staticmethod
    def generate_referensi():
        return f"PAY-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
