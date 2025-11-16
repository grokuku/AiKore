import { showToast } from './ui.js';
import { state, DOM } from './state.js';
import { fetchAndRenderInstances } from './main.js';
import { hideAllModals } from './modals.js';
import { exitEditor } from './tools.js';

export async function fetchSystemInfo() {
    try {
        const response = await fetch('/api/system/info');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        state.systemInfo = await response.json();
    } catch (error) {
        console.error("Failed to fetch system info:", error);
        state.systemInfo = { gpu_count: 0, gpus: [] };
    }
}

export async function fetchAndStoreBlueprints() {
    try {
        const response = await fetch('/api/system/blueprints');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        state.availableBlueprints = data;
    } catch (error) {
        console.error("Failed to fetch blueprints:", error);
        state.availableBlueprints = { stock: ["Error loading blueprints"], custom: [] };
    }
}

export async function fetchAvailablePorts() {
    try {
        const response = await fetch('/api/system/available-ports');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        state.availablePorts = data.available_ports;
    } catch (error) {
        console.error("Failed to fetch available ports:", error);
        state.availablePorts = [];
    }
}

export async function updateInstanceAutostart(instanceId, autostartValue, instanceName) {
    try {
        const response = await fetch(`/api/instances/${instanceId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ autostart: autostartValue })
        });
        if (!response.ok) throw new Error((await response.json()).detail);
        const updatedInstance = await response.json();

        const row = DOM.instancesTbody.querySelector(`tr[data-id="${instanceId}"]`);
        if (row) {
            row.dataset.originalAutostart = String(updatedInstance.autostart);
        }
        showToast(`Autostart for '${instanceName}' updated.`, 'success');
    } catch (error) {
        showToast(`Error updating autostart: ${error.message}`, 'error');
        const row = DOM.instancesTbody.querySelector(`tr[data-id="${instanceId}"]`);
        if (row) {
            row.querySelector('input[data-field="autostart"]').checked = !autostartValue;
        }
    }
}

export async function performInstanceAction(instanceId, action) {
    try {
        const response = await fetch(`/api/instances/${instanceId}/${action}`, { method: 'POST' });
        if (!response.ok) throw new Error((await response.json()).detail);
        await fetchAndRenderInstances();
    } catch (error) {
        showToast(error.message, 'error');
        await fetchAndRenderInstances();
    }
}

export async function createInstance(data) {
    try {
        const response = await fetch('/api/instances/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (!response.ok) throw new Error((await response.json()).detail);
        await fetchAndRenderInstances();
        showToast(`Instance '${data.name}' created successfully.`);
    } catch (error) {
        showToast(error.message, 'error');
    }
}

export async function performFullInstanceUpdate(instanceId, data, button) {
    const modalConfirmButton = document.getElementById('update-confirm-btn-confirm');
    const originalButtonText = modalConfirmButton.textContent;
    modalConfirmButton.textContent = 'Updating...';
    modalConfirmButton.disabled = true;

    try {
        const response = await fetch(`/api/instances/${instanceId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to update instance.');
        }
        
        showToast(`Instance '${data.name}' is being updated.`, 'success');
        await fetchAndRenderInstances();

    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        modalConfirmButton.textContent = originalButtonText;
        modalConfirmButton.disabled = false;
    }
}

export async function fetchFileContent(instanceId, fileType) {
    try {
        const response = await fetch(`/api/instances/${instanceId}/file?file_type=${fileType}`);
        if (!response.ok) throw new Error((await response.json()).detail || 'Failed to load file.');
        const data = await response.json();
        return data.content;
    } catch (error) {
        return `[ERROR] Could not load file: ${error.message}`;
    }
}

export async function updateInstanceScript(restart = false) {
    if (!state.editorState.instanceId || !state.editorState.fileType) return;
    const content = state.codeEditor.getValue();
    DOM.editorUpdateBtn.textContent = 'Updating...';
    DOM.editorUpdateBtn.disabled = true;
    try {
        const response = await fetch(`/api/instances/${state.editorState.instanceId}/file?file_type=${state.editorState.fileType}&restart=${restart}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content })
        });
        if (!response.ok) throw new Error((await response.json()).detail || 'Failed to save file.');
        
        if (restart) {
            showToast('Instance script updated. Restarting instance...', 'success');
            exitEditor(); // Close editor and go back to welcome screen
        } else {
            showToast('Instance script updated successfully.', 'success');
        }
    } catch (error) {
        showToast(`Error updating script: ${error.message}`, 'error');
    } finally {
        DOM.editorUpdateBtn.textContent = 'Update Instance';
        DOM.editorUpdateBtn.disabled = false;
        hideAllModals();
    }
}

export async function cloneInstance(instanceId, sourceName, newName) {
    try {
        const response = await fetch(`/api/instances/${instanceId}/copy`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to clone instance.');
        }
        showToast(`Instance '${sourceName}' successfully cloned as '${newName}'.`);
        await fetchAndRenderInstances();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

export async function instantiateInstance(instanceId, sourceName, newName) {
    try {
        const response = await fetch(`/api/instances/${instanceId}/instantiate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to instantiate instance.');
        }
        showToast(`Instance '${sourceName}' successfully instantiated as '${newName}'.`);
        await fetchAndRenderInstances();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

export async function deleteInstance(instanceId, options) {
    try {
        const response = await fetch(`/api/instances/${instanceId}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options)
        });
        if (response.status === 409) {
            hideAllModals();
            document.getElementById('overwrite-modal-instance-name').textContent = document.getElementById('delete-modal-instance-name').textContent;
            DOM.overwriteModal.classList.remove('hidden');
            return;
        }
        if (!response.ok) throw new Error((await response.json()).detail);
        showToast("Instance moved to trashcan.");
        hideAllModals();
        await fetchAndRenderInstances();
    } catch (error) {
        showToast(error.message, 'error');
        hideAllModals();
    }
}

export async function rebuildInstance(instanceId, instanceName) {
    try {
        const response = await fetch(`/api/instances/${instanceId}/rebuild`, { method: 'POST' });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to initiate rebuild.');
        }
        showToast(`Rebuild process for '${instanceName}' has been successfully initiated.`);
        await fetchAndRenderInstances();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

export async function saveCustomBlueprint(filename, content, button) {
    button.textContent = 'Saving...';
    button.disabled = true;
    try {
        const response = await fetch('/api/system/blueprints/custom', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, content })
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to save custom blueprint.');
        }
        const savedData = await response.json();
        hideAllModals();
        showToast(`Custom blueprint '${savedData.filename}' saved successfully.`, 'success');
        await fetchAndStoreBlueprints();
        await fetchAndRenderInstances(); // Refresh to update dropdowns in any 'new' rows.
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        button.textContent = 'Save Blueprint';
        button.disabled = false;
    }
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

export async function getBestGpu() {
    try {
        const stats = await getSystemStats();
        if (stats && stats.gpus && stats.gpus.length > 0) {
            let maxFreeVram = -1;
            let bestGpuId = null;
            stats.gpus.forEach(gpu => {
                const freeVram = gpu.vram.total - gpu.vram.used;
                if (freeVram > maxFreeVram) {
                    maxFreeVram = freeVram;
                    bestGpuId = gpu.id;
                }
            });
            return bestGpuId;
        }
    } catch (error) {
        console.error("Could not fetch system stats for default GPU selection:", error);
    }
    return null;
}

export async function fetchLogs(instanceId) {
    try {
        const response = await fetch(`/api/instances/${instanceId}/logs?offset=${state.logSize}`);
        if (!response.ok) throw new Error('Instance stopped or logs unavailable.');
        return await response.json();
    } catch (error) {
        clearInterval(state.activeLogInterval);
        state.activeLogInstanceId = null;
        return null;
    }
}

export async function performVersionCheck(instanceId) {
    try {
        const response = await fetch(`/api/instances/${instanceId}/version-check`, {
            method: 'POST'
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        const errorMessage = `[ERROR] Could not perform version check: ${error.message}`;
        console.error(errorMessage);
        return { versions: errorMessage, conflicts: '' };
    }
}
