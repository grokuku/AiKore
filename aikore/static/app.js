document.addEventListener('DOMContentLoaded', () => {
    const instancesTbody = document.getElementById('instances-tbody');
    const addInstanceBtn = document.querySelector('.add-new-btn');
    let availableBlueprints = []; // Store blueprints globally

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
        } else if (action === 'open') {
            // Handled by the <a> tag href directly
            // No specific JS action needed here as long as href is set correctly
        }
    });

    // --- Initial Load ---
    fetchAndStoreBlueprints().then(fetchAndRenderInstances);
});