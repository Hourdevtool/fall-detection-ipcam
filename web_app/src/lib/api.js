const API_BASE = '';  // Empty string = same origin (uses Vite proxy in dev)

/**
 * Authenticated fetch wrapper.
 * Automatically adds JWT token from localStorage.
 */
async function apiFetch(path, options = {}) {
  // Use device-specific apiBase and token if provided, fallback to localStorage
  const apiBase = options.apiBase || API_BASE;
  const token = options.token || localStorage.getItem('fallguard_token');

  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const cleanApiBase = apiBase && !apiBase.startsWith('http') ? `http://${apiBase}` : apiBase;
  const response = await fetch(`${cleanApiBase}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    // Only clear main token if it failed on the main host
    if (!options.apiBase) {
      localStorage.removeItem('fallguard_token');
      localStorage.removeItem('fallguard_user');
      window.location.href = '/login';
    }
    throw new Error('Unauthorized');
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// ── Auth ──

export async function loginWithGoogle(credential, apiBase = '') {
  return apiFetch('/api/auth/google', {
    method: 'POST',
    body: JSON.stringify({ credential }),
    apiBase,
  });
}

export async function getMe(device = null) {
  return apiFetch('/api/auth/me', {
    apiBase: device?.ip,
    token: device?.token,
  });
}

// ── Pairing ──

export async function getPairStatus(device = null) {
  return apiFetch('/api/pair/status', {
    apiBase: device?.ip,
    token: device?.token,
  });
}

export async function submitPairCode(code, device = null) {
  return apiFetch('/api/pair', {
    method: 'POST',
    body: JSON.stringify({ code }),
    apiBase: device?.ip,
    token: device?.token,
  });
}

export async function unpair(device = null) {
  return apiFetch('/api/pair', { 
    method: 'DELETE',
    apiBase: device?.ip,
    token: device?.token,
  });
}

// ── Cameras ──

export async function getCameras(device = null) {
  return apiFetch('/api/cameras', {
    apiBase: device?.ip,
    token: device?.token,
  });
}

export async function getFrames(device = null) {
  return apiFetch('/api/frames', {
    apiBase: device?.ip,
    token: device?.token,
  });
}

export async function getSingleFrame(ip, device = null) {
  return apiFetch(`/api/frames/${ip}`, {
    apiBase: device?.ip,
    token: device?.token,
  });
}

// ── Fall Events ──

export async function getFallEvents({ limit = 50, offset = 0, camera, dateFrom, dateTo, device = null } = {}) {
  const params = new URLSearchParams();
  if (limit) params.set('limit', limit);
  if (offset) params.set('offset', offset);
  if (camera) params.set('camera', camera);
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);

  return apiFetch(`/api/fall-events?${params.toString()}`, {
    apiBase: device?.ip,
    token: device?.token,
  });
}

// ── Status ──

export async function getSystemStatus(device = null) {
  return apiFetch('/api/status', {
    apiBase: device?.ip,
    token: device?.token,
  });
}

