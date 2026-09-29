import { state, DOM } from './state.js';

// --- Authentication ----------------------------------------------------------
// Configure HolafFetch with a custom auth strategy that uses the API key
HolafFetch.configure({
    auth: {
        type: 'custom',
        headers: () => window.AIKORE_API_KEY ? { 'X-API-Key': window.AIKORE_API_KEY } : {}
    }
});

export async function fetchInstances() {
    return HolafFetch.get('/api/instances/');
}

export async function fetchSystemInfo() {
    return HolafFetch.get('/api/system/info');
}

export async function fetchAndStoreBlueprints() {
    return HolafFetch.get('/api/system/blueprints');
}

export async function fetchAvailablePorts() {
    return HolafFetch.get('/api/system/available-ports');
}

export async function updateInstanceAutostart(instanceId, autostartValue) {
    return HolafFetch.put(`/api/instances/${instanceId}`, {
        body: { autostart: autostartValue }
    });
}

export async function performInstanceAction(instanceId, action) {
    return HolafFetch.post(`/api/instances/${instanceId}/${action}`);
}

export async function createInstance(data) {
    return HolafFetch.post('/api/instances/', { body: data });
}

// Renamed/Aliased function to match eventHandlers.js call
export async function updateInstance(instanceId, data) {
    return performFullInstanceUpdate(instanceId, data);
}

export async function performFullInstanceUpdate(instanceId, data) {
    return HolafFetch.put(`/api/instances/${instanceId}`, { body: data });
}

export async function fetchFileContent(instanceId, fileType) {
    return HolafFetch.get(`/api/instances/${instanceId}/file?file_type=${fileType}`);
}

export async function updateInstanceScript(instanceId, fileType, content, restart = false) {
    return HolafFetch.put(`/api/instances/${instanceId}/file?file_type=${fileType}&restart=${restart}`, {
        body: { content }
    });
}

export async function cloneInstance(instanceId, newName) {
    return HolafFetch.post(`/api/instances/${instanceId}/copy`, {
        body: { new_name: newName }
    });
}

export async function instantiateInstance(instanceId, newName) {
    return HolafFetch.post(`/api/instances/${instanceId}/instantiate`, {
        body: { new_name: newName }
    });
}

export async function deleteInstance(instanceId, options) {
    try {
        return await HolafFetch.delete(`/api/instances/${instanceId}`, { body: options });
    } catch (err) {
        if (err.status === 409) {
            return { conflict: true };
        }
        throw err;
    }
}

export async function rebuildInstance(instanceId) {
    return HolafFetch.post(`/api/instances/${instanceId}/rebuild`);
}

export async function saveCustomBlueprint(filename, content) {
    return HolafFetch.post('/api/system/blueprints/custom', {
        body: { filename, content }
    });
}

export async function getSystemStats() {
    try {
        return await HolafFetch.get('/api/system/stats');
    } catch (error) {
        console.warn("Could not fetch system stats:", error);
        return null;
    }
}

export async function fetchLogs(instanceId, offset) {
    return HolafFetch.get(`/api/instances/${instanceId}/logs?offset=${offset}`);
}

export async function performVersionCheck(instanceId) {
    return HolafFetch.post(`/api/instances/${instanceId}/version-check`);
}

export async function fetchCudaVersions() {
    try {
        return await HolafFetch.get('/api/builder/versions/cuda');
    } catch (error) {
        console.error('Failed to fetch CUDA versions:', error);
        throw error;
    }
}

export async function fetchTorchVersions(cudaVer) {
    if (!cudaVer) return [];
    const cuString = cudaVer.startsWith('cu') ? cudaVer : 'cu' + cudaVer.replace('.', '');
    try {
        return await HolafFetch.get(`/api/builder/versions/torch/${cuString}`);
    } catch (error) {
        console.error(`Failed to fetch torch versions for ${cudaVer}:`, error);
        throw error;
    }
}

export async function fetchAvailablePythonVersions() {
    try {
        return await HolafFetch.get('/api/builder/versions/python');
    } catch (e) {
        console.error('Failed to fetch Python versions:', e);
        throw e;
    }
}
