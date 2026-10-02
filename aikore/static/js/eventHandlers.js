import { state, DOM } from './state.js';
import * as api from './api.js';
import { showToolsMenu, hideToolsMenu, openDeleteModal, openRebuildModal, openRestartConfirmModal, openSaveBlueprintModal, openUpdateConfirmModal } from './modals.js';
import { openEditor, openTerminal, showVersionCheckView, openInstanceView, showLogViewer, showInstanceWheelsManager } from './tools.js';
import { renderInstanceRow, buildInstanceUrl, showToast, resolveGpuIds, setButtonLabel } from './ui.js';
import { fetchAndRenderInstances } from './main.js';

export function setupMainEventListeners() {
    const globalSaveBtn = document.getElementById('global-save-btn');
    
    DOM.addInstanceBtn.addEventListener('click', async () => {
        if (document.querySelector('tr[data-is-new="true"]')) return;
        
        const noInstancesRow = DOM.instancesTable.querySelector('.no-instances-row');
        if (noInstancesRow) noInstancesRow.closest('tbody').remove();

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
        
        const newTbody = document.createElement('tbody');
        newTbody.classList.add('instance-group');
        newTbody.dataset.groupId = 'new';
        newTbody.appendChild(newRow);
        
        DOM.instancesTable.appendChild(newTbody);
        
        newRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        
        newRow.querySelector('input[data-field="name"]').focus();
    });

    if (globalSaveBtn) {
        globalSaveBtn.addEventListener('click', () => {
            const dirtyRows = document.querySelectorAll('tr.row-dirty');
            if (dirtyRows.length === 0) return;

            state.pendingUpdates =[];
            const changes = [];

            let requiresRestart = false;
            let hasOutputPathChange = false;

            dirtyRows.forEach(row => {
                const instanceName = row.dataset.originalName || 'Unknown';
                const instanceId = row.dataset.id;
                const status = row.dataset.status;
                
                const rowChanges = {};
                const fieldMap = {
                    name: 'Name',
                    base_blueprint: 'Blueprint',
                    output_path: 'Output Path',
                    gpu_ids: 'GPU IDs',
                    persistent_mode: 'Persistent UI',
                    use_custom_hostname: 'Use Custom Address',
                    hostname: 'Custom Address',
                    port: 'Port',
                    autostart: 'Autostart',
                    python_version: 'Python Ver.',
                    cuda_version: 'CUDA Ver.',
                    torch_version: 'Torch Ver.'
                };

                const nameField = row.querySelector('input[data-field="name"]');
                if (nameField.value !== row.dataset.originalName) {
                    rowChanges.name = { old: row.dataset.originalName, new: nameField.value };
                }
                const blueprintField = row.querySelector('[data-field="base_blueprint"]');
                if (blueprintField && !blueprintField.disabled && blueprintField.value !== row.dataset.originalBlueprint) {
                    rowChanges.base_blueprint = { old: row.dataset.originalBlueprint, new: blueprintField.value };
                }
                const outputPathField = row.querySelector('input[data-field="output_path"]');
                if (outputPathField && !outputPathField.disabled && (outputPathField.value || '') !== (row.dataset.originalOutputPath || '')) {
                    rowChanges.output_path = { old: row.dataset.originalOutputPath || '', new: outputPathField.value };
                    hasOutputPathChange = true;
                }
                const selectedGpuIds = resolveGpuIds(row);
                if (selectedGpuIds !== row.dataset.originalGpuIds) {
                    rowChanges.gpu_ids = { old: row.dataset.originalGpuIds, new: selectedGpuIds };
                }
                const persistentModeField = row.querySelector('input[data-field="persistent_mode"]');
                if (persistentModeField && persistentModeField.checked.toString() !== row.dataset.originalPersistentMode) {
                    rowChanges.persistent_mode = { old: row.dataset.originalPersistentMode, new: persistentModeField.checked ? 'true' : 'false' };
                }
                const useHostnameField = row.querySelector('input[data-field="use_custom_hostname"]');
                if (useHostnameField && useHostnameField.checked.toString() !== row.dataset.originalUseCustomHostname) {
                    rowChanges.use_custom_hostname = { old: row.dataset.originalUseCustomHostname, new: useHostnameField.checked ? 'true' : 'false' };
                }
                const hostnameField = row.querySelector('input[data-field="hostname"]');
                if (hostnameField && (hostnameField.value || '') !== (row.dataset.originalHostname || '')) {
                    rowChanges.hostname = { old: row.dataset.originalHostname || '', new: hostnameField.value };
                }
                const portField = row.querySelector('select[data-field="port"]');
                if (portField && portField.value !== (row.dataset.originalPort || '')) {
                    rowChanges.port = { old: row.dataset.originalPort || 'Auto', new: portField.value || 'Auto' };
                }
                const autostartField = row.querySelector('input[data-field="autostart"]');
                if (autostartField && autostartField.checked.toString() !== row.dataset.originalAutostart) {
                    rowChanges.autostart = { old: row.dataset.originalAutostart, new: autostartField.checked ? 'true' : 'false' };
                }
                
                const pyField = row.querySelector('select[data-field="python_version"]');
                if (pyField && !pyField.disabled && (pyField.value || '') !== (row.dataset.originalPythonVersion || '')) {
                    rowChanges.python_version = { old: row.dataset.originalPythonVersion || 'Auto', new: pyField.value || 'Auto' };
                }
                const cudaField = row.querySelector('select[data-field="cuda_version"]');
                if (cudaField && !cudaField.disabled && (cudaField.value || '') !== (row.dataset.originalCudaVersion || '')) {
                    rowChanges.cuda_version = { old: row.dataset.originalCudaVersion || 'Auto', new: cudaField.value || 'Auto' };
                }
                const torchField = row.querySelector('select[data-field="torch_version"]');
                if (torchField && !torchField.disabled && (torchField.value || '') !== (row.dataset.originalTorchVersion || '')) {
                    rowChanges.torch_version = { old: row.dataset.originalTorchVersion || 'Auto', new: torchField.value || 'Auto' };
                }

                if (Object.keys(rowChanges).length > 0) {
                    state.pendingUpdates.push({
                        id: instanceId,
                        row: row,
                        changes: rowChanges
                    });

                    Object.keys(rowChanges).forEach(key => {
                        changes.push(`[${instanceName}] ${fieldMap[key]}: ${rowChanges[key].old} → ${rowChanges[key].new}`);
                    });

                    if (status !== 'stopped') {
                        const criticalChanges =[
                            'name', 'base_blueprint', 'output_path', 'gpu_ids', 
                            'persistent_mode', 'port', 'python_version', 'cuda_version', 'torch_version'
                        ];
                        const hasCritical = Object.keys(rowChanges).some(k => criticalChanges.includes(k));
                        if (hasCritical) requiresRestart = true;
                    }
                }
            });

            openUpdateConfirmModal(changes, async () => {
                const updates = state.pendingUpdates ||[];
                let successCount = 0;
                let errorCount = 0;

                for (const update of updates) {
                    try {
                        const row = update.row;
                        const bpSelect = row.querySelector('[data-field="base_blueprint"]');
                        const outPathInput = row.querySelector('input[data-field="output_path"]');
                        const pyField = row.querySelector('select[data-field="python_version"]');
                        const cudaField = row.querySelector('select[data-field="cuda_version"]');
                        const torchField = row.querySelector('select[data-field="torch_version"]');

                        const data = {
                            name: row.querySelector('input[data-field="name"]').value,
                            base_blueprint: bpSelect.disabled ? undefined : bpSelect.value,
                            output_path: outPathInput.disabled ? undefined : (outPathInput.value || null),
                            gpu_ids: resolveGpuIds(row),
                            autostart: row.querySelector('input[data-field="autostart"]').checked,
                            persistent_mode: row.querySelector('input[data-field="persistent_mode"]').checked,
                            hostname: row.querySelector('input[data-field="hostname"]').value || null,
                            use_custom_hostname: row.querySelector('input[data-field="use_custom_hostname"]').checked,
                            port: row.querySelector('select[data-field="port"]').value ? parseInt(row.querySelector('select[data-field="port"]').value, 10) : null,
                            python_version: (pyField && !pyField.disabled) ? (pyField.value || null) : undefined,
                            cuda_version: (cudaField && !cudaField.disabled) ? (cudaField.value || null) : undefined,
                            torch_version: (torchField && !torchField.disabled) ? (torchField.value || null) : undefined,
                        };

                        await api.updateInstance(update.id, data);
                        row.classList.remove('row-dirty');
                        successCount++;
                    } catch (err) {
                        console.error(`Failed to update instance ${update.id}:`, err);
                        errorCount++;
                        showToast(`Failed to update instance ${update.id}: ${err.message}`, 'error');
                    }
                }

                if (successCount > 0) showToast(`${successCount} instance(s) updated successfully.`);
                if (errorCount > 0) showToast(`${errorCount} update(s) failed.`, 'error');
                
                document.getElementById('global-save-btn').style.display = 'none';
                await fetchAndRenderInstances();
            });
        });
    }

    DOM.instancesTable.addEventListener('click', async (event) => {
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
                    const portValue = row.querySelector('select[data-field="port"]').value;
                    const data = {
                        name: row.querySelector('input[data-field="name"]').value,
                        base_blueprint: row.querySelector('[data-field="base_blueprint"]').value,
                        output_path: row.querySelector('input[data-field="output_path"]').value || null,
                        gpu_ids: resolveGpuIds(row),
                        autostart: row.querySelector('input[data-field="autostart"]').checked,
                        persistent_mode: row.querySelector('input[data-field="persistent_mode"]').checked,
                        hostname: row.querySelector('input[data-field="hostname"]').value || null,
                        use_custom_hostname: row.querySelector('input[data-field="use_custom_hostname"]').checked,
                        port: portValue ? parseInt(portValue, 10) : null,
                        // --- NEW: Env variables ---
                        python_version: row.querySelector('select[data-field="python_version"]').value || null,
                        cuda_version: row.querySelector('select[data-field="cuda_version"]').value || null,
                        torch_version: row.querySelector('select[data-field="torch_version"]').value || null,
                    };
                    await api.createInstance(data);
                    showToast(`Instance '${data.name}' created successfully.`);
                    row.closest('tbody').remove();
                    await fetchAndRenderInstances();
                    break;

                case 'delete':
                    openDeleteModal(instanceId, row.dataset.name);
                    break;

                case 'logs':
                    showLogViewer(instanceId, row.dataset.name);
                    break;

                case 'view':
                    const url = buildInstanceUrl(row, true);
                    openInstanceView(row.dataset.name, url);
                    break;

                case 'cancel_new':
                    row.closest('tbody').remove();
                    if (DOM.instancesTable.querySelectorAll('tbody').length === 0) fetchAndRenderInstances();
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
                    case 'manage-wheels':
                        showInstanceWheelsManager(id, name);
                        break;
                    case 'rebuild-env':
                        openRebuildModal(state.currentMenuInstance);
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

    DOM.editorSaveCustomBtn.addEventListener('click', () => {
        const { instanceId, instanceName, fileType, baseBlueprint } = state.editorState;
        if (!instanceId) {
            showToast('No file is currently being edited.', 'error');
            return;
        }
        openSaveBlueprintModal();
    });

    DOM.editorUpdateBtn.addEventListener('click', () => {
        const { instanceId } = state.editorState;
        if (!instanceId) return;

        const row = DOM.instancesTable.querySelector(`tr[data-id="${instanceId}"]`);
        if (!row) {
            showToast('Could not find instance data. Please refresh.', 'error');
            return;
        }
        const status = row.dataset.status;
        const instanceName = row.dataset.name;

        if (status !== 'stopped') {
            openRestartConfirmModal(instanceName);
        } else {
            const { fileType } = state.editorState;
            const content = state.codeEditor.getValue();
            
            setButtonLabel(DOM.editorUpdateBtn, 'Updating...');
            DOM.editorUpdateBtn.disabled = true;
            api.updateInstanceScript(instanceId, fileType, content, false)
                .then(() => {
                    showToast('Instance script updated successfully.', 'success');
                })
                .catch(error => {
                    showToast(`Error updating script: ${error.message}`, 'error');
                })
                .finally(() => {
                    setButtonLabel(DOM.editorUpdateBtn, 'Update Instance', 'refresh');
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