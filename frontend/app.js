const CONFIG = {
    USER_SERVICE:    'http://localhost:5001',
    ORDER_SERVICE:   'http://localhost:8082',
    PAYMENT_SERVICE: 'http://localhost:8083',
    HEALTH_POLL_MS:  10000,
    ORDERS_POLL_MS:  8000
};

let currentUser    = JSON.parse(localStorage.getItem('cd_user') || 'null');
let ordersInterval = null;

// ── Bootstrap ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    if (currentUser) {
        showAppSection();
    }
    startHealthPolling();
});

// ── Tabs ───────────────────────────────────────────────────────────────────

function switchTab(tab) {
    document.getElementById('tab-login').classList.toggle('hidden', tab !== 'login');
    document.getElementById('tab-register').classList.toggle('hidden', tab !== 'register');
    document.querySelectorAll('.tab-btn').forEach((btn, i) => {
        btn.classList.toggle('active',
            (i === 0 && tab === 'login') || (i === 1 && tab === 'register'));
    });
    hideMessage('auth-message');
}

// ── Auth ───────────────────────────────────────────────────────────────────

async function handleRegister() {
    const username = document.getElementById('reg-username').value.trim();
    const email    = document.getElementById('reg-email').value.trim();
    const password = document.getElementById('reg-password').value;

    if (!username || !email || !password) {
        showMessage('auth-message', 'All fields are required.', 'error');
        return;
    }

    try {
        // FIX: Changed endpoint from /api/users/register to /register
        const res  = await post(`${CONFIG.USER_SERVICE}/register`,
                                { username, email, password });
        const data = await res.json();

        if (res.ok) {
            showMessage('auth-message', 'Registered successfully. Please login.', 'success');
            setTimeout(() => switchTab('login'), 1500);
        } else {
            showMessage('auth-message', data.error || 'Registration failed.', 'error');
        }
    } catch {
        showMessage('auth-message', 'User service is unreachable.', 'error');
    }
}

async function handleLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;

    if (!username || !password) {
        showMessage('auth-message', 'Username and password are required.', 'error');
        return;
    }

    try {
        // FIX: Changed endpoint from /api/users/login to /login
        const res  = await post(`${CONFIG.USER_SERVICE}/login`,
                                { username, password });
        const data = await res.json();

        if (res.ok) {
            // FIX: Map the Python backend response (user_id, username) to the frontend expected object (id, username)
            currentUser = { id: data.user_id, username: data.username };
            localStorage.setItem('cd_user', JSON.stringify(currentUser));
            showAppSection();
        } else {
            showMessage('auth-message', data.error || 'Login failed.', 'error');
        }
    } catch {
        showMessage('auth-message', 'User service is unreachable.', 'error');
    }
}

function handleLogout() {
    currentUser = null;
    localStorage.removeItem('cd_user');
    clearInterval(ordersInterval);
    document.getElementById('auth-section').classList.remove('hidden');
    document.getElementById('app-section').classList.add('hidden');
}

function showAppSection() {
    document.getElementById('auth-section').classList.add('hidden');
    document.getElementById('app-section').classList.remove('hidden');
    document.getElementById('user-display-name').textContent = currentUser.username;
    loadOrders();
    ordersInterval = setInterval(loadOrders, CONFIG.ORDERS_POLL_MS);
}

// ── Orders ─────────────────────────────────────────────────────────────────

async function handlePlaceOrder() {
    const itemName = document.getElementById('item-name').value.trim();
    const quantity = parseInt(document.getElementById('item-quantity').value, 10);
    const amount   = parseFloat(document.getElementById('item-amount').value);
    const btn      = document.getElementById('place-order-btn');

    if (!itemName || !quantity || !amount) {
        showMessage('order-message', 'All fields are required.', 'error');
        return;
    }

    if (quantity < 1 || amount <= 0) {
        showMessage('order-message', 'Quantity and amount must be positive.', 'error');
        return;
    }

    btn.disabled    = true;
    btn.textContent = 'Processing...';
    hideMessage('order-message');

    try {
        // FIX: Send camelCase (itemName) and include userId in the body. Removed the X-User-ID header.
        const res  = await post(
            `${CONFIG.ORDER_SERVICE}/api/orders`,
            { userId: currentUser.id, itemName: itemName, quantity, amount }
        );
        const data = await res.json();

        if (res.ok) {
            // FIX: Python returns data.status and data.paymentId directly, not wrapped in data.order
            const status = data.status;
            const msg = status === 'COMPLETED'
                ? `Order placed. Payment ID: ${data.paymentId}`
                : `Order created but payment failed. Status: ${status}`;
            showMessage('order-message', msg, status === 'COMPLETED' ? 'success' : 'error');
            document.getElementById('item-name').value   = '';
            document.getElementById('item-amount').value = '';
            loadOrders();
        } else {
            showMessage('order-message',
                data.error || 'Order failed. Payment service may be down.', 'error');
        }
    } catch {
        showMessage('order-message', 'Order service is unreachable.', 'error');
    } finally {
        btn.disabled    = false;
        btn.textContent = 'Place Order';
    }
}

async function loadOrders() {
    if (!currentUser) return;

    try {
        // FIX: Pass userId as a query parameter instead of a header
        const res = await fetch(`${CONFIG.ORDER_SERVICE}/api/orders?userId=${currentUser.id}`);
        const data = await res.json();

        // FIX: Python returns a raw array, not an object with an "orders" property
        if (res.ok) renderOrders(data);
    } catch {
        // silent fail on background poll
    }
}

function renderOrders(orders) {
    const container = document.getElementById('orders-container');

    if (!orders || orders.length === 0) {
        container.innerHTML =
            '<p class="empty-state">No orders yet. Place your first order above.</p>';
        return;
    }

    const rows = [...orders].reverse().map(o => `
        <tr>
            <td>#${o.id}</td>
            <!-- FIX: Backend returns itemName, not item_name -->
            <td>${safe(o.itemName)}</td>
            <td>${o.quantity}</td>
            <td>₹${Number(o.amount).toFixed(2)}</td>
            <!-- FIX: Added toLowerCase() so CSS classes like .completed or .pending match properly -->
            <td><span class="badge ${o.status.toLowerCase()}">${o.status}</span></td>
            <!-- FIX: Backend doesn't return created_at, using a placeholder -->
            <td>Just now</td>
        </tr>
    `).join('');

    container.innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>ID</th><th>Item</th><th>Qty</th>
                    <th>Amount</th><th>Status</th><th>Time</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;
}

// ── Health Polling ─────────────────────────────────────────────────────────

function startHealthPolling() {
    pollAll();
    setInterval(pollAll, CONFIG.HEALTH_POLL_MS);
}

async function pollAll() {
    await Promise.allSettled([
        checkHealth(CONFIG.USER_SERVICE,    'user'),
        checkHealth(CONFIG.ORDER_SERVICE,   'order'),
        checkHealth(CONFIG.PAYMENT_SERVICE, 'payment')
    ]);
}

async function checkHealth(baseUrl, service) {
    const dot  = document.getElementById(`dot-${service}`);
    const stat = document.getElementById(`stat-${service}`);

    try {
        const start = Date.now();
        const res   = await fetch(`${baseUrl}/health`,
                                  { signal: AbortSignal.timeout(4000) });
        const ms    = Date.now() - start;
        const data  = await res.json();
        
        // FIX: Python returns "UP" (uppercase), so we convert to lowercase before checking
        const statusStr = String(data.status).toLowerCase();
        const up = res.ok && (statusStr === 'ok' || statusStr === 'up');

        dot.className = `health-dot ${up ? 'up' : 'down'}`;

        if (stat) {
            stat.textContent = up ? `UP · ${ms}ms` : 'DEGRADED';
            stat.style.color = up ? 'var(--success)' : 'var(--danger)';
        }

        if (service === 'order' && data.circuit_breaker_state) {
            const cb = document.getElementById('stat-circuit');
            if (cb) {
                const state  = data.circuit_breaker_state;
                cb.textContent = state.toUpperCase();
                cb.style.color = state === 'closed'
                    ? 'var(--success)' : 'var(--danger)';
            }
        }

    } catch {
        if (dot)  dot.className       = 'health-dot down';
        if (stat) {
            stat.textContent = 'UNREACHABLE';
            stat.style.color = 'var(--danger)';
        }
    }
}

// ── Utilities ──────────────────────────────────────────────────────────────

function post(url, body, extraHeaders = {}) {
    return fetch(url, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...extraHeaders },
        body:    JSON.stringify(body)
    });
}

function showMessage(id, text, type) {
    const el = document.getElementById(id);
    el.textContent = text;
    el.className   = `message ${type}`;
    el.classList.remove('hidden');
}

function hideMessage(id) {
    document.getElementById(id).classList.add('hidden');
}

function safe(str) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
}