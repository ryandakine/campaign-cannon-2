/* Campaign Cannon 2 — Dashboard JS */

const REFRESH_INTERVAL = 30; // seconds
let countdown = REFRESH_INTERVAL;

// ── API Helpers ────────────────────────────────────────────────────────────

async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) return null;
    return resp.json();
}

function shortId(id) { return id ? id.substring(0, 8) : '—'; }

function relativeTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    const now = new Date();
    const diff = d - now;
    const absDiff = Math.abs(diff);
    if (absDiff < 60000) return diff > 0 ? 'in <1m' : '<1m ago';
    if (absDiff < 3600000) {
        const m = Math.round(absDiff / 60000);
        return diff > 0 ? `in ${m}m` : `${m}m ago`;
    }
    if (absDiff < 86400000) {
        const h = Math.round(absDiff / 3600000);
        return diff > 0 ? `in ${h}h` : `${h}h ago`;
    }
    return d.toLocaleDateString();
}

function platformBadge(p) {
    return `<span class="badge badge-${p}">${p}</span>`;
}

function statusBadge(s) {
    const cls = s === 'pending' ? 'pending' : s === 'retry_scheduled' ? 'retry' : s === 'failed' ? 'failed' : 'success';
    return `<span class="badge badge-${cls}">${s}</span>`;
}

// ── Widget Updaters ────────────────────────────────────────────────────────

async function updateSummary() {
    const data = await fetchJSON('/api/v1/dashboard/summary');
    if (!data) return;
    document.getElementById('stat-total').textContent = data.total || 0;
    const s = data.by_status || {};
    document.getElementById('stat-draft').textContent = s.draft || 0;
    document.getElementById('stat-active').textContent = s.active || 0;
    document.getElementById('stat-paused').textContent = s.paused || 0;
    document.getElementById('stat-completed').textContent = s.completed || 0;
    document.getElementById('stat-cancelled').textContent = s.cancelled || 0;
}

async function updateRateLimits() {
    const data = await fetchJSON('/api/v1/dashboard/rate-limits');
    if (!data) return;
    const el = document.getElementById('rate-limits');
    if (!data.length) {
        el.innerHTML = '<div class="empty-state">No rate limit data</div>';
        return;
    }
    el.innerHTML = data.map(r => {
        const pct = r.headroom_pct;
        const cls = pct > 50 ? 'good' : pct > 20 ? 'warn' : 'danger';
        return `
            <div class="rate-gauge">
                <span class="rate-gauge-label">${r.platform}</span>
                <div class="rate-gauge-bar">
                    <div class="rate-gauge-fill ${cls}" style="width: ${Math.max(2, 100 - pct)}%"></div>
                </div>
                <span class="rate-gauge-pct">${pct}%</span>
            </div>`;
    }).join('');
}

async function updateNextDue() {
    const data = await fetchJSON('/api/v1/dashboard/next-due');
    const tbody = document.getElementById('next-due-body');
    if (!data || !data.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No upcoming posts</td></tr>';
        return;
    }
    tbody.innerHTML = data.map(p => `
        <tr>
            <td>${platformBadge(p.platform)}</td>
            <td title="${p.copy}">${p.copy}</td>
            <td>${relativeTime(p.scheduled_at)}</td>
            <td>${statusBadge(p.status)}</td>
        </tr>`).join('');
}

async function updateRetryQueue() {
    const data = await fetchJSON('/api/v1/dashboard/retry-queue');
    const tbody = document.getElementById('retry-queue-body');
    if (!data || !data.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No retries queued</td></tr>';
        return;
    }
    tbody.innerHTML = data.map(p => `
        <tr>
            <td>${platformBadge(p.platform)}</td>
            <td title="${p.copy}">${p.copy}</td>
            <td>${p.retry_count}/${p.max_retries}</td>
            <td>${relativeTime(p.scheduled_at)}</td>
            <td title="${p.error || ''}">${(p.error || '—').substring(0, 40)}</td>
        </tr>`).join('');
}

async function updateFailures() {
    const data = await fetchJSON('/api/v1/dashboard/recent-failures');
    const tbody = document.getElementById('failures-body');
    if (!data || !data.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No recent failures</td></tr>';
        return;
    }
    tbody.innerHTML = data.map(a => `
        <tr>
            <td>${shortId(a.post_id)}</td>
            <td>#${a.attempt_number}</td>
            <td>${statusBadge(a.outcome || 'failed')}</td>
            <td title="${a.error_message || ''}">${(a.error_message || '—').substring(0, 40)}</td>
            <td>${relativeTime(a.finished_at)}</td>
        </tr>`).join('');
}

async function updateMissed() {
    const data = await fetchJSON('/api/v1/dashboard/missed-posts');
    const tbody = document.getElementById('missed-body');
    if (!data || !data.length) {
        tbody.innerHTML = '<tr><td colspan="3" class="empty-state">No missed posts</td></tr>';
        return;
    }
    tbody.innerHTML = data.map(p => `
        <tr>
            <td>${platformBadge(p.platform)}</td>
            <td title="${p.copy}">${p.copy}</td>
            <td>${relativeTime(p.scheduled_at)}</td>
        </tr>`).join('');
}

// ── Refresh Loop ──────────────────────────────────────────────────────────

async function refreshAll() {
    await Promise.all([
        updateSummary(),
        updateRateLimits(),
        updateNextDue(),
        updateRetryQueue(),
        updateFailures(),
        updateMissed(),
    ]);
    countdown = REFRESH_INTERVAL;
}

function tick() {
    countdown--;
    document.getElementById('refresh-countdown').textContent = `${countdown}s`;
    if (countdown <= 0) refreshAll();
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    refreshAll();
    setInterval(tick, 1000);
    document.getElementById('btn-refresh').addEventListener('click', refreshAll);
});
