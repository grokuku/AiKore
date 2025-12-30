import { state, DOM } from './state.js';
import * as api from './api.js';
import { checkRowForChanges, showToast } from './ui.js';
import { fetchAndRenderInstances } from './main.js';
import { exitEditor } from './tools.js';

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
    DOM.deleteModal.classList.add('hidden');
    DOM.overwriteModal.classList.add('hidden');
    DOM.rebuildModal.classList.add('hidden');
    DOM.restartConfirmModal.classList.add('hidden');
    DOM.saveBlueprintModal.classList.add('hidden');
    DOM.updateConfirmModal.classList.add('hidden');
    state.instanceToDeleteId = null;
    state.instanceToRebuild = null;
    state.instanceToUpdate = null;
}

async function handleDelete(options) {
    if (!state.instanceToDeleteId) return;
    try {
        const result = await api.deleteInstance(state.instanceToDeleteId, options);
        if (result.conflict) {
            hideAllModals();
            document.getElementById('overwrite-modal-instance-name').textContent = document.getElementById('delete-modal-instance-name').textContent;
            DOM.overwriteModal.classList.remove('hidden');
            return;
        }
        showToast("Instance moved to trashcan.");
        hideAllModals();
        await fetchAndRenderInstances();
    } catch (error) {
        showToast(error.message, 'error');
        hideAllModals();
    }
}

export function setupModalEventHandlers() {
    DOM.deleteModal.addEventListener('click', (e) => {
        const action = e.target.id;
        if (action === 'delete-btn-cancel') hideAllModals();
        else if (action === 'delete-btn-trash') handleDelete({ mode: 'trash', overwrite: false });
        else if (action === 'delete-btn-permanent') handleDelete({ mode: 'permanent', overwrite: false });
    });

    DOM.overwriteModal.addEventListener('click', (e) => {
        const action = e.target.id;
        if (action === 'overwrite-btn-cancel') hideAllModals();
        else if (action === 'overwrite-btn-confirm') handleDelete({ mode: 'trash', overwrite: true });
    });

    DOM.rebuildModal.addEventListener('click', async (e) => {
        const action = e.target.id;
        if (action === 'rebuild-btn-cancel') {
            hideAllModals();
        } else if (action === 'rebuild-btn-confirm') {
            if (!state.instanceToRebuild) {
                showToast("Error: Instance context lost. Please try again.", "error");
                hideAllModals();
                return;
            }
            const { id, name } = state.instanceToRebuild;
            hideAllModals();
            try {
                await api.rebuildInstance(id);
                showToast(`Rebuild process for '${name}' has been successfully initiated.`);
                await fetchAndRenderInstances();
            } catch (error) {
                showToast(error.message, 'error');
            }
        }
    });

    DOM.restartConfirmModal.addEventListener('click', async (e) => {
        const action = e.target.id;
        if (action === 'restart-btn-cancel') {
            hideAllModals();
        } else if (action === 'restart-btn-confirm') {
            const { instanceId, fileType } = state.editorState;
            const content = state.codeEditor.getValue();
            hideAllModals();
            
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

    DOM.updateConfirmModal.addEventListener('click', async (e) => {
        const action = e.target.id;
        if (action === 'update-confirm-btn-cancel') {
            if (state.instanceToUpdate) {
                const { row } = state.instanceToUpdate;
                // Revert changes in the UI
                row.querySelector('input[data-field="name"]').value = row.dataset.originalName;
                row.querySelector('select[data-field="base_blueprint"]').value = row.dataset.originalBlueprint;
                row.querySelector('input[data-field="output_path"]').value = row.dataset.originalOutputPath || '';
                row.querySelector('input[data-field="persistent_mode"]').checked = row.dataset.originalPersistentMode === 'true';
                row.querySelector('input[data-field="use_custom_hostname"]').checked = row.dataset.originalUseCustomHostname === 'true';
                row.querySelector('input[data-field="hostname"]').value = row.dataset.originalHostname || '';
                
                const originalGpus = (row.dataset.originalGpuIds || '').split(',').filter(id => id);
                row.querySelectorAll('input[name^="gpu_id_"]').forEach(cb => {
                    cb.checked = originalGpus.includes(cb.value);
                });
    
                checkRowForChanges(row);
            }
            hideAllModals();
        } else if (action === 'update-confirm-btn-confirm') {
            if (state.instanceToUpdate) {
                const { row } = state.instanceToUpdate;
                const instanceId = row.dataset.id;
                const data = {
                    name: row.querySelector('input[data-field="name"]').value,
                    base_blueprint: row.querySelector('select[data-field="base_blueprint"]').value,
                    output_path: row.querySelector('input[data-field="output_path"]').value || null,
                    gpu_ids: Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(','),
                    persistent_mode: row.querySelector('input[data-field="persistent_mode"]').checked,
                    hostname: row.querySelector('input[data-field="hostname"]').value || null,
                    use_custom_hostname: row.querySelector('input[data-field="use_custom_hostname"]').checked,
                };
                
                const button = e.target;
                const originalButtonText = button.textContent;
                button.textContent = 'Updating...';
                button.disabled = true;

                try {
                    await api.performFullInstanceUpdate(instanceId, data);
                    showToast(`Instance '${data.name}' is being updated.`, 'success');
                    await fetchAndRenderInstances();
                } catch (error) {
                    showToast(error.message, 'error');
                } finally {
                    button.textContent = originalButtonText;
                    button.disabled = false;
                    hideAllModals();
                }
            }
        }
    });

    DOM.saveBlueprintModal.addEventListener('click', async (e) => {
        const action = e.target.id;
        if (action === 'save-blueprint-btn-cancel') {
            hideAllModals();
        } else if (action === 'save-blueprint-btn-confirm') {
            let filename = DOM.blueprintFilenameInput.value.trim();
            if (!filename) {
                showToast('Filename cannot be empty.', 'error');
                return;
            }
            if (!filename.endsWith('.sh')) {
                filename += '.sh';
            }
            const content = state.codeEditor.getValue();
            
            const button = e.target;
            button.textContent = 'Saving...';
            button.disabled = true;

            try {
                const savedData = await api.saveCustomBlueprint(filename, content);
                hideAllModals();
                showToast(`Custom blueprint '${savedData.filename}' saved successfully.`, 'success');
                const blueprints = await api.fetchAndStoreBlueprints();
                state.availableBlueprints = blueprints;
                await fetchAndRenderInstances();
            } catch (error) {
                showToast(error.message, 'error');
            } finally {
                button.textContent = 'Save Blueprint';
                button.disabled = false;
            }
        }
    });
}