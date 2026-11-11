import calendar
from collections import Counter
from datetime import datetime, time, timedelta
from statistics import mean, median

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, ExpressionWrapper, F, IntegerField, Prefetch, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import VendorMenuForm
from .models import Menu, Pesanan, PesananItem, PesananPedagang
from .order_services import (
    invalidate_vendor_dashboard_cache,
    transition_vendor_order,
)

VENDOR_GROUP = 'vendor'
PAGE_SIZE = 10
DASHBOARD_CACHE_TIMEOUT = 60
PAID_ORDER_STATUSES = ['waiting', 'cooking', 'ready', 'done']


def _daily_statistics(values):
    frequencies = Counter(values)
    highest_frequency = max(frequencies.values(), default=0)
    return {
        'mean': round(mean(values), 2) if values else 0,
        'median': median(values) if values else 0,
        'modes': sorted(
            value for value, frequency in frequencies.items()
            if frequency == highest_frequency and frequency > 1
        ),
    }


def _percentage_change(current, previous):
    if not previous:
        return {
            'value': None,
            'label': 'Baru (sebelumnya 0)' if current else '0% (keduanya 0)',
        }
    value = (current - previous) / previous * 100
    return {'value': round(value, 2), 'label': f'{value:+.2f}%'}


def _vendor_sales_analytics(user):
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    previous_week_start = week_start - timedelta(days=7)
    previous_month = month_start - timedelta(days=1)
    previous_month_start = previous_month.replace(day=1)
    previous_month_days = min(
        today.day,
        calendar.monthrange(previous_month.year, previous_month.month)[1],
    )
    weekly_days = (today - week_start).days + 1
    monthly_days = today.day
    year_start = today.replace(month=1, day=1)
    range_start = min(previous_week_start, previous_month_start)
    range_end = today + timedelta(days=1)
    start_at = timezone.make_aware(datetime.combine(range_start, time.min))
    end_at = timezone.make_aware(datetime.combine(range_end, time.min))

    items = PesananItem.objects.filter(
        pesanan__status__in=PAID_ORDER_STATUSES,
        pesanan__created_at__gte=start_at,
        pesanan__created_at__lt=end_at,
    )
    if not user.is_superuser:
        items = items.filter(menu__vendor=user)

    revenue_expression = ExpressionWrapper(
        F('qty') * F('harga_saat_pesan'),
        output_field=IntegerField(),
    )
    daily_rows = list(
        items.annotate(day=TruncDate(
            'pesanan__created_at',
            tzinfo=timezone.get_current_timezone(),
        ))
        .values('day')
        .annotate(
            orders=Count('pesanan_id', distinct=True),
            revenue=Sum(revenue_expression),
            units=Sum('qty'),
        )
        .order_by('day')
    )
    daily = {
        row['day']: {
            'orders': row['orders'] or 0,
            'revenue': row['revenue'] or 0,
            'units': row['units'] or 0,
        }
        for row in daily_rows
    }

    def period_values(start, length):
        return [
            daily.get(start + timedelta(days=offset), {
                'orders': 0,
                'revenue': 0,
                'units': 0,
            })
            for offset in range(length)
        ]

    def period_summary(start, length, comparison_start, comparison_length, label):
        current = period_values(start, length)
        previous = period_values(comparison_start, comparison_length)
        metrics = {}
        for key in ('orders', 'revenue', 'units'):
            current_total = sum(day[key] for day in current)
            previous_total = sum(day[key] for day in previous)
            metrics[key] = {
                **_daily_statistics([day[key] for day in current]),
                'total': current_total,
                'change': _percentage_change(current_total, previous_total),
            }
        return {
            'label': label,
            'labels': [(start + timedelta(days=i)).strftime('%d %b') for i in range(length)],
            'orders': [day['orders'] for day in current],
            'revenue': [day['revenue'] for day in current],
            'units': [day['units'] for day in current],
            'metrics': metrics,
        }

    weekly = period_summary(
        week_start,
        weekly_days,
        previous_week_start,
        weekly_days,
        'Minggu ini',
    )
    monthly = period_summary(
        month_start,
        monthly_days,
        previous_month_start,
        previous_month_days,
        'Bulan ini',
    )
    yearly_start_at = timezone.make_aware(datetime.combine(year_start, time.min))
    year_items = PesananItem.objects.filter(
        pesanan__status__in=PAID_ORDER_STATUSES,
        pesanan__created_at__gte=yearly_start_at,
        pesanan__created_at__lt=end_at,
    )
    if not user.is_superuser:
        year_items = year_items.filter(menu__vendor=user)
    yearly_totals = year_items.aggregate(
        orders=Count('pesanan_id', distinct=True),
        revenue=Sum(revenue_expression),
        units=Sum('qty'),
    )
    best_sellers = list(
        year_items.order_by()
        .values('nama_menu')
        .annotate(
            weekly_units=Sum('qty', filter=Q(
                pesanan__created_at__gte=timezone.make_aware(
                    datetime.combine(week_start, time.min)
                ),
                pesanan__created_at__lt=end_at,
            )),
            monthly_units=Sum('qty', filter=Q(
                pesanan__created_at__gte=timezone.make_aware(
                    datetime.combine(month_start, time.min)
                ),
                pesanan__created_at__lt=end_at,
            )),
            yearly_units=Sum('qty'),
        )
    )
    for period, summary, units_key in (
        ('weekly', weekly, 'weekly_units'),
        ('monthly', monthly, 'monthly_units'),
    ):
        bestseller = max(
            best_sellers,
            key=lambda row: row[units_key] or 0,
            default=None,
        )
        summary['best_seller'] = (
            {
                'name': bestseller['nama_menu'],
                'units': bestseller[units_key],
            }
            if bestseller and bestseller[units_key]
            else None
        )
    yearly_bestseller = max(
        best_sellers,
        key=lambda row: row['yearly_units'] or 0,
        default=None,
    )
    return {
        'weekly': weekly,
        'monthly': monthly,
        'yearly': {
            'orders': yearly_totals['orders'] or 0,
            'revenue': yearly_totals['revenue'] or 0,
            'units': yearly_totals['units'] or 0,
            'best_seller': (
                {
                    'name': yearly_bestseller['nama_menu'],
                    'units': yearly_bestseller['yearly_units'],
                }
                if yearly_bestseller and yearly_bestseller['yearly_units']
                else None
            ),
        },
    }


def _is_vendor_or_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=VENDOR_GROUP).exists()
    )


def _require_vendor_or_admin(request):
    if not _is_vendor_or_admin(request.user):
        raise PermissionDenied


def _menu_queryset(user):
    menus = Menu.objects.select_related('vendor')
    if not user.is_superuser:
        menus = menus.filter(vendor=user)
    return menus


def _vendor_order_queryset(user):
    items = PesananItem.objects.select_related('menu')
    if not user.is_superuser:
        items = items.filter(menu__vendor=user)
    orders = PesananPedagang.objects.select_related(
        'vendor',
        'pesanan',
        'pesanan__user',
        'pesanan__payment',
    ).prefetch_related(
        Prefetch('pesanan__items', queryset=items)
    )
    if not user.is_superuser:
        orders = orders.filter(vendor=user)
    return orders


def _dashboard_data(user):
    cache_key = f'vendor-dashboard:v1:{user.pk}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    tomorrow_start = today_start + timedelta(days=1)
    first_day = today - timedelta(days=6)
    first_day_start = today_start - timedelta(days=6)
    items = PesananItem.objects.filter(
        pesanan__created_at__gte=first_day_start,
        pesanan__created_at__lt=tomorrow_start,
    ).exclude(pesanan__status__in=['cancelled', 'awaiting_payment'])
    if not user.is_superuser:
        items = items.filter(menu__vendor=user)

    revenue_expression = ExpressionWrapper(
        F('qty') * F('harga_saat_pesan'),
        output_field=IntegerField(),
    )
    daily = list(
        items.annotate(day=TruncDate('pesanan__created_at'))
        .values('day')
        .annotate(
            revenue=Sum(revenue_expression),
            orders=Count('pesanan_id', distinct=True),
        )
        .order_by('day')
    )
    by_day = {
        row['day']: {
            'revenue': row['revenue'] or 0,
            'orders': row['orders'],
        }
        for row in daily
    }

    menu_queryset = _menu_queryset(user)
    if not user.is_superuser:
        menu_queryset = menu_queryset.filter(vendor=user)

    order_items_today = PesananItem.objects.filter(
        pesanan__created_at__gte=today_start,
        pesanan__created_at__lt=tomorrow_start,
    ).exclude(pesanan__status__in=['cancelled', 'awaiting_payment'])
    if not user.is_superuser:
        order_items_today = order_items_today.filter(menu__vendor=user)

    series = [
        {
            'label': (first_day + timedelta(days=offset)).strftime('%d %b'),
            'revenue': by_day.get(first_day + timedelta(days=offset), {}).get('revenue', 0),
            'orders': by_day.get(first_day + timedelta(days=offset), {}).get('orders', 0),
        }
        for offset in range(7)
    ]
    data = {
        'menu_count': menu_queryset.count(),
        'order_count_today': order_items_today.values('pesanan_id').distinct().count(),
        'revenue_today': order_items_today.aggregate(total=Sum(revenue_expression))['total'] or 0,
        'labels': [entry['label'] for entry in series],
        'revenue_series': [entry['revenue'] for entry in series],
        'order_series': [entry['orders'] for entry in series],
        'sales_analytics': _vendor_sales_analytics(user),
    }
    cache.set(cache_key, data, DASHBOARD_CACHE_TIMEOUT)
    return data


@login_required
def vendor_dashboard(request):
    _require_vendor_or_admin(request)
    return render(request, 'vendor/dashboard.html', {
        'dashboard': _dashboard_data(request.user),
    })


@login_required
def vendor_menu_list(request):
    _require_vendor_or_admin(request)
    page = Paginator(_menu_queryset(request.user), PAGE_SIZE).get_page(
        request.GET.get('page')
    )
    return render(request, 'vendor/menu_list.html', {'page_obj': page})


@login_required
def vendor_menu_create(request):
    _require_vendor_or_admin(request)
    form = VendorMenuForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        menu = form.save(commit=False)
        if not request.user.is_superuser:
            menu.vendor = request.user
        menu.save()
        invalidate_vendor_dashboard_cache([menu.vendor_id])
        return redirect('vendor_menu_list')
    return render(request, 'vendor/menu_form.html', {
        'form': form,
        'page_title': 'Tambah Menu',
    })


@login_required
def vendor_menu_update(request, menu_id):
    _require_vendor_or_admin(request)
    menu = get_object_or_404(_menu_queryset(request.user), pk=menu_id)
    form = VendorMenuForm(request.POST or None, request.FILES or None, instance=menu)
    if request.method == 'POST' and form.is_valid():
        menu = form.save()
        invalidate_vendor_dashboard_cache([menu.vendor_id])
        return redirect('vendor_menu_list')
    return render(request, 'vendor/menu_form.html', {
        'form': form,
        'page_title': 'Ubah Menu',
        'menu': menu,
    })


@login_required
@require_POST
def vendor_menu_delete(request, menu_id):
    _require_vendor_or_admin(request)
    menu = get_object_or_404(_menu_queryset(request.user), pk=menu_id)
    vendor_id = menu.vendor_id
    menu.delete()
    invalidate_vendor_dashboard_cache([vendor_id])
    return redirect('vendor_menu_list')


@login_required
def vendor_order_list(request):
    _require_vendor_or_admin(request)
    page = Paginator(
        _vendor_order_queryset(request.user).order_by(
            '-pesanan__created_at',
            '-pk',
        ),
        PAGE_SIZE,
    ).get_page(request.GET.get('page'))
    for vendor_order in page.object_list:
        vendor_order.vendor_items = [
            item
            for item in vendor_order.pesanan.items.all()
            if (
                item.menu_id is None
                and request.user.is_superuser
            ) or (
                item.menu_id
                and item.menu.vendor_id == vendor_order.vendor_id
            )
        ]
        vendor_order.vendor_total = sum(
            item.qty * item.harga_saat_pesan
            for item in vendor_order.vendor_items
        )
    return render(request, 'vendor/order_list.html', {'page_obj': page})


@login_required
@require_POST
def vendor_order_update(request, vendor_order_id):
    _require_vendor_or_admin(request)
    queryset = PesananPedagang.objects.all()
    if not request.user.is_superuser:
        queryset = queryset.filter(vendor=request.user)
    vendor_order = get_object_or_404(queryset, pk=vendor_order_id)
    try:
        transition_vendor_order(
            vendor_order.pk,
            request.POST.get('action', ''),
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, 'Status pesanan berhasil diperbarui.')
    return redirect('vendor_order_list')
