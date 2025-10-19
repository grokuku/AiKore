document.addEventListener('DOMContentLoaded', () => {
    const instancesTbody = document.getElementById('instances-tbody');
    const addInstanceBtn = document.querySelector('.add-new-btn');
    let availableBlueprints = []; // Store blueprints globally

    // Tools/Logs pane elements
    const toolsPaneTitle = document.getElementById('tools-pane-title');
    const toolsPaneContent = document.getElementById('tools-pane-content');
    const toolsPaneTerminal = document.querySelector('.terminal-style'); // Get the parent for scroll checks

    // State for live logs
    let activeLogInstanceId = null;
    let activeLogInterval = null;
    let cachedLogContent = ""; // Cache for smart log updates

    // --- Helper function to fetch blueprints and populate the global array ---
    async function fetchAndStoreBlueprints() {
        try {
            const response = await fetch('/api/system/blueprints');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            availableBlueprints = data.blueprints;
        } catch (error) {
            console.error("Failed to fetch blueprints:", error);
            // Fallback if blueprints cannot be loaded
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
            defaultOption.selected = true; // Set as selected by default
            select.appendChild(defaultOption);

            availableBlueprints.forEach(bp => {
                const option = document.createElement('option');
                option.value = bp;
                option.textContent = bp;
                if (bp === selectedValue) {
                    option.selected = true;
                    defaultOption.selected = false; // Unselect default if a value matches
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
        const isStopped = instance.status === 'stopped';
        const isError = instance.status === 'error';

        // Store original values for change detection
        row.dataset.originalName = instance.name;
        row.dataset.originalBlueprint = instance.base_blueprint;
        row.dataset.originalGpuIds = instance.gpu_ids || '';
        row.dataset.originalAutostart = instance.autostart;
        row.dataset.originalPersistentMode = instance.persistent_mode;

        // Name (editable)
        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.value = instance.name;
        nameInput.dataset.field = 'name';
        nameInput.required = true;
        nameInput.disabled = !isNew; // Name is only editable for new instances
        row.insertCell().appendChild(nameInput);

        // Base Blueprint (editable select)
        const blueprintSelect = createBlueprintSelect(instance.base_blueprint);
        blueprintSelect.disabled = !isNew; // Blueprint is only editable for new instances
        row.insertCell().appendChild(blueprintSelect);

        // GPU IDs (editable)
        const gpuInput = document.createElement('input');
        gpuInput.type = 'text';
        gpuInput.value = instance.gpu_ids || '';
        gpuInput.dataset.field = 'gpu_ids';
        row.insertCell().appendChild(gpuInput);

        // Autostart (editable checkbox)
        const autostartCheckbox = document.createElement('input');
        autostartCheckbox.type = 'checkbox';
        autostartCheckbox.checked = instance.autostart;
        autostartCheckbox.dataset.field = 'autostart';
        row.insertCell().appendChild(autostartCheckbox);

        // Persistent UI (editable checkbox)
        const persistentModeCheckbox = document.createElement('input');
        persistentModeCheckbox.type = 'checkbox';
        persistentModeCheckbox.checked = instance.persistent_mode;
        persistentModeCheckbox.dataset.field = 'persistent_mode';
        row.insertCell().appendChild(persistentModeCheckbox);

        // Status (display only)
        row.insertCell().innerHTML = `<span class="${statusClass}">${instance.status}</span>`;

        // Port (display only)
        row.insertCell().textContent = instance.port || 'N/A';

        // Actions column
        const actionsCell = row.insertCell();
        actionsCell.classList.add('actions-column');

        // Start button
        const startButton = document.createElement('button');
        startButton.classList.add('action-btn');
        startButton.dataset.action = 'start';
        startButton.dataset.id = instance.id;
        startButton.textContent = 'Start';
        startButton.disabled = isRunning || isStarting || isNew;
        actionsCell.appendChild(startButton);

        // Stop button
        const stopButton = document.createElement('button');
        stopButton.classList.add('action-btn');
        stopButton.dataset.action = 'stop';
        stopButton.dataset.id = instance.id;
        stopButton.textContent = 'Stop';
        stopButton.disabled = !isRunning || isNew;
        actionsCell.appendChild(stopButton);

        // Logs button
        const logsButton = document.createElement('button');
        logsButton.classList.add('action-btn');
        logsButton.dataset.action = 'logs';
        logsButton.dataset.id = instance.id;
        logsButton.dataset.name = instance.name; // Store name for title
        logsButton.textContent = 'Logs';
        logsButton.disabled = isNew; // Disabled for new unsaved instances
        actionsCell.appendChild(logsButton);

        // Save/Update button
        const saveUpdateButton = document.createElement('button');
        saveUpdateButton.classList.add('action-btn');
        saveUpdateButton.dataset.id = instance.id;
        if (isNew) {
            saveUpdateButton.dataset.action = 'save';
            saveUpdateButton.textContent = 'Save';
            // Enable Save for new rows if name and blueprint are filled
            saveUpdateButton.disabled = !nameInput.value || blueprintSelect.value === '';
        } else {
            saveUpdateButton.dataset.action = 'update';
            saveUpdateButton.textContent = 'Update';
            saveUpdateButton.disabled = true; // Disabled by default, enabled on change
        }
        actionsCell.appendChild(saveUpdateButton);

        // Delete button
        const deleteButton = document.createElement('button');
        deleteButton.classList.add('action-btn');
        deleteButton.dataset.action = 'delete';
        deleteButton.dataset.id = instance.id;
        deleteButton.textContent = 'Delete';
        deleteButton.disabled = isRunning || isStarting;
        actionsCell.appendChild(deleteButton);
        
        // Open button (always last)
        const openButton = document.createElement('a');
        openButton.classList.add('action-btn');
        openButton.dataset.action = 'open';
        openButton.dataset.id = instance.id;
        openButton.textContent = 'Open';
        if (isRunning) {
            openButton.href = `/app/${instance.name}/`;
            openButton.target = '_blank';
            openButton.disabled = false; // Ensure it's not disabled if running
        } else {
            openButton.href = '#'; // No valid link if not running
            openButton.disabled = true;
            openButton.style.pointerEvents = 'none'; // Prevent click events when disabled
        }
        actionsCell.appendChild(openButton);

        // Add event listeners for input changes to enable/disable Update button
        if (!isNew) {
            const editableFields = row.querySelectorAll('input[type="text"], select, input[type="checkbox"]');
            editableFields.forEach(field => {
                field.addEventListener('input', () => {
                    checkRowForChanges(row);
                });
            });
        } else {
            // For new rows, enable Save button if name and blueprint are filled
            nameInput.addEventListener('input', () => {
                saveUpdateButton.disabled = !nameInput.value || blueprintSelect.value === '';
            });
            blueprintSelect.addEventListener('change', () => {
                saveUpdateButton.disabled = !nameInput.value || blueprintSelect.value === '';
            });
        }

        return row;
    }

    /**
     * Checks a row for changes against original values and enables/disables the Update button.
     * @param {HTMLElement} row - The table row element.
     */
    function checkRowForChanges(row) {
        const instanceId = row.dataset.id;
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
        if (autostartField.checked.toString() !== row.dataset.originalAutostart) changed = true; // Compare boolean as string
        if (persistentModeField.checked.toString() !== row.dataset.originalPersistentMode) changed = true; // Compare boolean as string

        updateButton.disabled = !changed;
    }


    /**
     * Fetches instances from the API and renders them in the table.
     */
    async function fetchAndRenderInstances() {
        try {
            const response = await fetch('/api/instances/');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const instances = await response.json();

            instancesTbody.innerHTML = ''; // Clear existing rows

            if (instances.length === 0) {
                instancesTbody.innerHTML = `<tr><td colspan="8" style="text-align: center;">No instances created yet.</td></tr>`;
            } else {
                instances.forEach(instance => {
                    const row = renderInstanceRow(instance, false); // Render existing instances
                    instancesTbody.appendChild(row);
                });
            }
        } catch (error) {
            console.error("Failed to fetch instances:", error);
            instancesTbody.innerHTML = `<tr><td colspan="8">Error loading data. Check console.</td></tr>`;
        }
    }

    /**
     * Adds an empty, editable row for a new instance to the table.
     */
    function addNewInstanceRow() {
        // Create a dummy instance object for the new row
        const newInstance = {
            id: 'new', // Use 'new' as a temporary ID
            name: '',
            base_blueprint: '',
            gpu_ids: '',
            autostart: false,
            persistent_mode: false,
            status: 'stopped', // Default status for a new instance
            pid: null,
            port: null
        };
        const newRow = renderInstanceRow(newInstance, true);
        instancesTbody.appendChild(newRow);

        // Make name and blueprint fields immediately editable for the new row
        newRow.querySelector('input[data-field="name"]').focus();
        newRow.querySelector('input[data-field="name"]').disabled = false;
        newRow.querySelector('select[data-field="base_blueprint"]').disabled = false;
    }

    // --- Event Listeners ---
    addInstanceBtn.addEventListener('click', addNewInstanceRow);

    instancesTbody.addEventListener('click', async (event) => {
        const target = event.target;
        if (!target.classList.contains('action-btn')) return;

        const instanceId = target.dataset.id;
        const action = target.dataset.action;
        const row = target.closest('tr');

        if (action === 'start' || action === 'stop') {
            try {
                const response = await fetch(`/api/instances/${instanceId}/${action}`, { method: 'POST' });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || `Failed to ${action} instance.`);
                }
                fetchAndRenderInstances(); // Refresh the table
            } catch (error) {
                console.error(`Error ${action}ing instance:`, error);
                alert(`Error: ${error.message}`);
            }
        } else if (action === 'save') {
            // Logic to save a new instance
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
                fetchAndRenderInstances(); // Refresh the table
            } catch (error) {
                console.error('Error creating instance:', error);
                alert(`Error: ${error.message}`);
            }

        } else if (action === 'update') {
            // Logic to update an existing instance (not yet implemented)
            alert('Update functionality coming soon!');
            // For now, just refresh to reset button state
            // fetchAndRenderInstances();
        } else if (action === 'delete') {
            if (activeLogInstanceId === instanceId) {
                clearInterval(activeLogInterval);
                activeLogInstanceId = null;
                toolsPaneTitle.textContent = 'Tools / Logs';
                toolsPaneContent.textContent = '> Console output will be displayed here...';
            }
            if (!confirm('Are you sure you want to delete this instance?')) return;
            try {
                const response = await fetch(`/api/instances/${instanceId}`, { method: 'DELETE' });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Failed to delete instance.');
                }
                fetchAndRenderInstances(); // Refresh the table
            } catch (error) {
                console.error('Error deleting instance:', error);
                alert(`Error: ${error.message}`);
            }
        } else if (action === 'logs') {
            const instanceName = target.dataset.name;
            
            // Clear any previous interval and reset state
            clearInterval(activeLogInterval);
            cachedLogContent = ""; // IMPORTANT: Reset cache for the new instance
            activeLogInstanceId = instanceId;

            toolsPaneTitle.textContent = `Logs: ${instanceName}`;
            toolsPaneContent.textContent = 'Loading logs...';

            const fetchLogs = async () => {
                if (!activeLogInstanceId) return;

                try {
                    const response = await fetch(`/api/instances/${activeLogInstanceId}/logs`);
                    if (!response.ok) {
                        throw new Error('Instance stopped or logs unavailable.');
                    }
                    const data = await response.json();

                    // --- Smart Update Logic ---
                    const selection = window.getSelection();
                    const hasSelectionInLogs = selection.toString().length > 0 && toolsPaneContent.contains(selection.anchorNode);
                    
                    if (hasSelectionInLogs) return; // Skip update if user is selecting text

                    const isScrolledToBottom = toolsPaneTerminal.scrollHeight - toolsPaneTerminal.scrollTop <= toolsPaneTerminal.clientHeight + 2; // +2 for buffer
                    
                    if (data.logs.startsWith(cachedLogContent)) {
                        // Append only new content
                        const newContent = data.logs.substring(cachedLogContent.length);
                        if (newContent) {
                            toolsPaneContent.appendChild(document.createTextNode(newContent));
                        }
                    } else {
                        // Full refresh if logs were cleared or are different
                        toolsPaneContent.textContent = data.logs;
                    }
                    cachedLogContent = data.logs; // Update cache

                    if (isScrolledToBottom) {
                        toolsPaneTerminal.scrollTop = toolsPaneTerminal.scrollHeight;
                    }

                } catch (error) {
                    console.warn('Could not refresh logs:', error.message);
                    clearInterval(activeLogInterval);
                    activeLogInstanceId = null;
                }
            };

            fetchLogs(); // Initial fetch
            activeLogInterval = setInterval(fetchLogs, 500); // Poll every 500ms

        } else if (action === 'open') {
            // Handled by the <a> tag href directly
        }
    });

    // --- Initial Load ---
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

            // Update CPU
            cpuProgress.style.width = `${stats.cpu_percent}%`;
            cpuPercentText.textContent = `${stats.cpu_percent.toFixed(1)}%`;

            // Update RAM
            ramProgress.style.width = `${stats.ram.percent}%`;
            ramUsageText.textContent = `${formatBytes(stats.ram.used)} / ${formatBytes(stats.ram.total)}`;

            // Update GPUs
            gpuStatsContainer.innerHTML = ''; // Clear previous entries
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

    // Fetch stats immediately and then every 2 seconds
    updateSystemStats();
    setInterval(updateSystemStats, 2000);

    // --- Initialize Split Panes ---
    Split(['#instance-pane', '#bottom-split'], {
        sizes: [60, 40],
        minSize: [200, 150],
        gutterSize: 5,
        direction: 'vertical',
        cursor: 'row-resize'
    });

    Split(['#tools-pane', '#monitoring-pane'], {
        sizes: [65, 35],
        minSize: [300, 200],
        gutterSize: 5,
        direction: 'horizontal',
        cursor: 'col-resize'
    });
});