import { state, DOM } from './state.js';
import * as api from './api.js';
import { checkRowForChanges, showToast } from './ui.js';
import { fetchAndRenderInstances } from './main.js';
import { exitEditor, closeTerminalById } from './tools.js';

export function showToolsMenu(buttonEl) {
    const row = buttonEl.closest('tr');
    const isSatellite = row.classList.contains('satellite-instance');

    const rect = buttonEl.getBoundingClientRect();
    DOM.toolsContextMenu.style.display = 'block';
    DOM.toolsContextMenu.style.left = `${rect.left}px`;
    DOM.toolsContextMenu.style.top = `${rect.bottom + 5}px`;
    
    DOM.toolsContextMenu.querySelector('[data-action="script"]').disabled = isSatellite;
    DOM.toolsContextMenu.querySelector('[data-action="terminal"]').disabled = isSatellite;
    DOM.toolsContextMenu.querySelector('[data-action="manage-wheels"]').disabled = isSatellite; // DISABLED FOR SATELLITES
    DOM.toolsContextMenu.querySelector('[data-action="rebuild-env"]').disabled = isSatellite;
    DOM.toolsContextMenu.querySelector('[data-action="clone"]').disabled = isSatellite;
    DOM.toolsContextMenu.querySelector('[data-action="instantiate"]').disabled = isSatellite;

    state.currentMenuInstance = { id: row.dataset.id, name: row.dataset.name, status: row.dataset.status };
}

export function hideToolsMenu() {
    DOM.toolsContextMenu.style.display = 'none';
    state.currentMenuInstance = null;
}

export function hideAllModals() {
    // HolafModal manages its own stack, no need to manually hide hidden classes anymore.
    state.instanceToDeleteId = null;
    state.instanceToRebuild = null;
    state.instanceToUpdate = null;
}

async function handleDelete(options) {
    if (!state.instanceToDeleteId) return;
    try {
        const result = await api.deleteInstance(state.instanceToDeleteId, options);
        if (result.conflict) {
            // Open Overwrite Confirmation Modal
            const name = document.getElementById('delete-modal-instance-name')?.textContent || state.currentMenuInstance?.name || '';
            
            await HolafModal.open({
                title: 'Overwrite Confirmation',
                content: `An instance with the name "${name}" already exists in the trashcan.\n\nDo you want to overwrite it?`,
                buttons: [
                    { text: 'Overwrite', type: 'danger', value: true, onClick: () => {} },
                    { text: 'Cancel', type: 'cancel', value: false }
                ]
            }).then(res => {
                if (res === true) {
                    handleDelete({ mode: 'trash', overwrite: true });
                }
            });
            return;
        }
        closeTerminalById(state.instanceToDeleteId);
        showToast("Instance moved to trashcan.");
        await fetchAndRenderInstances();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

export function setupModalEventHandlers() {
    // This function is now largely empty or can be removed as we use programmatic modals.
    // However, to keep compatibility with main.js calling it, we leave it.
}

// NEW: Programmatic Modal Triggers
export async function openDeleteModal(instanceId, name) {
    state.instanceToDeleteId = instanceId;
    await HolafModal.open({
        title: `Delete Instance: ${name}`,
        content: 'Choose a deletion method:',
        buttons: [
            { text: 'Permanent Delete', type: 'danger', value: { mode: 'permanent', overwrite: false }, onClick: () => {} },
            { text: 'Move to Trashcan', type: 'primary', value: { mode: 'trash', overwrite: false }, onClick: () => {} },
            { text: 'Cancel', type: 'cancel', value: null }
        ]
    }).then(res => {
        if (res) handleDelete(res);
    });
}

export async function openRebuildModal(instance) {
    state.instanceToRebuild = instance;
    await HolafModal.open({
        title: `Rebuild Environment: ${instance.name}`,
        content: 'This will rebuild the environment. Continue?',
        buttons: [
            { text: 'Confirm Rebuild', type: 'primary', value: true },
            { text: 'Cancel', type: 'cancel', value: false }
        ]
    }).then(async res => {
        if (res === true) {
            try {
                await api.rebuildInstance(instance.id);
                showToast(`Rebuild process for '${instance.name}' has been successfully initiated.`);
                await fetchAndRenderInstances();
            } catch (error) {
                showToast(error.message, 'error');
            }
        }
    });
}

export async function openRestartConfirmModal(instanceName) {
    await HolafModal.open({
        title: 'Instance Restart Required',
        content: `To apply these script changes, the instance '${instanceName}' must be restarted.\n\nDo you want to save and restart?`,
        buttons: [
            { text: 'Save & Restart', type: 'primary', value: true },
            { text: 'Cancel', type: 'cancel', value: false }
        ]
    }).then(async res => {
        if (res === true) {
            const { instanceId, fileType } = state.editorState;
            const content = state.codeEditor.getValue();
            
            const button = DOM.editorUpdateBtn;
            button.textContent = 'Updating...';
            button.disabled = true;

            try {
                await api.updateInstanceScript(instanceId, fileType, content, true);
                showToast('Instance script updated. Restarting instance...', 'success');
                exitEditor();
                await fetchAndRenderInstances();
            } catch (error) {
                showToast(`Error updating script: ${error.message}`, 'error');
            } finally {
                button.textContent = 'Update Instance';
                button.disabled = false;
            }
        }
    });
}

export async function openSaveBlueprintModal() {
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'e.g., my-custom-comfy.sh';
    input.className = 'holaf-modal-input';
    input.style.width = '100%';

    await HolafModal.open({
        title: 'Save as Custom Blueprint',
        content: 'Enter a filename for the new custom blueprint.',
        // We can pass a Node as content. We'll wrap it.
        content: [
            document.createElement('p'), // spacer
            input
        ],
        buttons: [
            { text: 'Save Blueprint', type: 'primary', value: true },
            { text: 'Cancel', type: 'cancel', value: false }
        ]
    }).then(async res => {
        if (res === true) {
            let filename = input.value.trim();
            if (!filename) {
                showToast('Filename cannot be empty.', 'error');
                return;
            }
            if (!filename.endsWith('.sh')) filename += '.sh';
            
            const content = state.codeEditor.getValue();
            try {
                const savedData = await api.saveCustomBlueprint(filename, content);
                showToast(`Custom blueprint '${savedData.filename}' saved successfully.`, 'success');
                const blueprints = await api.fetchAndStoreBlueprints();
                state.availableBlueprints = blueprints;
                await fetchAndRenderInstances();
            } catch (error) {
                showToast(error.message, 'error');
            }
        }
    });
}

export async function openUpdateConfirmModal(changes, onConfirm) {
    const list = document.createElement('div');
    list.className = 'changes-list';
    changes.forEach(c => {
        const item = document.createElement('div');
        item.textContent = c;
        list.appendChild(item);
    });

    await HolafModal.open({
        title: 'Confirm Global Changes',
        content: [
            document.createElement('p'), // dummy
            list
        ],
        buttons: [
            { text: 'Apply All Changes', type: 'primary', value: true },
            { text: 'Cancel', type: 'cancel', value: false }
        ]
    }).then(res => {
        if (res === true) {
            onConfirm();
        } else {
            // Revert UI changes as in original code
            if (state.pendingUpdates) {
                state.pendingUpdates.forEach(update => {
                    const row = update.row;
                    if (!row) return;
                    row.querySelector('input[data-field="name"]').value = row.dataset.originalName;
                    row.querySelector('[data-field="base_blueprint"]').value = row.dataset.originalBlueprint;
                    row.querySelector('input[data-field="output_path"]').value = row.dataset.originalOutputPath || '';
                    row.querySelector('input[data-field="persistent_mode"]').checked = row.dataset.originalPersistentMode === 'true';
                    row.querySelector('input[data-field="use_custom_hostname"]').checked = row.dataset.originalUseCustomHostname === 'true';
                    row.querySelector('input[data-field="hostname"]').value = row.dataset.originalHostname || '';
                    
                    const originalGpus = (row.dataset.originalGpuIds || '').split(',').filter(id => id);
                    row.querySelectorAll('input[name^="gpu_id_"]').forEach(cb => {
                        cb.checked = originalGpus.includes(cb.value);
                    });
                    checkRowForChanges(row);
                });
            }
        }
    });
}
