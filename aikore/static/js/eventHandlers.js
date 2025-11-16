import { state, DOM } from './state.js';
import * as api from './api.js';
import { showToolsMenu, hideToolsMenu } from './modals.js';
import { openEditor, openTerminal, showVersionCheckView, openInstanceView, showLogViewer } from './tools.js';
import { renderInstanceRow, buildInstanceUrl, showToast } from './ui.js';
import { fetchAndRenderInstances } from './main.js';

export function setupMainEventListeners() {
    DOM.addInstanceBtn.addEventListener('click', async () => {
        if (document.querySelector('tr[data-is-new="true"]')) return;
        const noInstancesRow = DOM.instancesTbody.querySelector('.no-instances-row');
        if (noInstancesRow) noInstancesRow.remove();

        let bestGpuId = null;
        try {
            const stats = await api.getSystemStats();
            if (stats && stats.gpus && stats.gpus.length > 0) {
                bestGpuId = stats.gpus.reduce((best, gpu) => {
                    const freeVram = gpu.vram.total - gpu.vram.used;
                    return freeVram > best.maxFreeVram ? { maxFreeVram: freeVram, id: gpu.id } : best;
                }, { maxFreeVram: -1, id: null }).id;
            }
        } catch (error) {
            console.error("Could not fetch system stats for default GPU selection:", error);
        }

        const newInstance = {
            id: 'new',
            autostart: false,
            persistent_mode: false,
            status: 'stopped',
            gpu_ids: bestGpuId !== null ? String(bestGpuId) : ''
        };

        const newRow = renderInstanceRow(newInstance, true);
        DOM.instancesTbody.appendChild(newRow);
        newRow.querySelector('input[data-field="name"]').focus();
    });

    DOM.instancesTbody.addEventListener('change', async (event) => {
        const target = event.target;
        if (target.matches('[data-field="autostart"]')) {
            const row = target.closest('tr');
            const instanceId = row.dataset.id;
            const instanceName = row.dataset.name;
            const isChecked = target.checked;

            try {
                await api.updateInstanceAutostart(instanceId, isChecked);
                showToast(`Autostart for '${instanceName}' updated.`, 'success');
                // Update the original-autostart dataset to prevent unsaved changes warnings
                row.dataset.originalAutostart = String(isChecked);
            } catch (error) {
                showToast(`Error updating autostart: ${error.message}`, 'error');
                // Revert the checkbox on failure
                target.checked = !isChecked;
            }
        }
    });

    DOM.instancesTbody.addEventListener('click', async (event) => {
        const target = event.target.closest('[data-action]');
        if (!target) return;
        if (target.closest('.context-menu')) return;
        if (target.disabled || target.classList.contains('disabled')) return;

        const action = target.dataset.action;
        if (action === 'tools_menu') {
            showToolsMenu(target);
            return;
        }
        hideToolsMenu();

        const row = target.closest('tr');
        const instanceId = row.dataset.id;

        try {
            switch (action) {
                case 'start':
                case 'stop':
                    target.disabled = true;
                    await api.performInstanceAction(instanceId, action);
                    await fetchAndRenderInstances();
                    break;

                case 'save':
                    const portValue = row.querySelector('[data-field="port"]').value;
                    const data = {
                        name: row.querySelector('input[data-field="name"]').value,
                        base_blueprint: row.querySelector('select[data-field="base_blueprint"]').value,
                        output_path: row.querySelector('input[data-field="output_path"]').value || null,
                        gpu_ids: Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(','),
                        autostart: row.querySelector('input[data-field="autostart"]').checked,
                        persistent_mode: row.querySelector('input[data-field="persistent_mode"]').checked,
                        hostname: row.querySelector('input[data-field="hostname"]').value || null,
                        use_custom_hostname: row.querySelector('input[data-field="use_custom_hostname"]').checked,
                        port: portValue ? parseInt(portValue, 10) : null
                    };
                    await api.createInstance(data);
                    showToast(`Instance '${data.name}' created successfully.`);
                    await fetchAndRenderInstances();
                    break;

                case 'update':
                    state.instanceToUpdate = { row, button: target };
                    const changes = {};
                    const fieldMap = {
                        name: 'Name',
                        base_blueprint: 'Blueprint',
                        output_path: 'Output Path',
                        gpu_ids: 'GPU IDs',
                        persistent_mode: 'Persistent UI',
                        use_custom_hostname: 'Use Custom Address',
                        hostname: 'Custom Address'
                    };
    
                    const nameField = row.querySelector('input[data-field="name"]');
                    if (nameField.value !== row.dataset.originalName) {
                        changes.name = { old: row.dataset.originalName, new: nameField.value, label: fieldMap.name };
                    }
                    const blueprintField = row.querySelector('select[data-field="base_blueprint"]');
                    if (blueprintField.value !== row.dataset.originalBlueprint) {
                        changes.base_blueprint = { old: row.dataset.originalBlueprint, new: blueprintField.value, label: fieldMap.base_blueprint };
                    }
                    const outputPathField = row.querySelector('input[data-field="output_path"]');
                    if ((outputPathField.value || '') !== (row.dataset.originalOutputPath || '')) {
                        changes.output_path = { old: row.dataset.originalOutputPath || '', new: outputPathField.value, label: fieldMap.output_path };
                    }
                    const selectedGpuIds = Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(',');
                    if (selectedGpuIds !== row.dataset.originalGpuIds) {
                        changes.gpu_ids = { old: row.dataset.originalGpuIds, new: selectedGpuIds, label: fieldMap.gpu_ids };
                    }
                    const persistentModeField = row.querySelector('input[data-field="persistent_mode"]');
                    if (persistentModeField.checked.toString() !== row.dataset.originalPersistentMode) {
                        changes.persistent_mode = { old: row.dataset.originalPersistentMode === 'true' ? 'true' : 'false', new: persistentModeField.checked ? 'true' : 'false', label: fieldMap.persistent_mode };
                    }
                    const useHostnameField = row.querySelector('input[data-field="use_custom_hostname"]');
                    if (useHostnameField.checked.toString() !== row.dataset.originalUseCustomHostname) {
                        changes.use_custom_hostname = { old: row.dataset.originalUseCustomHostname === 'true' ? 'true' : 'false', new: useHostnameField.checked ? 'true' : 'false', label: fieldMap.use_custom_hostname };
                    }
                    const hostnameField = row.querySelector('input[data-field="hostname"]');
                    if ((hostnameField.value || '') !== (row.dataset.originalHostname || '')) {
                        changes.hostname = { old: row.dataset.originalHostname || '', new: hostnameField.value, label: fieldMap.hostname };
                    }
    
                    const changesContainer = document.getElementById('update-confirm-changes');
                    changesContainer.innerHTML = '';
                    Object.values(changes).forEach(change => {
                        const div = document.createElement('div');
                        div.innerHTML = `<strong>${change.label}:</strong> ${change.old || '""'} &rarr; ${change.new || '""'}`;
                        changesContainer.appendChild(div);
                    });
    
                    const warning = document.getElementById('update-confirm-warning');
                    const title = document.getElementById('update-confirm-title');
                    title.textContent = `Confirm Changes for: ${row.dataset.name}`;
                    if (row.dataset.status !== 'stopped') {
                        warning.textContent = 'This instance is running. Applying these changes will require a restart.';
                    } else {
                        warning.textContent = 'These changes will be applied the next time the instance is started.';
                    }
    
                    const outputPathWarning = document.getElementById('update-output-path-warning');
                    if (changes.output_path) {
                        outputPathWarning.textContent = `Warning: This does not move existing files. The old folder '.../outputs/${changes.output_path.old}' will be preserved.`;
                        outputPathWarning.style.display = 'block';
                    } else {
                        outputPathWarning.style.display = 'none';
                    }
    
                    DOM.updateConfirmModal.classList.remove('hidden');
                    break;

                case 'delete':
                    state.instanceToDeleteId = instanceId;
                    document.getElementById('delete-modal-instance-name').textContent = row.dataset.name;
                    DOM.deleteModal.classList.remove('hidden');
                    break;

                case 'logs':
                    showLogViewer(instanceId, row.dataset.name);
                    break;

                case 'view':
                    const url = buildInstanceUrl(row, true);
                    openInstanceView(row.dataset.name, url);
                    break;

                case 'cancel_new':
                    row.remove();
                    if (DOM.instancesTbody.childElementCount === 0) fetchAndRenderInstances();
                    break;
            }
        } catch (error) {
            showToast(error.message, 'error');
            await fetchAndRenderInstances();
        }
    });

    DOM.toolsContextMenu.addEventListener('click', async (event) => {
        const target = event.target.closest('[data-action]');
        if (!target || target.disabled) return;
        const action = target.dataset.action;
        if (state.currentMenuInstance) {
            const { id, name, status } = state.currentMenuInstance;
            try {
                switch (action) {
                    case 'script':
                        openEditor(id, name, 'script');
                        break;
                    case 'terminal':
                        openTerminal(id, name);
                        break;
                    case 'version-check':
                        showVersionCheckView(id, name);
                        break;
                    case 'rebuild-env':
                        state.instanceToRebuild = state.currentMenuInstance;
                        const message = status !== 'stopped'
                            ? `This will stop and restart the instance '${name}' to rebuild its environment. This can take several minutes.`
                            : `This will rebuild the environment for '${name}' the next time it starts.`;
                        document.getElementById('rebuild-modal-instance-name').textContent = name;
                        document.getElementById('rebuild-modal-message').textContent = message;
                        DOM.rebuildModal.classList.remove('hidden');
                        break;
                    case 'clone':
                        const newCloneName = prompt(`Enter a name for the clone of "${name}":`, `${name}_clone`);
                        if (newCloneName) {
                            await api.cloneInstance(id, newCloneName);
                            showToast(`Instance '${name}' successfully cloned as '${newCloneName}'.`);
                            await fetchAndRenderInstances();
                        }
                        break;
                    case 'instantiate':
                        const newInstanceName = prompt(`Enter a name for the new instance of "${name}":`, `${name}_instance`);
                        if (newInstanceName) {
                            await api.instantiateInstance(id, newInstanceName);
                            showToast(`Instance '${name}' successfully instantiated as '${newInstanceName}'.`);
                            await fetchAndRenderInstances();
                        }
                        break;
                }
            } catch (error) {
                showToast(error.message, 'error');
            }
        }
        hideToolsMenu();
    });

    DOM.editorUpdateBtn.addEventListener('click', () => {
        const { instanceId } = state.editorState;
        if (!instanceId) return;

        const row = DOM.instancesTbody.querySelector(`tr[data-id="${instanceId}"]`);
        if (!row) {
            showToast('Could not find instance data. Please refresh.', 'error');
            return;
        }
        const status = row.dataset.status;
        const instanceName = row.dataset.name;

        if (status !== 'stopped') {
            document.getElementById('restart-modal-instance-name').textContent = instanceName;
            DOM.restartConfirmModal.classList.remove('hidden');
        } else {
            // The actual update is handled in the modal's event handler,
            // but we can trigger it directly if the instance is stopped.
            const { fileType } = state.editorState;
            const content = state.codeEditor.getValue();
            
            DOM.editorUpdateBtn.textContent = 'Updating...';
            DOM.editorUpdateBtn.disabled = true;
            api.updateInstanceScript(instanceId, fileType, content, false)
                .then(() => {
                    showToast('Instance script updated successfully.', 'success');
                })
                .catch(error => {
                    showToast(`Error updating script: ${error.message}`, 'error');
                })
                .finally(() => {
                    DOM.editorUpdateBtn.textContent = 'Update Instance';
                    DOM.editorUpdateBtn.disabled = false;
                });
        }
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.context-menu') && !event.target.closest('[data-action="tools_menu"]')) {
            hideToolsMenu();
        }
    });
}
