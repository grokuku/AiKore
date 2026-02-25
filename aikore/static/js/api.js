import { state, DOM } from './state.js';

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

export async function fetchSystemInfo() {
    const response = await fetch('/api/system/info');
    return handleResponse(response);
}

export async function fetchAndStoreBlueprints() {
    const response = await fetch('/api/system/blueprints');
    return handleResponse(response);
}

export async function fetchAvailablePorts() {
    const response = await fetch('/api/system/available-ports');
    return handleResponse(response);
}

export async function updateInstanceAutostart(instanceId, autostartValue) {
    const response = await fetch(`/api/instances/${instanceId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ autostart: autostartValue })
    });
    return handleResponse(response);
}

export async function performInstanceAction(instanceId, action) {
    const response = await fetch(`/api/instances/${instanceId}/${action}`, { method: 'POST' });
    return handleResponse(response);
}

export async function createInstance(data) {
    const response = await fetch('/api/instances/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    return handleResponse(response);
}

export async function fetchFileContent(instanceId, fileType) {
    const response = await fetch(`/api/instances/${instanceId}/file?file_type=${fileType}`);
    return handleResponse(response);
}

export async function updateInstanceScript(instanceId, fileType, content, restart = false) {
    const response = await fetch(`/api/instances/${instanceId}/file?file_type=${fileType}&restart=${restart}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
    });
    return handleResponse(response);
}

export async function cloneInstance(instanceId, newName) {
    const response = await fetch(`/api/instances/${instanceId}/copy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName })
    });
    return handleResponse(response);
}

export async function instantiateInstance(instanceId, newName) {
    const response = await fetch(`/api/instances/${instanceId}/instantiate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName })
    });
    return handleResponse(response);
}

export async function deleteInstance(instanceId, options) {
    const response = await fetch(`/api/instances/${instanceId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options)
    });
    // Special handling for 409 Conflict
    if (response.status === 409) {
        return { conflict: true };
    }
    return handleResponse(response);
}

export async function rebuildInstance(instanceId) {
    const response = await fetch(`/api/instances/${instanceId}/rebuild`, { method: 'POST' });
    return handleResponse(response);
}

export async function saveCustomBlueprint(filename, content) {
    const response = await fetch('/api/system/blueprints/custom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, content })
    });
    return handleResponse(response);
}

export async function getSystemStats() {
    try {
        const response = await fetch('/api/system/stats');
        if (!response.ok) return null;
        return await response.json();
    } catch (error) {
        console.warn("Could not fetch system stats:", error);
        return null;
    }
}

export async function fetchLogs(instanceId, offset) {
    const response = await fetch(`/api/instances/${instanceId}/logs?offset=${offset}`);
    return handleResponse(response);
}

export async function performVersionCheck(instanceId) {
    const response = await fetch(`/api/instances/${instanceId}/version-check`, {
        method: 'POST'
    });
    return handleResponse(response);
}
// --- NEW: Fetch available PyTorch versions for a specific CUDA version ---
export async function fetchTorchVersions(cudaVer) {
    // Si cudaVer est vide ("CUDA Auto"), on utilise 12.8 par défaut pour peupler la liste
    const targetCuda = cudaVer || '12.8'; 
    const cuString = 'cu' + targetCuda.replace('.', '');
    try {
        const response = await fetch(`/api/builder/versions/torch/${cuString}`);
        if (response.ok) {
            return await response.json();
        }
    } catch (error) {
        console.error(`Failed to fetch torch versions for ${targetCuda}:`, error);
    }
    // Updated fallback list
    return['2.11.0', '2.10.0', '2.9.1', '2.8.0', '2.7.0', '2.6.0', '2.5.1'];
}
export async function fetchAvailablePythonVersions() {
    try {
        const response = await fetch('/api/builder/versions/python');
        if (row.ok) return await response.json();
    } catch (e) {
        console.error("Discovery failed", e);
    }
    return ['3.15', '3.14', '3.13', '3.12', '3.11', '3.10']; // Fallback
}