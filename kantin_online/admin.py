from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    Menu,
    ProfilSiswa,
    CartItem,
    Pesanan,
    PesananItem,
    PesananPedagang,
    Payment,
    Voucher,
)


class UserAdmin(DjangoUserAdmin):
    list_per_page = 10
    show_full_result_count = False


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.register(Voucher)


class PesananItemInline(admin.TabularInline):
    model = PesananItem
    extra = 0
    readonly_fields = ('subtotal',)

    def subtotal(self, obj):
        return f"Rp {obj.subtotal:,.0f}".replace(',', '.')


class PaymentInline(admin.StackedInline):
    model = Payment
    extra = 0
    can_delete = False
    readonly_fields = (
        'metode',
        'jumlah',
        'status',
        'referensi',
        'referensi_transfer',
        'proof_link',
        'paid_at',
        'reviewed_at',
        'reviewed_by',
    )

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description='Bukti transfer')
    def proof_link(self, obj):
        if not obj or not obj.bukti_transfer:
            return '-'
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Lihat bukti</a>',
            reverse('payment_proof_file', args=[obj.pk]),
        )


@admin.register(Menu)
class MenuAdmin(admin.ModelAdmin):
    list_display = ('nama', 'harga_formatted', 'kategori', 'stok', 'vendor', 'is_bestseller', 'is_active')
    list_filter = ('kategori', 'vendor', 'is_bestseller', 'is_active')
    search_fields = ('nama', 'vendor__username')
    list_select_related = ('vendor',)
    list_editable = ('stok', 'is_bestseller', 'is_active')
    list_per_page = 10
    show_full_result_count = False


@admin.register(ProfilSiswa)
class ProfilSiswaAdmin(admin.ModelAdmin):
    list_display = ('user', 'kelas', 'saldo_formatted')
    list_filter = ('kelas',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    list_select_related = ('user',)
    list_per_page = 10
    show_full_result_count = False


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'menu', 'qty', 'created_at')
    list_filter = ('user',)
    list_select_related = ('user', 'menu')
    list_per_page = 10
    show_full_result_count = False


@admin.register(Pesanan)
class PesananAdmin(admin.ModelAdmin):
    list_display = (
        'nomor_antrean',
        'user',
        'total_formatted',
        'diskon',
        'voucher',
        'status',
        'metode_bayar',
        'created_at',
    )
    list_filter = ('status', 'metode_bayar', 'created_at')
    search_fields = ('nomor_antrean', 'user__username')
    inlines = [PesananItemInline, PaymentInline]
    list_select_related = ('user', 'voucher')
    list_per_page = 10
    show_full_result_count = False
    readonly_fields = ('status',)


@admin.register(PesananPedagang)
class PesananPedagangAdmin(admin.ModelAdmin):
    list_display = ('pesanan', 'vendor', 'status', 'updated_at')
    list_filter = ('status', 'vendor')
    search_fields = ('pesanan__nomor_antrean', 'vendor__username')
    list_select_related = ('pesanan', 'vendor')
    list_per_page = 10
    show_full_result_count = False
    readonly_fields = ('pesanan', 'vendor', 'status', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'pesanan',
        'metode',
        'jumlah_formatted',
        'status',
        'referensi_transfer',
        'proof_link',
        'reviewed_at',
    )
    list_filter = ('status', 'metode')
    search_fields = (
        'referensi',
        'referensi_transfer',
        'pesanan__nomor_antrean',
    )
    list_select_related = ('pesanan', 'pesanan__user')
    list_per_page = 10
    show_full_result_count = False
    actions = ()
    readonly_fields = (
        'pesanan',
        'metode',
        'jumlah',
        'status',
        'referensi',
        'referensi_transfer',
        'paid_at',
        'reviewed_at',
        'reviewed_by',
        'proof_link',
    )
    fields = readonly_fields

    @admin.display(description='Bukti transfer')
    def proof_link(self, obj):
        if not obj.bukti_transfer:
            return '-'
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Lihat bukti</a>',
            reverse('payment_proof_file', args=[obj.pk]),
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
