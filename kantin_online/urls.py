from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import vendor_views

urlpatterns = [
    # Pages
    path('', views.beranda, name='beranda'),
    path('menu/', views.menu_page, name='menu'),
    path('keranjang/', views.keranjang_page, name='keranjang'),
    path('checkout/', views.checkout_page, name='checkout'),
    path('voucher/', views.voucher_list, name='voucher_list'),
    path('admin-voucher/', views.voucher_admin_page, name='voucher_admin'),
    path(
        'admin-voucher/<int:voucher_id>/',
        views.voucher_admin_page,
        name='voucher_admin_edit',
    ),
    path(
        'admin-voucher/<int:voucher_id>/toggle/',
        views.voucher_toggle,
        name='voucher_toggle',
    ),
    path('pesananku/', views.pesananku_page, name='pesananku'),
    path('profil/', views.profil_page, name='profil'),
    path('panduan/', views.help_guide, name='help_guide'),
    path('verifikasi-pembayaran/', views.payment_review_list, name='payment_review_list'),
    path(
        'verifikasi-pembayaran/<int:payment_id>/<str:action>/',
        views.payment_review_action,
        name='payment_review_action',
    ),
    path('daftar-siswa/', views.student_register, name='student_register'),
    path('pesanan/<int:pesanan_id>/pembayaran/', views.payment_submit, name='payment_submit'),
    path(
        'pesanan/<int:pesanan_id>/pembayaran/bukti/',
        views.payment_proof_submit,
        name='payment_proof_submit',
    ),
    path(
        'pembayaran/<int:payment_id>/bukti/',
        views.payment_proof_file,
        name='payment_proof_file',
    ),
    path('vendor/', vendor_views.vendor_dashboard, name='vendor_dashboard'),
    path('vendor/menu/', vendor_views.vendor_menu_list, name='vendor_menu_list'),
    path('vendor/menu/tambah/', vendor_views.vendor_menu_create, name='vendor_menu_create'),
    path('vendor/menu/<int:menu_id>/ubah/', vendor_views.vendor_menu_update, name='vendor_menu_update'),
    path('vendor/menu/<int:menu_id>/hapus/', vendor_views.vendor_menu_delete, name='vendor_menu_delete'),
    path('vendor/pesanan/', vendor_views.vendor_order_list, name='vendor_order_list'),
    path(
        'vendor/pesanan/<int:vendor_order_id>/status/',
        vendor_views.vendor_order_update,
        name='vendor_order_update',
    ),

    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # API - Keranjang
    path('api/keranjang/', views.api_keranjang, name='api_keranjang'),
    path('api/keranjang/tambah/', views.api_keranjang_tambah, name='api_keranjang_tambah'),
    path('api/keranjang/update/', views.api_keranjang_update, name='api_keranjang_update'),
    path('api/keranjang/hapus/', views.api_keranjang_hapus, name='api_keranjang_hapus'),
    path('api/keranjang/clear/', views.api_keranjang_clear, name='api_keranjang_clear'),

    # API - Menu
    path('api/menu/filter/', views.api_menu_filter, name='api_menu_filter'),

    # API - Checkout & Payment
    path('api/checkout/', views.api_checkout, name='api_checkout'),
    path('api/payment/status/<int:pesanan_id>/', views.api_payment_status, name='api_payment_status'),

    # API - Profil
    path('api/profil/update/', views.api_profil_update, name='api_profil_update'),

    # API - Pesanan detail
    path('api/pesanan/<int:pesanan_id>/', views.api_pesanan_detail, name='api_pesanan_detail'),
]
