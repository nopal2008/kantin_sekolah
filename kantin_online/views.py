import json
from datetime import datetime, time, timedelta
from functools import wraps
import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Group
from django.shortcuts import render, redirect, get_object_or_404
from django.http import FileResponse, Http404, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.db.models import Sum
from django.core.paginator import Paginator
from django.db import transaction
from django.urls import reverse

from .forms import PaymentProofForm, StudentRegistrationForm, VoucherForm
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
from .order_services import invalidate_vendor_dashboard_cache, review_manual_payment


# ============================================================
# HELPER: Get cart (works for both session and DB)
# ============================================================

def student_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if (
            request.user.is_superuser
            or request.user.is_staff
            or request.user.groups.filter(name='vendor').exists()
        ):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


def _is_vendor(user):
    return user.is_superuser or user.groups.filter(name='vendor').exists()


def _get_cart_items(request):
    """Return list of cart dicts: [{id, nama, harga, qty, subtotal, stok, kategori_icon}]"""
    items = []
    if request.user.is_authenticated:
        for ci in CartItem.objects.filter(user=request.user).select_related('menu'):
            items.append({
                'id': ci.menu.id,
                'nama': ci.menu.nama,
                'harga': ci.menu.harga,
                'qty': ci.qty,
                'subtotal': ci.subtotal,
                'stok': ci.menu.stok,
                'kategori_icon': ci.menu.kategori_icon,
                'harga_fmt': ci.menu.harga_formatted(),
                'subtotal_fmt': f"Rp {ci.subtotal:,.0f}".replace(',', '.'),
            })
    else:
        cart = request.session.get('cart', {})
        for menu_id_str, qty in cart.items():
            try:
                m = Menu.objects.get(id=int(menu_id_str))
                sub = m.harga * qty
                items.append({
                    'id': m.id,
                    'nama': m.nama,
                    'harga': m.harga,
                    'qty': qty,
                    'subtotal': sub,
                    'stok': m.stok,
                    'kategori_icon': m.kategori_icon,
                    'harga_fmt': m.harga_formatted(),
                    'subtotal_fmt': f"Rp {sub:,.0f}".replace(',', '.'),
                })
            except Menu.DoesNotExist:
                continue
    return items


def _get_cart_total(request):
    items = _get_cart_items(request)
    return sum(i['subtotal'] for i in items)


def _get_cart_count(request):
    if request.user.is_authenticated:
        agg = CartItem.objects.filter(user=request.user).aggregate(total=Sum('qty'))
        return agg['total'] or 0
    else:
        cart = request.session.get('cart', {})
        return sum(cart.values())


def _merge_session_cart_to_db(request):
    """After login, merge session cart into DB cart."""
    cart = request.session.get('cart', {})
    if cart and request.user.is_authenticated:
        for menu_id_str, qty in cart.items():
            try:
                menu = Menu.objects.get(id=int(menu_id_str))
                ci, created = CartItem.objects.get_or_create(
                    user=request.user, menu=menu,
                    defaults={'qty': qty}
                )
                if not created:
                    ci.qty += qty
                    ci.save()
            except Menu.DoesNotExist:
                continue
        request.session['cart'] = {}
        request.session.modified = True


# ============================================================
# PAGE VIEWS
# ============================================================

def beranda(request):
    bestsellers = Menu.objects.filter(is_bestseller=True, is_active=True).order_by('-created_at')[:6]
    favorit = Menu.objects.filter(is_active=True).order_by('-created_at')[:8]
    context = {
        'bestsellers': bestsellers,
        'favorit': favorit,
        'user_nama': request.user.get_full_name() if request.user.is_authenticated else 'Pengunjung',
    }
    return render(request, 'kantin/beranda.html', context)


def menu_page(request):
    kategori = request.GET.get('kategori', 'semua')
    search = request.GET.get('q', '').strip()[:100]
    menus = Menu.objects.filter(is_active=True).select_related('vendor')

    if kategori == 'makanan_berat':
        menus = menus.filter(kategori='makanan_berat')
    elif kategori == 'jajanan_ringan':
        menus = menus.filter(kategori='jajanan_ringan')
    elif kategori == 'minuman':
        menus = menus.filter(kategori='minuman')
    elif kategori == 'hemat':
        menus = menus.filter(harga__lte=10000)

    if search:
        menus = menus.filter(nama__icontains=search)

    page = Paginator(menus.order_by('kategori', 'nama'), 10).get_page(
        request.GET.get('page')
    )
    available_vouchers = Voucher.objects.filter(is_active=True).order_by(
        'minimum_pembelian',
        '-potongan',
    )[:10]
    context = {
        'menus': page,
        'page_obj': page,
        'active_kategori': kategori,
        'search_query': search,
        'available_vouchers': available_vouchers,
    }
    return render(request, 'kantin/menu.html', context)


def _best_voucher_for_subtotal(subtotal):
    return Voucher.objects.filter(
        is_active=True,
        minimum_pembelian__lte=subtotal,
    ).order_by('-potongan', 'minimum_pembelian', 'pk').first()


@student_required
def voucher_list(request):
    vouchers = Voucher.objects.filter(is_active=True).order_by(
        'minimum_pembelian',
        '-potongan',
    )
    return render(request, 'kantin/voucher_list.html', {
        'vouchers': vouchers,
    })


@login_required
def voucher_admin_page(request, voucher_id=None):
    if not request.user.is_staff and not request.user.is_superuser:
        raise PermissionDenied
    voucher = get_object_or_404(Voucher, pk=voucher_id) if voucher_id else None
    form = VoucherForm(request.POST or None, instance=voucher)
    if request.method == 'POST' and form.is_valid():
        voucher = form.save(commit=False)
        if not voucher.pk:
            voucher.created_by = request.user
        voucher.save()
        messages.success(request, 'Voucher berhasil disimpan.')
        return redirect('voucher_admin')
    return render(request, 'kantin/voucher_admin.html', {
        'form': form,
        'vouchers': Voucher.objects.select_related('created_by').order_by('-created_at', '-pk'),
        'editing_voucher': voucher,
    })


@login_required
@require_POST
def voucher_toggle(request, voucher_id):
    if not request.user.is_staff and not request.user.is_superuser:
        raise PermissionDenied
    voucher = get_object_or_404(Voucher, pk=voucher_id)
    voucher.is_active = not voucher.is_active
    voucher.save(update_fields=['is_active'])
    messages.success(
        request,
        f'Voucher {voucher.nama} {"diaktifkan" if voucher.is_active else "dinonaktifkan"}.',
    )
    return redirect('voucher_admin')


def keranjang_page(request):
    items = _get_cart_items(request)
    total = sum(i['subtotal'] for i in items)
    context = {
        'items': items,
        'total': total,
        'total_fmt': f"Rp {total:,.0f}".replace(',', '.'),
        'is_empty': len(items) == 0,
    }
    return render(request, 'kantin/keranjang.html', context)


@student_required
def checkout_page(request):
    items = _get_cart_items(request)
    if not items:
        return redirect('keranjang')
    total = sum(i['subtotal'] for i in items)
    voucher = _best_voucher_for_subtotal(total)
    discount = min(voucher.potongan, total) if voucher else 0
    payable_total = total - discount
    profil = getattr(request.user, 'profil', None)
    if profil is None:
        profil = ProfilSiswa.objects.create(user=request.user)
    context = {
        'items': items,
        'total': payable_total,
        'subtotal': total,
        'discount': discount,
        'applied_voucher': voucher,
        'total_fmt': f"Rp {payable_total:,.0f}".replace(',', '.'),
        'subtotal_fmt': f"Rp {total:,.0f}".replace(',', '.'),
        'discount_fmt': f"Rp {discount:,.0f}".replace(',', '.'),
        'profil': profil,
        'saldo': profil.saldo if profil else 0,
        'saldo_fmt': profil.saldo_formatted() if profil else 'Rp 0',
        'sisa_saldo': (profil.saldo - payable_total) if profil else 0,
        'sisa_saldo_fmt': f"Rp {(profil.saldo - payable_total):,.0f}".replace(',', '.') if profil else 'Rp 0',
        'ewallet_number': settings.EWALLET_DESTINATION_NUMBER,
        'ewallet_account_name': settings.EWALLET_ACCOUNT_NAME,
    }
    return render(request, 'kantin/checkout.html', context)


@student_required
def pesananku_page(request):
    pesanan_aktif_query = Pesanan.objects.filter(
        user=request.user,
        status__in=['awaiting_payment', 'waiting', 'cooking', 'ready']
    ).prefetch_related('items', 'payment', 'pesanan_pedagang__vendor')
    pesanan_riwayat_query = Pesanan.objects.filter(
        user=request.user,
        status__in=['done', 'cancelled']
    ).prefetch_related('items', 'payment', 'pesanan_pedagang__vendor')
    pesanan_aktif = Paginator(
        pesanan_aktif_query.order_by('-created_at', '-pk'), 10
    ).get_page(request.GET.get('active_page'))
    pesanan_riwayat = Paginator(
        pesanan_riwayat_query.order_by('-created_at', '-pk'), 10
    ).get_page(request.GET.get('history_page'))
    context = {
        'pesanan_aktif': pesanan_aktif,
        'pesanan_riwayat': pesanan_riwayat,
    }
    return render(request, 'kantin/pesananku.html', context)


@student_required
def profil_page(request):
    profil = getattr(request.user, 'profil', None)
    if not profil:
        profil = ProfilSiswa.objects.create(user=request.user, kelas='10A', saldo=0)
    total_pesanan = Pesanan.objects.filter(user=request.user).count()
    total_selesai = Pesanan.objects.filter(user=request.user, status='done').count()
    context = {
        'profil': profil,
        'total_pesanan': total_pesanan,
        'total_selesai': total_selesai,
    }
    return render(request, 'kantin/profil.html', context)


# ============================================================
# AUTH VIEWS
# ============================================================

def student_register(request):
    if request.user.is_authenticated:
        return redirect('vendor_dashboard' if _is_vendor(request.user) else 'beranda')

    form = StudentRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save(commit=False)
            user.save()
            group, _ = Group.objects.get_or_create(name='siswa')
            user.groups.add(group)
            ProfilSiswa.objects.create(
                user=user,
                kelas=form.cleaned_data['kelas'],
            )
        login(request, user)
        messages.success(request, 'Akun siswa berhasil dibuat. Selamat datang!')
        return redirect('beranda')

    return render(request, 'registration/student_register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('vendor_dashboard' if _is_vendor(request.user) else 'beranda')
    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            _merge_session_cart_to_db(request)
            next_url = request.POST.get('next') or request.GET.get('next', '/')
            if not url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                next_url = '/'
            if _is_vendor(user):
                if next_url == '/':
                    next_url = '/vendor/'
            return redirect(next_url)
        else:
            error = 'Username atau password salah.'
    return render(request, 'registration/login.html', {'error': error})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('beranda')


# ============================================================
# API VIEWS — KERANJANG
# ============================================================

def api_keranjang(request):
    items = _get_cart_items(request)
    total = sum(i['subtotal'] for i in items)
    return JsonResponse({
        'items': items,
        'total': total,
        'total_fmt': f"Rp {total:,.0f}".replace(',', '.'),
        'count': sum(i['qty'] for i in items),
    })


@require_POST
def api_keranjang_tambah(request):
    try:
        data = json.loads(request.body)
        menu_id = data.get('menu_id')
        qty = int(data.get('qty', 1))
    except (json.JSONDecodeError, TypeError):
        menu_id = request.POST.get('menu_id')
        qty = int(request.POST.get('qty', 1))

    try:
        menu = Menu.objects.get(id=menu_id, is_active=True)
    except Menu.DoesNotExist:
        return JsonResponse({'error': 'Menu tidak ditemukan'}, status=404)

    if not menu.tersedia:
        return JsonResponse({'error': 'Menu sedang habis'}, status=400)

    if request.user.is_authenticated:
        ci, created = CartItem.objects.get_or_create(
            user=request.user, menu=menu,
            defaults={'qty': qty}
        )
        if not created:
            ci.qty += qty
            ci.save()
    else:
        cart = request.session.get('cart', {})
        key = str(menu_id)
        cart[key] = cart.get(key, 0) + qty
        request.session['cart'] = cart
        request.session.modified = True

    count = _get_cart_count(request)
    return JsonResponse({
        'success': True,
        'message': f'{menu.nama} ditambahkan ke keranjang',
        'count': count,
    })


@require_POST
def api_keranjang_update(request):
    try:
        data = json.loads(request.body)
        menu_id = data.get('menu_id')
        delta = int(data.get('delta', 0))
    except (json.JSONDecodeError, TypeError):
        menu_id = request.POST.get('menu_id')
        delta = int(request.POST.get('delta', 0))

    if request.user.is_authenticated:
        try:
            ci = CartItem.objects.get(user=request.user, menu_id=menu_id)
            ci.qty += delta
            if ci.qty <= 0:
                ci.delete()
            else:
                ci.save()
        except CartItem.DoesNotExist:
            pass
    else:
        cart = request.session.get('cart', {})
        key = str(menu_id)
        if key in cart:
            cart[key] += delta
            if cart[key] <= 0:
                del cart[key]
            request.session['cart'] = cart
            request.session.modified = True

    items = _get_cart_items(request)
    total = sum(i['subtotal'] for i in items)
    return JsonResponse({
        'success': True,
        'items': items,
        'total': total,
        'total_fmt': f"Rp {total:,.0f}".replace(',', '.'),
        'count': sum(i['qty'] for i in items),
    })


@require_POST
def api_keranjang_hapus(request):
    try:
        data = json.loads(request.body)
        menu_id = data.get('menu_id')
    except (json.JSONDecodeError, TypeError):
        menu_id = request.POST.get('menu_id')

    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user, menu_id=menu_id).delete()
    else:
        cart = request.session.get('cart', {})
        key = str(menu_id)
        if key in cart:
            del cart[key]
        request.session['cart'] = cart
        request.session.modified = True

    items = _get_cart_items(request)
    total = sum(i['subtotal'] for i in items)
    return JsonResponse({
        'success': True,
        'items': items,
        'total': total,
        'total_fmt': f"Rp {total:,.0f}".replace(',', '.'),
        'count': sum(i['qty'] for i in items),
    })


@require_POST
def api_keranjang_clear(request):
    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user).delete()
    else:
        request.session['cart'] = {}
        request.session.modified = True

    return JsonResponse({'success': True, 'items': [], 'total': 0, 'total_fmt': 'Rp 0', 'count': 0})


# ============================================================
# API VIEWS — MENU FILTER
# ============================================================

def api_menu_filter(request):
    kategori = request.GET.get('kategori', 'semua')
    search = request.GET.get('q', '').strip()[:100]
    menus = Menu.objects.filter(is_active=True)

    if kategori == 'makanan_berat':
        menus = menus.filter(kategori='makanan_berat')
    elif kategori == 'jajanan_ringan':
        menus = menus.filter(kategori='jajanan_ringan')
    elif kategori == 'minuman':
        menus = menus.filter(kategori='minuman')
    elif kategori == 'hemat':
        menus = menus.filter(harga__lte=10000)

    if search:
        menus = menus.filter(nama__icontains=search)

    page = Paginator(menus.order_by('kategori', 'nama'), 10).get_page(
        request.GET.get('page')
    )
    data = [{
        'id': m.id,
        'nama': m.nama,
        'harga': m.harga,
        'harga_fmt': m.harga_formatted(),
        'kategori': m.kategori,
        'kategori_display': m.get_kategori_display(),
        'kategori_icon': m.kategori_icon,
        'stok': m.stok,
        'tersedia': m.tersedia,
        'is_bestseller': m.is_bestseller,
        'gambar_url': m.gambar.url if m.gambar else '',
    } for m in page.object_list]
    return JsonResponse({
        'menus': data,
        'count': page.paginator.count,
        'page': page.number,
        'pages': page.paginator.num_pages,
        'has_next': page.has_next(),
        'has_previous': page.has_previous(),
    })


# ============================================================
# API VIEWS — CHECKOUT & PAYMENT
# ============================================================

@student_required
@require_POST
def api_checkout(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            return JsonResponse({'error': 'Data pesanan tidak valid'}, status=400)
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = request.POST

    metode_bayar = data.get('metode_bayar', 'tunai')
    catatan = data.get('catatan', '')
    metode_checkout = {'tunai', 'saldo', 'gopay', 'dana', 'ovo'}
    if not isinstance(metode_bayar, str) or metode_bayar not in metode_checkout:
        return JsonResponse({'error': 'Metode pembayaran tidak valid'}, status=400)
    if not isinstance(catatan, str) or len(catatan) > 1000:
        return JsonResponse({'error': 'Catatan maksimal 1000 karakter'}, status=400)

    with transaction.atomic():
        cart_items = list(
            CartItem.objects.filter(user=request.user)
            .select_related('menu')
            .select_for_update()
        )
        if not cart_items:
            return JsonResponse({'error': 'Keranjang kosong'}, status=400)

        menu_ids = [item.menu_id for item in cart_items]
        locked_menus = {
            menu.pk: menu
            for menu in Menu.objects.filter(pk__in=menu_ids).select_for_update()
        }
        items = []
        for cart_item in cart_items:
            menu = locked_menus.get(cart_item.menu_id)
            if not menu or not menu.is_active or cart_item.qty < 1:
                return JsonResponse({'error': 'Ada menu keranjang yang tidak valid'}, status=400)
            if menu.stok < cart_item.qty:
                return JsonResponse({
                    'error': f'Stok {menu.nama} tidak mencukupi',
                }, status=400)
            items.append({
                'id': menu.pk,
                'nama': menu.nama,
                'harga': menu.harga,
                'qty': cart_item.qty,
                'subtotal': menu.harga * cart_item.qty,
            })

        subtotal = sum(item['subtotal'] for item in items)
        voucher = (
            Voucher.objects.select_for_update()
            .filter(is_active=True, minimum_pembelian__lte=subtotal)
            .order_by('-potongan', 'minimum_pembelian', 'pk')
            .first()
        )
        discount = min(voucher.potongan, subtotal) if voucher else 0
        total = subtotal - discount
        profil = ProfilSiswa.objects.select_for_update().filter(user=request.user).first()
        if metode_bayar == 'saldo' and (not profil or profil.saldo < total):
            return JsonResponse({'error': 'Saldo tidak mencukupi'}, status=400)

        pesanan = Pesanan.objects.create(
            user=request.user,
            nomor_antrean=Pesanan.generate_nomor_antrean(),
            total=total,
            status=(
                'awaiting_payment'
                if metode_bayar in {'gopay', 'dana', 'ovo'}
                else 'waiting'
            ),
            metode_bayar=metode_bayar,
            catatan=catatan,
            diskon=discount,
            voucher=voucher,
        )
        PesananItem.objects.bulk_create([
            PesananItem(
                pesanan=pesanan,
                menu_id=item['id'],
                nama_menu=item['nama'],
                qty=item['qty'],
                harga_saat_pesan=item['harga'],
            )
            for item in items
        ])
        status_pedagang = (
            'awaiting_payment'
            if metode_bayar in {'gopay', 'dana', 'ovo'}
            else 'waiting'
        )
        vendor_ids = {locked_menus[item['id']].vendor_id for item in items}
        PesananPedagang.objects.bulk_create([
            PesananPedagang(
                pesanan=pesanan,
                vendor_id=vendor_id,
                status=status_pedagang,
            )
            for vendor_id in vendor_ids
        ])
        payment = Payment.objects.create(
            pesanan=pesanan,
            metode=metode_bayar,
            jumlah=total,
            referensi=Payment.generate_referensi(),
            status='paid' if metode_bayar == 'saldo' else 'pending',
            paid_at=timezone.now() if metode_bayar == 'saldo' else None,
        )

        if metode_bayar == 'saldo':
            profil.saldo -= total
            profil.save(update_fields=['saldo'])
        for item in items:
            menu = locked_menus[item['id']]
            menu.stok -= item['qty']
            menu.save(update_fields=['stok'])
        CartItem.objects.filter(user=request.user).delete()
        request.session['cart'] = {}
        request.session.modified = True
        transaction.on_commit(
            lambda: invalidate_vendor_dashboard_cache(
                [locked_menus[item['id']].vendor_id for item in items]
            )
        )

    return JsonResponse({
        'success': True,
        'pesanan_id': pesanan.id,
        'nomor_antrean': pesanan.nomor_antrean,
        'subtotal_fmt': f"Rp {subtotal:,.0f}".replace(',', '.'),
        'diskon_fmt': f"Rp {discount:,.0f}".replace(',', '.'),
        'total_fmt': pesanan.total_formatted(),
        'voucher': voucher.nama if voucher else None,
        'payment_status': payment.get_status_display(),
        'payment_ref': payment.referensi,
        'payment_url': (
            reverse('payment_submit', args=[pesanan.pk])
            if metode_bayar in {'gopay', 'dana', 'ovo'}
            else None
        ),
    })


@student_required
def api_payment_status(request, pesanan_id):
    try:
        pesanan = Pesanan.objects.get(id=pesanan_id, user=request.user)
        payment = pesanan.payment
        return JsonResponse({
            'pesanan_id': pesanan.id,
            'nomor_antrean': pesanan.nomor_antrean,
            'status_pesanan': pesanan.status,
            'status_pesanan_display': pesanan.get_status_display(),
            'payment_status': payment.status,
            'payment_status_display': payment.get_status_display(),
            'payment_ref': payment.referensi,
            'transfer_ref': payment.referensi_transfer,
            'metode': payment.get_metode_display(),
            'jumlah_fmt': payment.jumlah_formatted(),
            'tujuan_transfer': (
                settings.EWALLET_DESTINATION_NUMBER
                if payment.metode in {'gopay', 'dana', 'ovo'}
                else ''
            ),
            'nama_tujuan': (
                settings.EWALLET_ACCOUNT_NAME
                if payment.metode in {'gopay', 'dana', 'ovo'}
                else ''
            ),
        })
    except (Pesanan.DoesNotExist, Payment.DoesNotExist):
        return JsonResponse({'error': 'Pesanan tidak ditemukan'}, status=404)


@student_required
def payment_submit(request, pesanan_id):
    payment = get_object_or_404(
        Payment.objects.select_related('pesanan'),
        pesanan_id=pesanan_id,
        pesanan__user=request.user,
        metode__in=['gopay', 'dana', 'ovo'],
    )
    pesanan = payment.pesanan

    form = None
    if payment.status == 'pending':
        form = PaymentProofForm()
    return render(request, 'kantin/payment_submit.html', {
        'pesanan': pesanan,
        'payment': payment,
        'form': form,
        'ewallet_number': settings.EWALLET_DESTINATION_NUMBER,
        'ewallet_account_name': settings.EWALLET_ACCOUNT_NAME,
    })


@student_required
@require_POST
def payment_proof_submit(request, pesanan_id):
    payment = get_object_or_404(
        Payment.objects.select_related('pesanan'),
        pesanan_id=pesanan_id,
        pesanan__user=request.user,
        metode__in=['gopay', 'dana', 'ovo'],
    )
    if payment.status != 'pending':
        messages.error(request, 'Bukti pembayaran untuk pesanan ini sudah dikirim atau ditinjau.')
        return redirect('payment_submit', pesanan_id=pesanan_id)

    form = PaymentProofForm(request.POST, request.FILES, instance=payment)
    if form.is_valid():
        with transaction.atomic():
            locked_payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if locked_payment.status != 'pending':
                messages.error(request, 'Status pembayaran sudah berubah. Muat ulang halaman.')
                return redirect('payment_submit', pesanan_id=pesanan_id)
            payment = form.save(commit=False)
            payment.status = 'submitted'
            payment.save()
        messages.success(request, 'Bukti transfer terkirim dan menunggu verifikasi admin.')
        return redirect('payment_submit', pesanan_id=pesanan_id)

    return render(request, 'kantin/payment_submit.html', {
        'pesanan': payment.pesanan,
        'payment': payment,
        'form': form,
        'ewallet_number': settings.EWALLET_DESTINATION_NUMBER,
        'ewallet_account_name': settings.EWALLET_ACCOUNT_NAME,
    })


@login_required
def payment_proof_file(request, payment_id):
    payment = get_object_or_404(
        Payment.objects.select_related('pesanan'),
        pk=payment_id,
    )
    if (
        payment.pesanan.user_id != request.user.pk
        and not request.user.is_staff
        and not request.user.is_superuser
    ):
        raise Http404
    if not payment.bukti_transfer:
        raise Http404

    content_type = mimetypes.guess_type(payment.bukti_transfer.name)[0]
    response = FileResponse(
        payment.bukti_transfer.open('rb'),
        content_type=content_type or 'application/octet-stream',
    )
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
def help_guide(request):
    if not (
        request.user.is_staff
        or request.user.is_superuser
        or request.user.groups.filter(name='vendor').exists()
    ):
        raise PermissionDenied
    return render(request, 'kantin/help_guide.html')


@login_required
def payment_review_list(request):
    if not request.user.is_staff and not request.user.is_superuser:
        raise PermissionDenied
    payments = (
        Payment.objects.filter(status='submitted')
        .select_related('pesanan', 'pesanan__user')
        .order_by('created_at', 'pk')
    )
    page = Paginator(payments, 10).get_page(request.GET.get('page'))
    return render(request, 'kantin/payment_review.html', {'page_obj': page})


@login_required
@require_POST
def payment_review_action(request, payment_id, action):
    if not request.user.is_staff and not request.user.is_superuser:
        raise PermissionDenied
    if action not in {'approve', 'reject'}:
        messages.error(request, 'Tindakan verifikasi tidak valid.')
        return redirect('payment_review_list')

    payment = get_object_or_404(Payment, pk=payment_id)
    try:
        review_manual_payment(
            payment.pk,
            request.user,
            approved=(action == 'approve'),
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if action == 'approve':
            messages.success(
                request,
                'Pembayaran berhasil diverifikasi. Pesanan diteruskan ke pedagang.',
            )
        else:
            messages.success(
                request,
                'Pembayaran ditolak. Pesanan dibatalkan dan stok dikembalikan.',
            )
    return redirect('payment_review_list')


# ============================================================
# API VIEWS — PROFIL
# ============================================================

@student_required
@require_POST
def api_profil_update(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    nama = data.get('nama', '')
    kelas = data.get('kelas', '')

    if nama:
        parts = nama.split(' ', 1)
        request.user.first_name = parts[0]
        request.user.last_name = parts[1] if len(parts) > 1 else ''
        request.user.save()

    profil = getattr(request.user, 'profil', None)
    if not profil:
        profil = ProfilSiswa.objects.create(user=request.user)

    if kelas:
        profil.kelas = kelas
        profil.save()

    return JsonResponse({
        'success': True,
        'nama': request.user.get_full_name(),
        'kelas': profil.kelas,
        'saldo_fmt': profil.saldo_formatted(),
    })


# ============================================================
# API VIEWS — PESANAN DETAIL
# ============================================================

@student_required
def api_pesanan_detail(request, pesanan_id):
    try:
        pesanan = Pesanan.objects.prefetch_related('items', 'payment').get(
            id=pesanan_id, user=request.user
        )
    except Pesanan.DoesNotExist:
        return JsonResponse({'error': 'Pesanan tidak ditemukan'}, status=404)

    items = []
    for pi in pesanan.items.all():
        items.append({
            'nama': pi.nama_menu,
            'qty': pi.qty,
            'harga': pi.harga_saat_pesan,
            'subtotal': pi.subtotal,
            'subtotal_fmt': f"Rp {pi.subtotal:,.0f}".replace(',', '.'),
        })

    payment_data = None
    try:
        p = pesanan.payment
        payment_data = {
            'metode': p.get_metode_display(),
            'status': p.status,
            'status_display': p.get_status_display(),
            'referensi': p.referensi,
            'referensi_transfer': p.referensi_transfer,
            'jumlah_fmt': p.jumlah_formatted(),
            'bukti_url': (
                reverse('payment_proof_file', args=[p.pk])
                if p.bukti_transfer
                else ''
            ),
        }
    except Payment.DoesNotExist:
        pass

    return JsonResponse({
        'id': pesanan.id,
        'nomor_antrean': pesanan.nomor_antrean,
        'status': pesanan.status,
        'status_display': pesanan.get_status_display(),
        'total': pesanan.total,
        'total_fmt': pesanan.total_formatted(),
        'metode_bayar': pesanan.get_metode_bayar_display(),
        'catatan': pesanan.catatan,
        'created_at': pesanan.created_at.strftime('%d %b %Y, %H:%M'),
        'items': items,
        'payment': payment_data,
        'vendor_orders': [
            {
                'vendor': (
                    vendor_order.vendor.get_full_name()
                    or vendor_order.vendor.username
                    if vendor_order.vendor
                    else 'Pedagang'
                ),
                'status': vendor_order.status,
                'status_display': vendor_order.get_status_display(),
            }
            for vendor_order in pesanan.pesanan_pedagang.select_related('vendor')
        ],
    })
