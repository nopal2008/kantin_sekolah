// static/js/app.js

// --- Utility Functions ---

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

async function fetchAPI(url, options = {}) {
    const csrfToken = getCookie('csrftoken');
    const headers = {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken,
        ...options.headers
    };
    
    const config = {
        ...options,
        headers
    };

    try {
        const response = await fetch(url, config);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Terjadi kesalahan pada server');
        }
        return data;
    } catch (error) {
        showToast(error.message, 'error');
        throw error;
    }
}

// --- UI Components ---

function showToast(message, type = 'success') {
    // Simple toast notification
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    // Style directly for simplicity, but could be in CSS
    Object.assign(toast.style, {
        position: 'fixed',
        top: '20px',
        right: '20px',
        padding: '12px 24px',
        borderRadius: '8px',
        color: 'white',
        background: type === 'success' ? 'var(--success-color)' : 'var(--danger-color)',
        zIndex: 9999,
        boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
        transition: 'opacity 0.3s',
        opacity: '0'
    });
    
    document.body.appendChild(toast);
    
    // Fade in
    setTimeout(() => toast.style.opacity = '1', 10);
    
    // Fade out and remove
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function updateCartBadge(count) {
    document.querySelectorAll('.cart-badge').forEach(badge => {
        if (count > 0) {
            badge.textContent = count;
            badge.style.display = 'block';
        } else {
            badge.style.display = 'none';
        }
    });
}

// --- Cart Operations ---

async function addToCart(menuId, qty = 1) {
    try {
        const data = await fetchAPI('/api/keranjang/tambah/', {
            method: 'POST',
            body: JSON.stringify({ menu_id: menuId, qty })
        });
        updateCartBadge(data.count);
        showToast(data.message);
    } catch (e) {
        // Error handled in fetchAPI
    }
}

async function updateCartQty(menuId, delta) {
    try {
        const data = await fetchAPI('/api/keranjang/update/', {
            method: 'POST',
            body: JSON.stringify({ menu_id: menuId, delta })
        });
        updateCartBadge(data.count);
        
        // If we're on the cart page, we need to reload or update DOM
        if (window.location.pathname === '/keranjang/') {
            window.location.reload();
        }
    } catch (e) {}
}

// --- Menu Page ---

function initMenuFilter() {
    const tabs = document.querySelectorAll('.tab-btn');
    if (!tabs.length) return;

    tabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            const kategori = e.target.dataset.kategori;
            const searchParams = new URLSearchParams(window.location.search);
            searchParams.set('kategori', kategori);
            window.location.href = `${window.location.pathname}?${searchParams.toString()}`;
        });
    });
}

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    initMenuFilter();
    
    // Keep the mobile navigation as a narrow drawer rather than expanding it over the page.
    const menuToggle = document.getElementById('mobile-menu-toggle');
    const sidebar = document.querySelector('.sidebar');
    const appContainer = document.querySelector('.app-container');
    const sidebarBackdrop = document.querySelector('.sidebar-backdrop');
    const closeSidebarButton = document.querySelector('.sidebar-close');
    
    if (menuToggle && sidebar && appContainer && sidebarBackdrop) {
        const closeSidebar = () => {
            appContainer.classList.remove('sidebar-open');
            menuToggle.setAttribute('aria-expanded', 'false');
            sidebar.setAttribute('aria-hidden', 'true');
        };
        const openSidebar = () => {
            appContainer.classList.add('sidebar-open');
            menuToggle.setAttribute('aria-expanded', 'true');
            sidebar.setAttribute('aria-hidden', 'false');
        };

        menuToggle.addEventListener('click', () => {
            if (appContainer.classList.contains('sidebar-open')) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });
        sidebarBackdrop.addEventListener('click', closeSidebar);
        if (closeSidebarButton) {
            closeSidebarButton.addEventListener('click', closeSidebar);
        }
        sidebar.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', closeSidebar);
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') closeSidebar();
        });
        window.addEventListener('resize', () => {
            closeSidebar();
            sidebar.setAttribute(
                'aria-hidden',
                window.innerWidth >= 1024 ? 'false' : 'true'
            );
        });
        sidebar.setAttribute('aria-hidden', window.innerWidth >= 1024 ? 'false' : 'true');
    }
});
