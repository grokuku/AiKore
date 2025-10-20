document.addEventListener('DOMContentLoaded', () => {
    const instancesTbody = document.getElementById('instances-tbody');
    const addInstanceBtn = document.querySelector('.add-new-btn');
    let availableBlueprints = []; // Store blueprints globally

    // Tools/Logs/Editor pane elements
    const toolsPaneTitle = document.getElementById('tools-pane-title');
    const logViewerContainer = document.getElementById('log-viewer-container');
    const toolsPaneContent = document.getElementById('tools-pane-content'); // This is the <code> in the log viewer
    const editorContainer = document.getElementById('editor-container');
    const fileEditorTextarea = document.getElementById('file-editor-textarea');
    const editorSaveBtn = document.getElementById('editor-save-btn');
    const editorExitBtn = document.getElementById('editor-exit-btn');

    // State for live logs
    let activeLogInstanceId = null;
    let activeLogInterval = null;
    let logSize = 0; // Single size tracker for the unified log file

    // State for editor
    let editorState = {
        instanceId: null,
        instanceName: null,
        fileType: null, // 'script'
    };

    // --- Helper function to fetch blueprints and populate the global array ---
    async function fetchAndStoreBlueprints() {
        try {
            const response = await fetch('/api/system/blueprints');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            availableBlueprints = data.blueprints;
        } catch (error) {
            console.error("Failed to fetch blueprints:", error);
            availableBlueprints = ["Error loading blueprints"];
        }
    }

    // --- Helper function to create a blueprint select element ---
    function createBlueprintSelect(selectedValue = '') {
        const select = document.createElement('select');
        select.dataset.field = 'base_blueprint';
        select.required = true;
        
        if (availableBlueprints.length === 0) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = 'Loading blueprints...';
            option.disabled = true;
            option.selected = true;
            select.appendChild(option);
        } else {
            const defaultOption = document.createElement('option');
            defaultOption.value = '';
            defaultOption.textContent = 'Select a blueprint';
            defaultOption.disabled = true;
            defaultOption.selected = true;
            select.appendChild(defaultOption);

            availableBlueprints.forEach(bp => {
                const option = document.createElement('option');
                option.value = bp;
                option.textContent = bp;
                if (bp === selectedValue) {
                    option.selected = true;
                    defaultOption.selected = false;
                }
                select.appendChild(option);
            });
        }
        return select;
    }

    /**
     * Renders a single instance row in the table.
     * @param {object} instance - The instance data.
     * @param {boolean} isNew - True if it's a newly added row not yet saved to DB.
     */
    function renderInstanceRow(instance, isNew = false) {
        const row = document.createElement('tr');
        row.dataset.id = instance.id;
        row.dataset.isNew = isNew;

        const statusClass = `status status-${instance.status.toLowerCase()}`;
        const isRunning = instance.status === 'running';
        const isStarting = instance.status === 'starting';

        row.dataset.originalName = instance.name;
        row.dataset.originalBlueprint = instance.base_blueprint;
        row.dataset.originalGpuIds = instance.gpu_ids || '';
        row.dataset.originalAutostart = instance.autostart;
        row.dataset.originalPersistentMode = instance.persistent_mode;

        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.value = instance.name;
        nameInput.dataset.field = 'name';
        nameInput.required = true;
        nameInput.disabled = !isNew;
        row.insertCell().appendChild(nameInput);

        const blueprintSelect = createBlueprintSelect(instance.base_blueprint);
        blueprintSelect.disabled = !isNew;
        row.insertCell().appendChild(blueprintSelect);

        const gpuInput = document.createElement('input');
        gpuInput.type = 'text';
        gpuInput.value = instance.gpu_ids || '';
        gpuInput.dataset.field = 'gpu_ids';
        row.insertCell().appendChild(gpuInput);

        const autostartCheckbox = document.createElement('input');
        autostartCheckbox.type = 'checkbox';
        autostartCheckbox.checked = instance.autostart;
        autostartCheckbox.dataset.field = 'autostart';
        row.insertCell().appendChild(autostartCheckbox);

        const persistentModeCheckbox = document.createElement('input');
        persistentModeCheckbox.type = 'checkbox';
        persistentModeCheckbox.checked = instance.persistent_mode;
        persistentModeCheckbox.dataset.field = 'persistent_mode';
        row.insertCell().appendChild(persistentModeCheckbox);

        row.insertCell().innerHTML = `<span class="${statusClass}">${instance.status}</span>`;
        row.insertCell().textContent = instance.port || 'N/A';

        // --- Unified Actions Cell ---
        const actionsCell = row.insertCell();
        actionsCell.classList.add('actions-column');

        const startButton = document.createElement('button');
        startButton.classList.add('action-btn');
        startButton.dataset.action = 'start';
        startButton.dataset.id = instance.id;
        startButton.textContent = 'Start';
        startButton.disabled = isRunning || isStarting || isNew;
        actionsCell.appendChild(startButton);

        const stopButton = document.createElement('button');
        stopButton.classList.add('action-btn');
        stopButton.dataset.action = 'stop';
        stopButton.dataset.id = instance.id;
        stopButton.textContent = 'Stop';
        stopButton.disabled = !isRunning || isNew;
        actionsCell.appendChild(stopButton);

        const logsButton = document.createElement('button');
        logsButton.classList.add('action-btn');
        logsButton.dataset.action = 'logs';
        logsButton.dataset.id = instance.id;
        logsButton.dataset.name = instance.name;
        logsButton.textContent = 'Logs';
        logsButton.disabled = isNew;
        actionsCell.appendChild(logsButton);

        const scriptButton = document.createElement('button');
        scriptButton.classList.add('action-btn');
        scriptButton.dataset.action = 'script';
        scriptButton.dataset.id = instance.id;
        scriptButton.dataset.name = instance.name;
        scriptButton.textContent = 'Script';
        scriptButton.disabled = isNew || isRunning || isStarting;
        actionsCell.appendChild(scriptButton);

        const saveUpdateButton = document.createElement('button');
        saveUpdateButton.classList.add('action-btn');
        saveUpdateButton.dataset.id = instance.id;
        if (isNew) {
            saveUpdateButton.dataset.action = 'save';
            saveUpdateButton.textContent = 'Save';
            saveUpdateButton.disabled = !nameInput.value || blueprintSelect.value === '';
        } else {
            saveUpdateButton.dataset.action = 'update';
            saveUpdateButton.textContent = 'Update';
            saveUpdateButton.disabled = true;
        }
        actionsCell.appendChild(saveUpdateButton);

        const deleteButton = document.createElement('button');
        deleteButton.classList.add('action-btn');
        deleteButton.dataset.action = 'delete';
        deleteButton.dataset.id = instance.id;
        deleteButton.textContent = 'Delete';
        deleteButton.disabled = isRunning || isStarting;
        actionsCell.appendChild(deleteButton);
        
        const openButton = document.createElement('a');
        openButton.classList.add('action-btn');
        openButton.dataset.action = 'open';
        openButton.dataset.id = instance.id;
        openButton.textContent = 'Open';
        if (isRunning) {
            openButton.href = `/app/${instance.name}/`;
            openButton.target = '_blank';
            openButton.disabled = false;
        } else {
            openButton.href = '#';
            openButton.disabled = true;
            openButton.style.pointerEvents = 'none';
        }
        actionsCell.appendChild(openButton);

        if (!isNew) {
            const editableFields = row.querySelectorAll('input[type="text"], select, input[type="checkbox"]');
            editableFields.forEach(field => {
                field.addEventListener('input', () => checkRowForChanges(row));
            });
        } else {
            nameInput.addEventListener('input', () => {
                saveUpdateButton.disabled = !nameInput.value || blueprintSelect.value === '';
            });
            blueprintSelect.addEventListener('change', () => {
                saveUpdateButton.disabled = !nameInput.value || blueprintSelect.value === '';
            });
        }

        return row;
    }

    function checkRowForChanges(row) {
        const nameField = row.querySelector('input[data-field="name"]');
        const blueprintField = row.querySelector('select[data-field="base_blueprint"]');
        const gpuIdsField = row.querySelector('input[data-field="gpu_ids"]');
        const autostartField = row.querySelector('input[data-field="autostart"]');
        const persistentModeField = row.querySelector('input[data-field="persistent_mode"]');
        const updateButton = row.querySelector('button[data-action="update"]');

        let changed = false;
        if (nameField.value !== row.dataset.originalName) changed = true;
        if (blueprintField.value !== row.dataset.originalBlueprint) changed = true;
        if (gpuIdsField.value !== row.dataset.originalGpuIds) changed = true;
        if (autostartField.checked.toString() !== row.dataset.originalAutostart) changed = true;
        if (persistentModeField.checked.toString() !== row.dataset.originalPersistentMode) changed = true;

        updateButton.disabled = !changed;
    }

    async function fetchAndRenderInstances() {
        try {
            const response = await fetch('/api/instances/');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const instances = await response.json();

            instancesTbody.innerHTML = '';

            if (instances.length === 0) {
                instancesTbody.innerHTML = `<tr><td colspan="8" style="text-align: center;">No instances created yet.</td></tr>`;
            } else {
                instances.forEach(instance => {
                    const row = renderInstanceRow(instance, false);
                    instancesTbody.appendChild(row);
                });
            }
        } catch (error) {
            console.error("Failed to fetch instances:", error);
            instancesTbody.innerHTML = `<tr><td colspan="8">Error loading data. Check console.</td></tr>`;
        }
    }

    function addNewInstanceRow() {
        const newInstance = {
            id: 'new', name: '', base_blueprint: '', gpu_ids: '',
            autostart: false, persistent_mode: false, status: 'stopped',
            pid: null, port: null
        };
        const newRow = renderInstanceRow(newInstance, true);
        instancesTbody.appendChild(newRow);

        newRow.querySelector('input[data-field="name"]').focus();
        newRow.querySelector('input[data-field="name"]').disabled = false;
        newRow.querySelector('select[data-field="base_blueprint"]').disabled = false;
    }

    addInstanceBtn.addEventListener('click', addNewInstanceRow);

    // --- Editor Functions ---
    function exitEditor() {
        editorContainer.classList.add('hidden');
        logViewerContainer.classList.remove('hidden');
        toolsPaneTitle.textContent = 'Tools / Logs';
        fileEditorTextarea.value = '';
        editorState.instanceId = null;
        editorState.instanceName = null;
        editorState.fileType = null;
    }

    async function openEditor(instanceId, instanceName, fileType) {
        clearInterval(activeLogInterval);
        activeLogInstanceId = null;

        logViewerContainer.classList.add('hidden');
        editorContainer.classList.remove('hidden');

        const fileTypeName = fileType.charAt(0).toUpperCase() + fileType.slice(1);
        toolsPaneTitle.textContent = `Editing ${fileTypeName} for: ${instanceName}`;
        fileEditorTextarea.value = `Loading ${fileType} content...`;

        editorState = { instanceId, instanceName, fileType };

        try {
            const response = await fetch(`/api/instances/${instanceId}/file?file_type=${fileType}`);
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to load file.');
            }
            const data = await response.json();
            fileEditorTextarea.value = data.content;
        } catch (error) {
            console.error(`Error loading file content:`, error);
            fileEditorTextarea.value = `[ERROR] Could not load file: ${error.message}`;
        }
    }

    async function saveFileContent() {
        if (!editorState.instanceId || !editorState.fileType) return;

        const content = fileEditorTextarea.value;
        editorSaveBtn.textContent = 'Saving...';
        editorSaveBtn.disabled = true;

        try {
            const response = await fetch(`/api/instances/${editorState.instanceId}/file?file_type=${editorState.fileType}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: content })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to save file.');
            }
            
            // On success, briefly show confirmation
            editorSaveBtn.textContent = 'Saved!';
            setTimeout(() => {
                editorSaveBtn.textContent = 'Save';
                editorSaveBtn.disabled = false;
            }, 1500);

        } catch (error) {
            console.error(`Error saving file content:`, error);
            alert(`Error saving file: ${error.message}`);
            editorSaveBtn.textContent = 'Save';
            editorSaveBtn.disabled = false;
        }
    }

    editorSaveBtn.addEventListener('click', saveFileContent);
    editorExitBtn.addEventListener('click', exitEditor);

    // --- Main Event Listener for Instance Actions ---
    instancesTbody.addEventListener('click', async (event) => {
        const target = event.target.closest('.action-btn');
        if (!target) return;

        const instanceId = target.dataset.id;
        const action = target.dataset.action;
        const row = target.closest('tr');

        if (action === 'start' || action === 'stop') {
            exitEditor(); // Ensure editor is closed before starting/stopping
            try {
                const response = await fetch(`/api/instances/${instanceId}/${action}`, { method: 'POST' });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || `Failed to ${action} instance.`);
                }
                fetchAndRenderInstances();
            } catch (error) {
                console.error(`Error ${action}ing instance:`, error);
                alert(`Error: ${error.message}`);
            }
        } else if (action === 'save') {
            exitEditor();
            const name = row.querySelector('input[data-field="name"]').value;
            const base_blueprint = row.querySelector('select[data-field="base_blueprint"]').value;
            const gpu_ids = row.querySelector('input[data-field="gpu_ids"]').value || null;
            const autostart = row.querySelector('input[data-field="autostart"]').checked;
            const persistent_mode = row.querySelector('input[data-field="persistent_mode"]').checked;

            if (!name || !base_blueprint) {
                alert('Instance Name and Base Blueprint are required.');
                return;
            }

            const data = { name, base_blueprint, gpu_ids, autostart, persistent_mode };

            try {
                const response = await fetch('/api/instances/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data),
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Failed to create instance.');
                }
                fetchAndRenderInstances();
            } catch (error) {
                console.error('Error creating instance:', error);
                alert(`Error: ${error.message}`);
            }

        } else if (action === 'update') {
            alert('Update functionality coming soon!');
        } else if (action === 'delete') {
            if (activeLogInstanceId === instanceId) {
                clearInterval(activeLogInterval);
                activeLogInstanceId = null;
            }
            exitEditor(); // Close editor if it was for this instance
            if (!confirm('Are you sure you want to delete this instance?')) return;
            try {
                const response = await fetch(`/api/instances/${instanceId}`, { method: 'DELETE' });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Failed to delete instance.');
                }
                fetchAndRenderInstances();
            } catch (error) {
                console.error('Error deleting instance:', error);
                alert(`Error: ${error.message}`);
            }
        } else if (action === 'logs') {
            exitEditor(); // Close editor before showing logs
            const instanceName = target.dataset.name;
            
            clearInterval(activeLogInterval);
            activeLogInstanceId = instanceId;
            logSize = 0; // Reset log size

            toolsPaneTitle.textContent = `Logs: ${instanceName}`;
            toolsPaneContent.textContent = 'Loading logs...';

            const errorKeywords = /(warning|warn|error|traceback|exception|failed)/i;

            const fetchLogs = async () => {
                if (!activeLogInstanceId) return;

                try {
                    const url = `/api/instances/${activeLogInstanceId}/logs?offset=${logSize}`;
                    const response = await fetch(url);
                    
                    if (!response.ok) throw new Error('Instance stopped or logs unavailable.');
                    
                    const data = await response.json();

                    const selection = window.getSelection();
                    const hasSelectionInLogs = selection.toString().length > 0 && toolsPaneContent.contains(selection.anchorNode);
                    if (hasSelectionInLogs) return;

                    const isScrolledToBottom = logViewerContainer.scrollHeight - logViewerContainer.scrollTop <= logViewerContainer.clientHeight + 2;
                    
                    if (data.content) {
                        if (toolsPaneContent.textContent === 'Loading logs...') {
                            toolsPaneContent.textContent = '';
                        }

                        const lines = data.content.split('\n');
                        lines.forEach((line, index) => {
                            if (index === lines.length - 1 && line === '') return;
                            
                            const lineContent = line + (index < lines.length - 1 ? '\n' : '');

                            if (errorKeywords.test(lineContent)) {
                                const errorSpan = document.createElement('span');
                                errorSpan.className = 'log-error';
                                errorSpan.textContent = lineContent;
                                toolsPaneContent.appendChild(errorSpan);
                            } else {
                                toolsPaneContent.appendChild(document.createTextNode(lineContent));
                            }
                        });
                        
                        logSize = data.size;

                        if (isScrolledToBottom) {
                            logViewerContainer.scrollTop = logViewerContainer.scrollHeight;
                        }
                    }

                } catch (error) {
                    console.warn('Could not refresh logs:', error.message);
                    clearInterval(activeLogInterval);
                    activeLogInstanceId = null;
                    toolsPaneContent.textContent = `[ERROR] Log fetching stopped: ${error.message}`;
                }
            };

            fetchLogs();
            activeLogInterval = setInterval(fetchLogs, 500);
        } else if (action === 'script') {
            const instanceName = target.dataset.name;
            openEditor(instanceId, instanceName, action);
        }
    });

    fetchAndStoreBlueprints().then(fetchAndRenderInstances);

    // --- System Monitoring ---
    const cpuProgress = document.getElementById('cpu-progress');
    const cpuPercentText = document.getElementById('cpu-percent-text');
    const ramProgress = document.getElementById('ram-progress');
    const ramUsageText = document.getElementById('ram-usage-text');
    const gpuStatsContainer = document.getElementById('gpu-stats-container');
    const gpuStatTemplate = document.getElementById('gpu-stat-template');

    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    async function updateSystemStats() {
        try {
            const response = await fetch('/api/system/stats');
            if (!response.ok) throw new Error('Failed to fetch system stats');
            const stats = await response.json();

            cpuProgress.style.width = `${stats.cpu_percent}%`;
            cpuPercentText.textContent = `${stats.cpu_percent.toFixed(1)}%`;

            ramProgress.style.width = `${stats.ram.percent}%`;
            ramUsageText.textContent = `${formatBytes(stats.ram.used)} / ${formatBytes(stats.ram.total)}`;

            gpuStatsContainer.innerHTML = '';
            if (stats.gpus && stats.gpus.length > 0) {
                stats.gpus.forEach(gpu => {
                    const gpuStatElement = gpuStatTemplate.content.cloneNode(true);
                    
                    gpuStatElement.querySelector('.gpu-name').textContent = `GPU ${gpu.id}: ${gpu.name}`;
                    
                    const vramProgress = gpuStatElement.querySelector('.vram-progress');
                    const vramText = gpuStatElement.querySelector('.vram-usage-text');
                    vramProgress.style.width = `${gpu.vram.percent}%`;
                    vramText.textContent = `${formatBytes(gpu.vram.used)} / ${formatBytes(gpu.vram.total)}`;

                    const utilProgress = gpuStatElement.querySelector('.util-progress');
                    const utilText = gpuStatElement.querySelector('.util-percent-text');
                    utilProgress.style.width = `${gpu.utilization_percent}%`;
                    utilText.textContent = `${gpu.utilization_percent}%`;

                    gpuStatsContainer.appendChild(gpuStatElement);
                });
            } else {
                gpuStatsContainer.innerHTML = '<p style="text-align: center; color: #aaa;">No NVIDIA GPUs detected.</p>';
            }

        } catch (error) {
            console.error("Error fetching system stats:", error);
        }
    }

    updateSystemStats();
    setInterval(updateSystemStats, 2000);

    Split(['#instance-pane', '#bottom-split'], {
        sizes: [60, 40], minSize: [200, 150], gutterSize: 5,
        direction: 'vertical', cursor: 'row-resize'
    });

    Split(['#tools-pane', '#monitoring-pane'], {
        sizes: [65, 35], minSize: [300, 200], gutterSize: 5,
        direction: 'horizontal', cursor: 'col-resize'
    });
});