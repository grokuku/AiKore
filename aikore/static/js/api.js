import { HolafFetch } from '../vendor/holaf-fetch.js';

// --- Authentication ----------------------------------------------------------
// HolafFetch.configure() ne gère QUE { timeout, retry } : l'authentification est
// ENFICHABLE et doit être fournie à CHAQUE requête via `opts.auth` (une clé
// `auth` passée à configure() est silencieusement ignorée). On centralise donc
// la stratégie ici (clé API injectée dans l'en-tête X-API-Key quand elle existe,
// sinon aucun en-tête) et on l'injecte systématiquement via le wrapper `hf`.
const AUTH = {
    type: 'custom',
    headers: () => window.AIKORE_API_KEY ? { 'X-API-Key': window.AIKORE_API_KEY } : {}
};

// En-têtes d'auth bruts pour les rares appels qui utilisent `fetch()` directement
// (ex. tools.js : endpoint builder / whels). Même stratégie que AUTH.
export function authHeaders() {
    return window.AIKORE_API_KEY ? { 'X-API-Key': window.AIKORE_API_KEY } : {};
}

// Petit wrapper : injecte l'auth à chaque appel sans toucher aux signatures
// exportées (URL/body inchangés).
const hf = {
    get: (url, opts = {}) => HolafFetch.get(url, { ...opts, auth: AUTH }),
    post: (url, opts = {}) => HolafFetch.post(url, { ...opts, auth: AUTH }),
    put: (url, opts = {}) => HolafFetch.put(url, { ...opts, auth: AUTH }),
    delete: (url, opts = {}) => HolafFetch.delete(url, { ...opts, auth: AUTH }),
};

export async function fetchInstances() {
    return hf.get('/api/instances/');
}

export async function fetchSystemInfo() {
    return hf.get('/api/system/info');
}

export async function fetchAndStoreBlueprints() {
    return hf.get('/api/system/blueprints');
}

export async function fetchAvailablePorts() {
    return hf.get('/api/system/available-ports');
}

export async function updateInstanceAutostart(instanceId, autostartValue) {
    return hf.put(`/api/instances/${instanceId}`, {
        body: { autostart: autostartValue }
    });
}

export async function performInstanceAction(instanceId, action) {
    return hf.post(`/api/instances/${instanceId}/${action}`);
}

export async function createInstance(data) {
    return hf.post('/api/instances/', { body: data });
}

// Renamed/Aliased function to match eventHandlers.js call
export async function updateInstance(instanceId, data) {
    return performFullInstanceUpdate(instanceId, data);
}

export async function performFullInstanceUpdate(instanceId, data) {
    return hf.put(`/api/instances/${instanceId}`, { body: data });
}

export async function fetchFileContent(instanceId, fileType) {
    return hf.get(`/api/instances/${instanceId}/file?file_type=${fileType}`);
}

export async function updateInstanceScript(instanceId, fileType, content, restart = false) {
    return hf.put(`/api/instances/${instanceId}/file?file_type=${fileType}&restart=${restart}`, {
        body: { content }
    });
}

export async function cloneInstance(instanceId, newName) {
    return hf.post(`/api/instances/${instanceId}/copy`, {
        body: { new_name: newName }
    });
}

export async function instantiateInstance(instanceId, newName) {
    return hf.post(`/api/instances/${instanceId}/instantiate`, {
        body: { new_name: newName }
    });
}

export async function deleteInstance(instanceId, options) {
    try {
        return await hf.delete(`/api/instances/${instanceId}`, { body: options });
    } catch (err) {
        if (err.status === 409) {
            return { conflict: true };
        }
        throw err;
    }
}

export async function rebuildInstance(instanceId) {
    return hf.post(`/api/instances/${instanceId}/rebuild`);
}

export async function saveCustomBlueprint(filename, content) {
    return hf.post('/api/system/blueprints/custom', {
        body: { filename, content }
    });
}

export async function getSystemStats() {
    try {
        return await hf.get('/api/system/stats');
    } catch (error) {
        console.warn("Could not fetch system stats:", error);
        return null;
    }
}

export async function fetchLogs(instanceId, offset) {
    return hf.get(`/api/instances/${instanceId}/logs?offset=${offset}`);
}

export async function performVersionCheck(instanceId) {
    return hf.post(`/api/instances/${instanceId}/version-check`);
}

export async function fetchCudaVersions() {
    try {
        return await hf.get('/api/builder/versions/cuda');
    } catch (error) {
        console.error('Failed to fetch CUDA versions:', error);
        throw error;
    }
}

// --- Version helpers -------------------------------------------------------
// The UI manipulates CUDA identifiers in two shapes: the PyTorch wheel folder
// ('cu130') and the dotted version ('13.0'). They must collapse to ONE
// canonical cache key, otherwise the same torch list is fetched twice under
// '13.0' and 'cu130'. Returns 'cuNNN' (or '' when there are no digits).
export function normalizeCudaKey(cudaVer) {
    if (!cudaVer) return '';
    const s = String(cudaVer).trim();
    if (/^cu\d+$/i.test(s)) return s.toLowerCase();
    const digits = s.replace(/[^0-9]/g, '');
    return digits ? 'cu' + digits : '';
}

// Numeric descending sort for dotted version strings ('2.9.1' must NOT rank
// above '2.11.0', unlike a lexicographic sort).
export function sortVersionsDesc(list) {
    return [...(list || [])].sort((a, b) => {
        const pa = String(a).split('.').map(n => parseInt(n, 10) || 0);
        const pb = String(b).split('.').map(n => parseInt(n, 10) || 0);
        const len = Math.max(pa.length, pb.length);
        for (let i = 0; i < len; i++) {
            const d = (pb[i] || 0) - (pa[i] || 0);
            if (d) return d;
        }
        return 0;
    });
}

// Numeric descending sort for CUDA entries ({cu, version} objects or raw
// 'cuNNN' strings). Guards the "CUDA 9.2 (Latest)" bug on the client side too.
export function sortCudaVersionsDesc(list) {
    const rank = (entry) => {
        const key = normalizeCudaKey(typeof entry === 'string' ? entry : (entry && entry.cu));
        const n = parseInt(key.replace(/^cu/, ''), 10);
        return isNaN(n) ? -1 : n;
    };
    return [...(list || [])].sort((a, b) => rank(b) - rank(a));
}

export async function fetchTorchVersions(cudaVer) {
    const cuString = normalizeCudaKey(cudaVer);
    if (!cuString) return [];
    try {
        return await hf.get(`/api/builder/versions/torch/${cuString}`);
    } catch (error) {
        console.error(`Failed to fetch torch versions for ${cudaVer}:`, error);
        throw error;
    }
}

export async function fetchAvailablePythonVersions() {
    try {
        return await hf.get('/api/builder/versions/python');
    } catch (e) {
        console.error('Failed to fetch Python versions:', e);
        throw e;
    }
}
