def cart_count(request):
    """Add cart item count to every template context."""
    count = 0
    is_vendor = False
    is_admin = False
    if request.user.is_authenticated:
        from .models import CartItem
        count = sum(item.qty for item in CartItem.objects.filter(user=request.user))
        is_admin = request.user.is_superuser or request.user.is_staff
        is_vendor = (
            not is_admin
            and request.user.groups.filter(name='vendor').exists()
        )
    else:
        cart = request.session.get('cart', {})
        count = sum(cart.values())
    if is_admin:
        user_role = 'Admin'
    elif not request.user.is_authenticated:
        user_role = 'Pengunjung'
    else:
        is_student = request.user.groups.filter(name='siswa').exists()
        user_role = 'Pedagang' if is_vendor else 'Siswa' if is_student else 'Pengguna'
    return {
        'cart_count': count,
        'is_vendor': is_vendor,
        'is_admin': is_admin,
        'user_role': user_role,
    }
