import { state, DOM } from './state.js';
import { deleteInstance, rebuildInstance, saveCustomBlueprint, performFullInstanceUpdate } from './api.js';
import { updateInstanceScript } from './api.js';
import { checkRowForChanges } from './ui.js';

export function showToolsMenu(buttonEl) {
    const row = buttonEl.closest('tr');
    const isSatellite = row.classList.contains('satellite-instance');

    const rect = buttonEl.getBoundingClientRect();
    DOM.toolsContextMenu.style.display = 'block';
    DOM.toolsContextMenu.style.left = `${rect.left}px`;
    DOM.toolsContextMenu.style.top = `${rect.bottom + 5}px`;
    
    DOM.toolsContextMenu.querySelector('[data-action="script"]').disabled = isSatellite;
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

function handleDelete(options) {
    if (!state.instanceToDeleteId) return;
    deleteInstance(state.instanceToDeleteId, options);
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
            const instanceName = state.instanceToRebuild.name;
            const instanceId = state.instanceToRebuild.id;
            hideAllModals();
            rebuildInstance(instanceId, instanceName);
        }
    });

    DOM.restartConfirmModal.addEventListener('click', (e) => {
        const action = e.target.id;
        if (action === 'restart-btn-cancel') {
            hideAllModals();
        } else if (action === 'restart-btn-confirm') {
            updateInstanceScript(true);
        }
    });

    DOM.updateConfirmModal.addEventListener('click', (e) => {
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
    
                checkRowForChanges(row); // This will disable the update button
            }
            hideAllModals();
        } else if (action === 'update-confirm-btn-confirm') {
            if (state.instanceToUpdate) {
                const { row, button } = state.instanceToUpdate;
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
                performFullInstanceUpdate(instanceId, data, button);
            }
            hideAllModals();
        }
    });

    DOM.saveBlueprintModal.addEventListener('click', async (e) => {
        const action = e.target.id;
        if (action === 'save-blueprint-btn-cancel') {
            DOM.saveBlueprintModal.classList.add('hidden');
        } else if (action === 'save-blueprint-btn-confirm') {
            let filename = DOM.blueprintFilenameInput.value.trim();
            const content = state.codeEditor.getValue();
            if (!filename) {
                showToast('Filename cannot be empty.', 'error');
                return;
            }
            if (!filename.endsWith('.sh')) {
                filename += '.sh';
            }
            saveCustomBlueprint(filename, content, e.target);
        }
    });
}
