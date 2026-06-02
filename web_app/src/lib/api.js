const API_BASE = '';  // Empty string = same origin (uses Vite proxy in dev)

/**
 * Authenticated fetch wrapper.
 * Automatically adds JWT token from localStorage.
 */
async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('fallguard_token');

  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    // Token expired or invalid
    localStorage.removeItem('fallguard_token');
    localStorage.removeItem('fallguard_user');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ── Auth ──

export async function loginWithGoogle(credential) {
  return apiFetch('/api/auth/google', {
    method: 'POST',
    body: JSON.stringify({ credential }),
  });
}

export async function getMe() {
  return apiFetch('/api/auth/me');
}

// ── Pairing ──

export async function getPairStatus() {
  return apiFetch('/api/pair/status');
}

export async function submitPairCode(code) {
  return apiFetch('/api/pair', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
}

export async function unpair() {
  return apiFetch('/api/pair', { method: 'DELETE' });
}

// ── Cameras ──

export async function getCameras() {
  return apiFetch('/api/cameras');
}

export async function getFrames() {
  return apiFetch('/api/frames');
}

export async function getSingleFrame(ip) {
  return apiFetch(`/api/frames/${ip}`);
}

// ── Fall Events ──

export async function getFallEvents({ limit = 50, offset = 0, camera, dateFrom, dateTo } = {}) {
  const params = new URLSearchParams();
  if (limit) params.set('limit', limit);
  if (offset) params.set('offset', offset);
  if (camera) params.set('camera', camera);
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);

  return apiFetch(`/api/fall-events?${params.toString()}`);
}

// ── Status ──

export async function getSystemStatus() {
  return apiFetch('/api/status');
}
