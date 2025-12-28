import { state, DOM } from './state.js';
    import * as api from './api.js';
    import { showToolsMenu, hideToolsMenu } from './modals.js';
    import { openEditor, openTerminal, showVersionCheckView, openInstanceView, showLogViewer } from './tools.js';
    import { renderInstanceRow, buildInstanceUrl, showToast } from './ui.js';
    import { fetchAndRenderInstances } from './main.js';
    
    export function setupMainEventListeners() {
        const globalSaveBtn = document.getElementById('global-save-btn');
        
        DOM.addInstanceBtn.addEventListener('click', async () => {
            if (document.querySelector('tr[data-is-new="true"]')) return;
            
            // Find and remove empty row if present
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
            
            // Create a new tbody specifically for this new row
            const newTbody = document.createElement('tbody');
            newTbody.classList.add('instance-group');
            newTbody.dataset.groupId = 'new';
            newTbody.appendChild(newRow);
            
            // Append at the bottom as requested to match final instance placement
            DOM.instancesTable.appendChild(newTbody);
            
            // Scroll the row into view so the user sees it immediately
            newRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            
            newRow.querySelector('input[data-field="name"]').focus();
        });
    
        // GLOBAL SAVE LISTENER
        if (globalSaveBtn) {
            globalSaveBtn.addEventListener('click', () => {
                const dirtyRows = document.querySelectorAll('tr.row-dirty');
                if (dirtyRows.length === 0) return;
    
                state.pendingUpdates = []; // Store all pending updates
                const changesContainer = document.getElementById('update-confirm-changes');
                changesContainer.innerHTML = '';
    
                let requiresRestart = false;
                let hasOutputPathChange = false;
    
                dirtyRows.forEach(row => {
                    const instanceName = row.dataset.originalName || 'Unknown';
                    const instanceId = row.dataset.id;
                    const status = row.dataset.status;
                    
                    const changes = {};
                    const fieldMap = {
                        name: 'Name',
                        base_blueprint: 'Blueprint',
                        output_path: 'Output Path',
                        gpu_ids: 'GPU IDs',
                        persistent_mode: 'Persistent UI',
                        use_custom_hostname: 'Use Custom Address',
                        hostname: 'Custom Address',
                        port: 'Port',
                        autostart: 'Autostart'
                    };
    
                    const nameField = row.querySelector('input[data-field="name"]');
                    if (nameField.value !== row.dataset.originalName) {
                        changes.name = { old: row.dataset.originalName, new: nameField.value };
                    }
                    const blueprintField = row.querySelector('select[data-field="base_blueprint"]');
                    if (blueprintField && !blueprintField.disabled && blueprintField.value !== row.dataset.originalBlueprint) {
                        changes.base_blueprint = { old: row.dataset.originalBlueprint, new: blueprintField.value };
                    }
                    const outputPathField = row.querySelector('input[data-field="output_path"]');
                    if (outputPathField && !outputPathField.disabled && (outputPathField.value || '') !== (row.dataset.originalOutputPath || '')) {
                        changes.output_path = { old: row.dataset.originalOutputPath || '', new: outputPathField.value };
                        hasOutputPathChange = true;
                    }
                    const selectedGpuIds = Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(',');
                    if (selectedGpuIds !== row.dataset.originalGpuIds) {
                        changes.gpu_ids = { old: row.dataset.originalGpuIds, new: selectedGpuIds };
                    }
                    const persistentModeField = row.querySelector('input[data-field="persistent_mode"]');
                    if (persistentModeField && persistentModeField.checked.toString() !== row.dataset.originalPersistentMode) {
                        changes.persistent_mode = { old: row.dataset.originalPersistentMode, new: persistentModeField.checked ? 'true' : 'false' };
                    }
                    const useHostnameField = row.querySelector('input[data-field="use_custom_hostname"]');
                    if (useHostnameField && useHostnameField.checked.toString() !== row.dataset.originalUseCustomHostname) {
                        changes.use_custom_hostname = { old: row.dataset.originalUseCustomHostname, new: useHostnameField.checked ? 'true' : 'false' };
                    }
                    const hostnameField = row.querySelector('input[data-field="hostname"]');
                    if (hostnameField && (hostnameField.value || '') !== (row.dataset.originalHostname || '')) {
                        changes.hostname = { old: row.dataset.originalHostname || '', new: hostnameField.value };
                    }
                    const portField = row.querySelector('select[data-field="port"]');
                    if (portField && portField.value !== (row.dataset.originalPort || '')) {
                        changes.port = { old: row.dataset.originalPort || 'Auto', new: portField.value || 'Auto' };
                    }
                    const autostartField = row.querySelector('input[data-field="autostart"]');
                    if (autostartField && autostartField.checked.toString() !== row.dataset.originalAutostart) {
                        changes.autostart = { old: row.dataset.originalAutostart, new: autostartField.checked ? 'true' : 'false' };
                    }
    
                    // Store for execution
                    if (Object.keys(changes).length > 0) {
                        state.pendingUpdates.push({
                            id: instanceId,
                            row: row,
                            changes: changes
                        });
    
                        // Visual list
                        Object.keys(changes).forEach(key => {
                            const div = document.createElement('div');
                            div.innerHTML = `<strong>[${instanceName}] ${fieldMap[key]}:</strong> ${changes[key].old} &rarr; ${changes[key].new}`;
                            changesContainer.appendChild(div);
                        });
    
                        // Check if restart is needed (if running and changed something critical)
                        if (status !== 'stopped') {
                            // Autostart change doesn't need restart. Others do.
                            const criticalChanges = ['name', 'base_blueprint', 'output_path', 'gpu_ids', 'persistent_mode', 'port'];
                            const hasCritical = Object.keys(changes).some(k => criticalChanges.includes(k));
                            if (hasCritical) requiresRestart = true;
                        }
                    }
                });
    
                const restartWarning = document.getElementById('update-restart-warning');
                restartWarning.style.display = requiresRestart ? 'block' : 'none';
    
                const outputPathWarning = document.getElementById('update-output-path-warning');
                if (hasOutputPathChange) {
                    outputPathWarning.textContent = `Warning: Changing Output Path does not move existing files.`;
                    outputPathWarning.style.display = 'block';
                } else {
                    outputPathWarning.style.display = 'none';
                }
    
                DOM.updateConfirmModal.classList.remove('hidden');
            });
        }
    
        // Handle confirm click for global update
        document.getElementById('update-confirm-btn-confirm').addEventListener('click', async () => {
            DOM.updateConfirmModal.classList.add('hidden');
            const updates = state.pendingUpdates || [];
            
            let successCount = 0;
            let errorCount = 0;
    
            for (const update of updates) {
                try {
                    // Prepare API Payload
                    const row = update.row;
                    // Important: Use null/inherited values if disabled
                    const bpSelect = row.querySelector('select[data-field="base_blueprint"]');
                    const outPathInput = row.querySelector('input[data-field="output_path"]');
    
                    const data = {
                        name: row.querySelector('input[data-field="name"]').value,
                        base_blueprint: bpSelect.disabled ? undefined : bpSelect.value, // Don't send if disabled
                        output_path: outPathInput.disabled ? undefined : (outPathInput.value || null),
                        gpu_ids: Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(','),
                        autostart: row.querySelector('input[data-field="autostart"]').checked,
                        persistent_mode: row.querySelector('input[data-field="persistent_mode"]').checked,
                        hostname: row.querySelector('input[data-field="hostname"]').value || null,
                        use_custom_hostname: row.querySelector('input[data-field="use_custom_hostname"]').checked,
                        port: row.querySelector('select[data-field="port"]').value ? parseInt(row.querySelector('select[data-field="port"]').value, 10) : null
                    };
    
                    await api.updateInstance(update.id, data);
                    row.classList.remove('row-dirty'); // Clear dirty status on success
                    successCount++;
                } catch (err) {
                    console.error(`Failed to update instance ${update.id}:`, err);
                    errorCount++;
                    showToast(`Failed to update instance ${update.id}: ${err.message}`, 'error');
                }
            }
    
            if (successCount > 0) showToast(`${successCount} instance(s) updated successfully.`);
            if (errorCount > 0) showToast(`${errorCount} update(s) failed.`, 'error');
            
            document.getElementById('global-save-btn').style.display = 'none'; // Hide button if all success (or refresh will handle it)
            await fetchAndRenderInstances();
        });
    
        document.getElementById('update-confirm-btn-cancel').addEventListener('click', () => {
            DOM.updateConfirmModal.classList.add('hidden');
        });
    
        // CHANGED: Listen on Table, not tbody
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
                        // Remove the temporary tbody and row
                        row.closest('tbody').remove();
                        await fetchAndRenderInstances();
                        break;
    
                    // 'update' case removed as per requirements
    
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
                        row.closest('tbody').remove();
                        // Check if table is empty (only thead remains)
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
    
            const row = DOM.instancesTable.querySelector(`tr[data-id="${instanceId}"]`);
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