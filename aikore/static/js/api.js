import { state, DOM } from './state.js';

// --- Authentication ----------------------------------------------------------
// window.AIKORE_API_KEY is initialized by an inline stub in index.html and may
// be overridden at deploy time (e.g. injected by the reverse proxy). When set,
// every API request carries an 'X-API-Key' header; when null, headers stay
// empty and the backend behaves as before (auth disabled).
export function authHeaders() {
    return window.AIKORE_API_KEY ? { 'X-API-Key': window.AIKORE_API_KEY } : {};
}

// Standard headers for JSON payloads, merged with the auth headers.
function jsonHeaders() {
    return { 'Content-Type': 'application/json', ...authHeaders() };
}

// Helper to handle API responses
async function handleResponse(response) {
    const text = await response.text();
    if (response.ok) {
        try {
            // Try to parse JSON, but return success if body is empty
            return text ? JSON.parse(text) : { success: true };
        } catch (e) {
            return { success: true }; // Empty response is also a success
        }
    } else {
        // Clear, actionable message when the API key is missing/invalid
        if (response.status === 401) {
            throw new Error('Authentification requise — vérifiez AIKORE_API_KEY / le proxy (HTTP 401).');
        }
        let errorDetail;
        try {
            // Try to parse as JSON error (FastAPI standard format)
            const json = JSON.parse(text);
            errorDetail = json.detail;
        } catch (e) {
            // If parsing fails, use the raw text (e.g. NGINX HTML error or Python traceback)
            errorDetail = text;
        }
        throw new Error(errorDetail || `HTTP error! status: ${response.status}`);
    }
}

export async function fetchInstances() {
    const response = await fetch('/api/instances/', { headers: authHeaders() });
    return handleResponse(response);
}

export async function fetchSystemInfo() {
    const response = await fetch('/api/system/info', { headers: authHeaders() });
    return handleResponse(response);
}

export async function fetchAndStoreBlueprints() {
    const response = await fetch('/api/system/blueprints', { headers: authHeaders() });
    return handleResponse(response);
}

export async function fetchAvailablePorts() {
    const response = await fetch('/api/system/available-ports', { headers: authHeaders() });
    return handleResponse(response);
}

export async function updateInstanceAutostart(instanceId, autostartValue) {
    const response = await fetch(`/api/instances/${instanceId}`, {
        method: 'PUT',
        headers: jsonHeaders(),
        body: JSON.stringify({ autostart: autostartValue })
    });
    return handleResponse(response);
}

export async function performInstanceAction(instanceId, action) {
    const response = await fetch(`/api/instances/${instanceId}/${action}`, {
        method: 'POST',
        headers: authHeaders()
    });
    return handleResponse(response);
}

export async function createInstance(data) {
    const response = await fetch('/api/instances/', {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify(data)
    });
    return handleResponse(response);
}

// Renamed/Aliased function to match eventHandlers.js call
export async function updateInstance(instanceId, data) {
    return performFullInstanceUpdate(instanceId, data);
}

export async function performFullInstanceUpdate(instanceId, data) {
    const response = await fetch(`/api/instances/${instanceId}`, {
        method: 'PUT',
        headers: jsonHeaders(),
        body: JSON.stringify(data)
    });
    return handleResponse(response);
}

export async function fetchFileContent(instanceId, fileType) {
    const response = await fetch(`/api/instances/${instanceId}/file?file_type=${fileType}`, { headers: authHeaders() });
    return handleResponse(response);
}

export async function updateInstanceScript(instanceId, fileType, content, restart = false) {
    const response = await fetch(`/api/instances/${instanceId}/file?file_type=${fileType}&restart=${restart}`, {
        method: 'PUT',
        headers: jsonHeaders(),
        body: JSON.stringify({ content })
    });
    return handleResponse(response);
}

export async function cloneInstance(instanceId, newName) {
    const response = await fetch(`/api/instances/${instanceId}/copy`, {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify({ new_name: newName })
    });
    return handleResponse(response);
}

export async function instantiateInstance(instanceId, newName) {
    const response = await fetch(`/api/instances/${instanceId}/instantiate`, {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify({ new_name: newName })
    });
    return handleResponse(response);
}

export async function deleteInstance(instanceId, options) {
    const response = await fetch(`/api/instances/${instanceId}`, {
        method: 'DELETE',
        headers: jsonHeaders(),
        body: JSON.stringify(options)
    });
    // Special handling for 409 Conflict
    if (response.status === 409) {
        return { conflict: true };
    }
    return handleResponse(response);
}

export async function rebuildInstance(instanceId) {
    const response = await fetch(`/api/instances/${instanceId}/rebuild`, {
        method: 'POST',
        headers: authHeaders()
    });
    return handleResponse(response);
}

export async function saveCustomBlueprint(filename, content) {
    const response = await fetch('/api/system/blueprints/custom', {
        method: 'POST',
        headers: jsonHeaders(),
        body: JSON.stringify({ filename, content })
    });
    return handleResponse(response);
}

export async function getSystemStats() {
    try {
        const response = await fetch('/api/system/stats', { headers: authHeaders() });
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.warn("Could not fetch system stats:", error);
        return null;
    }
}

export async function fetchLogs(instanceId, offset) {
    const response = await fetch(`/api/instances/${instanceId}/logs?offset=${offset}`, { headers: authHeaders() });
    return handleResponse(response);
}

export async function performVersionCheck(instanceId) {
    const response = await fetch(`/api/instances/${instanceId}/version-check`, {
        method: 'POST',
        headers: authHeaders()
    });
    return handleResponse(response);
}
// --- NEW: Fetch available PyTorch versions for a specific CUDA version ---
export async function fetchCudaVersions() {
    try {
        const response = await fetch('/api/builder/versions/cuda', { headers: authHeaders() });
        if (response.ok) return await response.json();
        throw new Error(`HTTP ${response.status}`);
    } catch (error) {
        console.error('Failed to fetch CUDA versions:', error);
        throw error;
    }
}

export async function fetchTorchVersions(cudaVer) {
    if (!cudaVer) return [];
    const cuString = cudaVer.startsWith('cu') ? cudaVer : 'cu' + cudaVer.replace('.', '');
    try {
        const response = await fetch(`/api/builder/versions/torch/${cuString}`, { headers: authHeaders() });
        if (response.ok) return await response.json();
        throw new Error(`HTTP ${response.status}`);
    } catch (error) {
        console.error(`Failed to fetch torch versions for ${cudaVer}:`, error);
        throw error;
    }
}

export async function fetchAvailablePythonVersions() {
    try {
        const response = await fetch('/api/builder/versions/python', { headers: authHeaders() });
        if (response.ok) return await response.json();
        throw new Error(`HTTP ${response.status}`);
    } catch (e) {
        console.error('Failed to fetch Python versions:', e);
        throw e;
    }
}
