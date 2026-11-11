from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Menu, Payment, Pesanan, PesananItem, PesananPedagang


def invalidate_vendor_dashboard_cache(vendor_ids):
    for vendor_id in set(vendor_ids):
        if vendor_id:
            cache.delete(f'vendor-dashboard:v1:{vendor_id}')


VENDOR_STATUS_TRANSITIONS = {
    'confirm': ('waiting', 'cooking'),
    'ready': ('cooking', 'ready'),
    'complete': ('ready', 'done'),
}


def _update_order_status(pesanan):
    statuses = list(
        PesananPedagang.objects.filter(pesanan=pesanan)
        .values_list('status', flat=True)
    )
    if not statuses:
        return
    if 'awaiting_payment' in statuses:
        pesanan.status = 'awaiting_payment'
    elif all(status == 'cancelled' for status in statuses):
        pesanan.status = 'cancelled'
    elif 'waiting' in statuses:
        pesanan.status = 'waiting'
    elif 'cooking' in statuses:
        pesanan.status = 'cooking'
    elif 'ready' in statuses:
        pesanan.status = 'ready'
    elif all(status in {'done', 'cancelled'} for status in statuses):
        pesanan.status = 'done'
    pesanan.save(update_fields=['status', 'updated_at'])


@transaction.atomic
def review_manual_payment(payment_id, reviewer, approved):
    payment = (
        Payment.objects.select_for_update()
        .select_related('pesanan')
        .get(pk=payment_id)
    )
    if payment.status != 'submitted':
        raise ValidationError('Pembayaran ini belum menunggu verifikasi.')
    if payment.metode not in {'gopay', 'dana', 'ovo'} or not payment.bukti_transfer:
        raise ValidationError('Pembayaran tidak memiliki bukti transfer yang valid.')

    pesanan = Pesanan.objects.select_for_update().get(pk=payment.pesanan_id)
    if pesanan.status != 'awaiting_payment':
        raise ValidationError('Status pesanan sudah berubah dan tidak dapat ditinjau.')

    vendor_ids = list(
        PesananPedagang.objects.filter(pesanan=pesanan)
        .exclude(vendor_id=None)
        .values_list('vendor_id', flat=True)
    )
    now = timezone.now()
    payment.status = 'paid' if approved else 'failed'
    payment.reviewed_by = reviewer
    payment.reviewed_at = now
    payment.paid_at = now if approved else None
    payment.save(update_fields=[
        'status',
        'reviewed_by',
        'reviewed_at',
        'paid_at',
    ])

    if approved:
        PesananPedagang.objects.filter(
            pesanan=pesanan,
            status='awaiting_payment',
        ).update(status='waiting', updated_at=now)
    else:
        vendor_order_rows = PesananPedagang.objects.filter(pesanan=pesanan)
        vendor_order_rows.update(status='cancelled', updated_at=now)
        for item in PesananItem.objects.filter(pesanan=pesanan).exclude(menu_id=None):
            Menu.objects.filter(pk=item.menu_id).update(stok=F('stok') + item.qty)

    _update_order_status(pesanan)
    transaction.on_commit(lambda: invalidate_vendor_dashboard_cache(vendor_ids))
    return payment


@transaction.atomic
def transition_vendor_order(vendor_order_id, action):
    try:
        current_status, next_status = VENDOR_STATUS_TRANSITIONS[action]
    except KeyError as exc:
        raise ValidationError('Tindakan status pesanan tidak valid.') from exc

    vendor_order = (
        PesananPedagang.objects.select_for_update()
        .select_related('pesanan')
        .get(pk=vendor_order_id)
    )
    pesanan = Pesanan.objects.select_for_update().get(pk=vendor_order.pesanan_id)
    if vendor_order.status != current_status:
        raise ValidationError('Status pesanan sudah berubah. Muat ulang halaman.')
    if pesanan.metode_bayar not in {'tunai', 'qris'}:
        try:
            payment = Payment.objects.get(pesanan=pesanan)
        except Payment.DoesNotExist as exc:
            raise ValidationError('Status pembayaran pesanan belum tersedia.') from exc
        if payment.status != 'paid':
            raise ValidationError('Pesanan hanya dapat diproses setelah pembayaran diverifikasi.')

    vendor_order.status = next_status
    vendor_order.save(update_fields=['status', 'updated_at'])
    _update_order_status(pesanan)
    transaction.on_commit(
        lambda: invalidate_vendor_dashboard_cache([vendor_order.vendor_id])
    )
    return vendor_order
