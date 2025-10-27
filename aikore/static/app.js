document.addEventListener('DOMContentLoaded', () => {
    const instancesTbody = document.getElementById('instances-tbody');
    const addInstanceBtn = document.querySelector('.add-new-btn');
    let availableBlueprints = [];

    const toolsPaneTitle = document.getElementById('tools-pane-title');
    const welcomeScreenContainer = document.getElementById('welcome-screen-container');
    const logViewerContainer = document.getElementById('log-viewer-container');
    const logContentArea = document.getElementById('log-content-area');
    const editorContainer = document.getElementById('editor-container');
    const fileEditorTextarea = document.getElementById('file-editor-textarea');
    const editorSaveBtn = document.getElementById('editor-save-btn');
    const editorExitBtn = document.getElementById('editor-exit-btn');
    const instanceViewContainer = document.getElementById('instance-view-container');
    const instanceIframe = document.getElementById('instance-iframe');
    const terminalViewContainer = document.getElementById('terminal-view-container');
    const terminalContent = document.getElementById('terminal-content');

    const toolsContextMenu = document.getElementById('tools-context-menu');
    let currentMenuInstance = null;

    const ASCII_LOGO = `                                                       
    @@@@@@   @@@  @@@  @@@   @@@@@@   @@@@@@@   @@@@@@@@  
@@@@@@@@  @@@  @@@  @@@  @@@@@@@@  @@@@@@@@  @@@@@@@@  
@@!  @@@  @@!  @@!  !@@  @@!  @@@  @@!  @@@  @@!       
!@!  @!@  !@!  !@!  @!!  !@!  @!@  !@!  @!@  !@!       
@!@!@!@!  !!@  @!@@!@!   @!@  !@!  @!@!!@!   @!!!:!    
!!!@!!!!  !!!  !!@!!!    !@!  !!!  !!@!@!    !!!!!:    
!!:  !!!  !!:  !!: :!!   !!:  !!!  !!: :!!   !!:       
:!:  !:!  :!:  :!:  !:!  :!:  !:!  :!:  !:!  :!:       
::   :::   ::   ::  :::  ::::: ::  ::   :::   :: ::::  
    :   : :  :     :   :::   : :  :    :   : :  : :: ::   
                                                        `;

    let activeLogInstanceId = null;
    let activeLogInterval = null;
    let logSize = 0;

    let editorState = {
        instanceId: null,
        instanceName: null,
        fileType: null,
    };

    let currentTerminal = null;
    let currentTerminalSocket = null;
    let fitAddon = null;

    let instancesPollInterval = null;

    function closeTerminal() {
        if (currentTerminalSocket) {
            currentTerminalSocket.close();
            currentTerminalSocket = null;
        }
        if (currentTerminal) {
            currentTerminal.dispose();
            currentTerminal = null;
            fitAddon = null;
        }
    }

    function hideAllToolViews() {
        welcomeScreenContainer.classList.add('hidden');
        logViewerContainer.classList.add('hidden');
        editorContainer.classList.add('hidden');
        instanceViewContainer.classList.add('hidden');
        terminalViewContainer.classList.add('hidden');

        instanceIframe.src = 'about:blank';

        clearInterval(activeLogInterval);
        activeLogInstanceId = null;

        closeTerminal();
    }

    function showWelcomeScreen() {
        hideAllToolViews();
        welcomeScreenContainer.classList.remove('hidden');
        welcomeScreenContainer.innerHTML = `<pre>${ASCII_LOGO}</pre>`;
        toolsPaneTitle.textContent = 'Tools / Welcome';
    }

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

    function createBlueprintSelect(selectedValue = '') {
        const select = document.createElement('select');
        select.dataset.field = 'base_blueprint';
        select.required = true;
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = 'Select a blueprint';
        defaultOption.disabled = true;
        select.appendChild(defaultOption);
        if (!selectedValue) defaultOption.selected = true;
        availableBlueprints.forEach(bp => {
            const option = document.createElement('option');
            option.value = bp;
            option.textContent = bp;
            if (bp === selectedValue) option.selected = true;
            select.appendChild(option);
        });
        return select;
    }

    // NEW: Helper function to build the correct URL based on access pattern
    function buildInstanceUrl(instance) {
        if (!instance || !instance.port) return '#';
        const hostname = window.location.hostname;
        if (instance.access_pattern === 'subdomain') {
            // Sanitize instance name to be a valid subdomain part
            const slug = instance.name.toLowerCase().replace(/[^a-z0-9-]/g, '-');
            const hostParts = hostname.split('.');
            // Simple check if hostname is not an IP address
            if (hostParts.length > 1) {
                return `${window.location.protocol}//${slug}.${hostname}`;
            }
        }
        // Default to port-based access
        return `${window.location.protocol}//${hostname}:${instance.port}`;
    }

    function checkRowForChanges(row) {
        const updateButton = row.querySelector('button[data-action="update"]');
        if (!updateButton) return;
        // For now, update is not implemented, so we leave it disabled
        // This function can be expanded when we implement the update endpoint
        updateButton.disabled = true;
    }

    function updateInstanceRow(row, instance) {
        const isStarted = instance.status === 'started';
        const isStopped = instance.status === 'stopped';
        const isActive = !isStopped;

        row.dataset.status = instance.status;

        const statusSpan = row.querySelector('.status');
        statusSpan.textContent = instance.status;
        statusSpan.className = `status status-${instance.status.toLowerCase()}`;

        // Update port and access pattern values
        row.querySelector('[data-field="port"]').value = instance.port || '';
        row.querySelector('[data-field="access_pattern"]').value = instance.access_pattern;

        // Update action buttons based on status
        row.querySelector('[data-action="start"]').disabled = isActive;
        row.querySelector('[data-action="stop"]').disabled = isStopped;
        row.querySelector('[data-action="delete"]').disabled = isActive;

        // Update Activate/Deactivate button
        const activateBtn = row.querySelector('[data-role="activation-button"]');
        if (instance.persistent_mode) {
            activateBtn.classList.add('hidden');
        } else {
            activateBtn.classList.remove('hidden');
            activateBtn.disabled = !isStarted;
            if (instance.is_active) {
                activateBtn.textContent = 'Deactivate';
                activateBtn.dataset.action = 'deactivate';
                activateBtn.classList.add('active-btn');
            } else {
                activateBtn.textContent = 'Activate';
                activateBtn.dataset.action = 'activate';
                activateBtn.classList.remove('active-btn');
            }
        }

        // Update Open and View buttons
        const openButton = row.querySelector('[data-action="open"]');
        const viewButton = row.querySelector('[data-role="view-button"]');
        const canBeAccessed = isStarted && (instance.is_active || instance.persistent_mode);

        if (canBeAccessed) {
            const url = buildInstanceUrl(instance);
            openButton.href = url;
            viewButton.dataset.url = url; // Store URL for iframe
            openButton.classList.remove('disabled');
            viewButton.disabled = false;
        } else {
            openButton.href = '#';
            viewButton.dataset.url = 'about:blank';
            openButton.classList.add('disabled');
            viewButton.disabled = true;
        }

        // Handle the special ComfyUI Active Slot button (legacy, to be phased out or integrated)
        const comfyUIButton = row.querySelector('[data-action="activate_comfyui"]');
        if (comfyUIButton) {
            comfyUIButton.disabled = !isStarted;
        }
    }

    function renderInstanceRow(instance, isNew = false) {
        const row = document.createElement('tr');
        row.dataset.id = instance.id;
        row.dataset.isNew = String(isNew);
        row.dataset.status = instance.status;

        // Store original values for change detection
        row.dataset.originalName = instance.name || '';
        row.dataset.originalBlueprint = instance.base_blueprint || '';
        row.dataset.originalGpuIds = instance.gpu_ids || '';
        row.dataset.originalPort = instance.port || '';
        row.dataset.originalAccessPattern = instance.access_pattern || 'port';
        row.dataset.originalAutostart = String(instance.autostart);
        row.dataset.originalPersistentMode = String(instance.persistent_mode);

        const isStarted = instance.status === 'started';
        const isStopped = instance.status === 'stopped';
        const isActive = !isStopped;
        const canBeAccessed = isStarted && (instance.is_active || instance.persistent_mode);

        // Column: Name
        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.value = instance.name || '';
        nameInput.dataset.field = 'name';
        nameInput.required = true;
        nameInput.disabled = !isNew && isActive;
        row.insertCell().appendChild(nameInput);

        // Column: Blueprint
        const blueprintSelect = createBlueprintSelect(instance.base_blueprint);
        blueprintSelect.disabled = !isNew;
        row.insertCell().appendChild(blueprintSelect);

        // Column: GPU IDs
        const gpuInput = document.createElement('input');
        gpuInput.type = 'text';
        gpuInput.value = instance.gpu_ids || '';
        gpuInput.dataset.field = 'gpu_ids';
        gpuInput.disabled = !isNew; // For simplicity, only editable on creation
        row.insertCell().appendChild(gpuInput);

        // Column: Public Port
        const portInput = document.createElement('input');
        portInput.type = 'number';
        portInput.placeholder = 'e.g. 50001';
        portInput.value = instance.port || '';
        portInput.dataset.field = 'port';
        portInput.required = true;
        portInput.disabled = !isNew; // For simplicity, only editable on creation
        row.insertCell().appendChild(portInput);

        // Column: Access Method
        const accessSelect = document.createElement('select');
        accessSelect.dataset.field = 'access_pattern';
        accessSelect.innerHTML = `
            <option value="port">Hostname:Port</option>
            <option value="subdomain">Subdomain</option>
        `;
        accessSelect.value = instance.access_pattern || 'port';
        row.insertCell().appendChild(accessSelect);

        // Column: Status
        row.insertCell().innerHTML = `<span class="status status-${instance.status.toLowerCase()}">${instance.status}</span>`;

        // Column: Actions
        const actionsCell = row.insertCell();
        actionsCell.classList.add('actions-column');

        if (isNew) {
            actionsCell.innerHTML = `
                <button class="action-btn" data-action="save" data-id="new" disabled>Save</button>
                <button class="action-btn" data-action="cancel_new">Cancel</button>
            `;
        } else {
            const activateBtnClass = instance.is_active ? 'active-btn' : '';
            const activateBtnText = instance.is_active ? 'Deactivate' : 'Activate';
            const activateBtnAction = instance.is_active ? 'deactivate' : 'activate';
            const activateBtnVisibility = instance.persistent_mode ? 'hidden' : '';

            actionsCell.innerHTML = `
                <button class="action-btn ${activateBtnClass} ${activateBtnVisibility}" data-role="activation-button" data-action="${activateBtnAction}" data-id="${instance.id}" ${!isStarted ? 'disabled' : ''}>${activateBtnText}</button>
                <button class="action-btn" data-action="start" data-id="${instance.id}" ${isActive ? 'disabled' : ''}>Start</button>
                <button class="action-btn" data-action="stop" data-id="${instance.id}" ${isStopped ? 'disabled' : ''}>Stop</button>
                <a href="${canBeAccessed ? buildInstanceUrl(instance) : '#'}" class="action-btn ${!canBeAccessed ? 'disabled' : ''}" data-action="open" data-id="${instance.id}" target="_blank">Open</a>
                <button class="action-btn" data-role="view-button" data-action="view" data-url="${canBeAccessed ? buildInstanceUrl(instance) : 'about:blank'}" data-id="${instance.id}" ${!canBeAccessed ? 'disabled' : ''}>View</button>
                <button class="action-btn" data-action="tools_menu" data-id="${instance.id}">Tools</button>
                <button class="action-btn" data-action="delete" data-id="${instance.id}" ${isActive ? 'disabled' : ''}>Delete</button>
            `;
        }

        // Add listeners for new row save button
        if (isNew) {
            const saveButton = row.querySelector('button[data-action="save"]');
            row.querySelectorAll('input, select').forEach(field => field.addEventListener('input', () => {
                const name = row.querySelector('input[data-field="name"]').value;
                const bp = row.querySelector('select[data-field="base_blueprint"]').value;
                const port = row.querySelector('input[data-field="port"]').value;
                saveButton.disabled = !name || !bp || !port;
            }));
        }

        return row;
    }

    async function fetchAndRenderInstances() {
        try {
            const response = await fetch('/api/instances/');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const instances = await response.json();
            const existingRows = new Map([...instancesTbody.querySelectorAll('tr[data-id]')].map(row => [row.dataset.id, row]));

            // Clear "no instances" message if present
            const noInstancesRow = instancesTbody.querySelector('.no-instances-row');
            if (noInstancesRow) noInstancesRow.remove();

            instances.forEach(instance => {
                const instanceIdStr = String(instance.id);
                if (existingRows.has(instanceIdStr)) {
                    updateInstanceRow(existingRows.get(instanceIdStr), instance);
                    existingRows.delete(instanceIdStr);
                } else {
                    const newRow = renderInstanceRow(instance);
                    instancesTbody.appendChild(newRow);
                }
            });

            // Remove rows for instances that no longer exist
            for (const row of existingRows.values()) {
                if (row.dataset.isNew !== 'true') row.remove();
            }

            if (instancesTbody.childElementCount === 0 && !document.querySelector('tr[data-is-new="true"]')) {
                instancesTbody.innerHTML = `<tr class="no-instances-row"><td colspan="7" style="text-align: center;">No instances created yet.</td></tr>`;
            }
        } catch (error) {
            console.error("Failed to fetch instances:", error);
            if (instancesPollInterval) clearInterval(instancesPollInterval);
            instancesTbody.innerHTML = `<tr><td colspan="7" style="text-align:center;">Error loading data. Check console.</td></tr>`;
        }
    }

    function addNewInstanceRow() {
        if (document.querySelector('tr[data-is-new="true"]')) return;
        const noInstancesRow = instancesTbody.querySelector('.no-instances-row');
        if (noInstancesRow) noInstancesRow.remove();
        const newInstance = { id: 'new', autostart: false, persistent_mode: false, status: 'stopped', access_pattern: 'port' };
        const newRow = renderInstanceRow(newInstance, true);
        instancesTbody.appendChild(newRow);
        newRow.querySelector('input[data-field="name"]').focus();
    }

    addInstanceBtn.addEventListener('click', addNewInstanceRow);

    function exitEditor() {
        editorState = { instanceId: null, instanceName: null, fileType: null };
        showWelcomeScreen();
    }

    async function openEditor(instanceId, instanceName, fileType) {
        hideAllToolViews();
        editorContainer.classList.remove('hidden');
        const fileTypeName = fileType.charAt(0).toUpperCase() + fileType.slice(1);
        toolsPaneTitle.textContent = `Editing ${fileTypeName} for: ${instanceName}`;
        fileEditorTextarea.value = `Loading ${fileType} content...`;
        editorState = { instanceId, instanceName, fileType };
        try {
            const response = await fetch(`/api/instances/${instanceId}/file?file_type=${fileType}`);
            if (!response.ok) throw new Error((await response.json()).detail || 'Failed to load file.');
            const data = await response.json();
            fileEditorTextarea.value = data.content;
        } catch (error) {
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
                method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content })
            });
            if (!response.ok) throw new Error((await response.json()).detail || 'Failed to save file.');
            editorSaveBtn.textContent = 'Saved!';
            setTimeout(() => { editorSaveBtn.textContent = 'Save'; editorSaveBtn.disabled = false; }, 1500);
        } catch (error) {
            alert(`Error saving file: ${error.message}`);
            editorSaveBtn.textContent = 'Save'; editorSaveBtn.disabled = false;
        }
    }

    function openInstanceView(instancePath, instanceName) {
        hideAllToolViews();
        instanceViewContainer.classList.remove('hidden');
        toolsPaneTitle.textContent = `View: ${instanceName}`;
        instanceIframe.src = instancePath;
    }

    function openTerminal(instanceId, instanceName) {
        hideAllToolViews();

        terminalViewContainer.classList.remove('hidden');
        toolsPaneTitle.textContent = `Terminal: ${instanceName}`;

        currentTerminal = new Terminal({
            cursorBlink: true, fontSize: 14, fontFamily: 'Courier New, Courier, monospace',
            theme: { background: '#111111', foreground: '#e0e0e0', cursor: '#e0e0e0' }
        });
        fitAddon = new FitAddon.FitAddon();
        currentTerminal.loadAddon(fitAddon);

        terminalContent.innerHTML = '';
        currentTerminal.open(terminalContent);
        fitAddon.fit();
        currentTerminal.focus();

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/instances/${instanceId}/terminal`;
        currentTerminalSocket = new WebSocket(wsUrl);
        currentTerminalSocket.binaryType = 'arraybuffer';

        currentTerminalSocket.onopen = () => {
            const initialSize = { type: 'resize', cols: currentTerminal.cols, rows: currentTerminal.rows };
            currentTerminalSocket.send(JSON.stringify(initialSize));
            currentTerminal.onData(data => { if (currentTerminalSocket && currentTerminalSocket.readyState === WebSocket.OPEN) currentTerminalSocket.send(data); });
            currentTerminal.onResize(size => { if (currentTerminalSocket && currentTerminalSocket.readyState === WebSocket.OPEN) currentTerminalSocket.send(JSON.stringify({ type: 'resize', cols: size.cols, rows: size.rows })); });
        };

        currentTerminalSocket.onmessage = (event) => { currentTerminal.write(new Uint8Array(event.data)); };
        currentTerminalSocket.onclose = (event) => { currentTerminal.write(`\r\n\r\n\x1b[31m[CONNECTION CLOSED]\x1b[0m Code: ${event.code}${event.reason ? `: ${event.reason}` : ''}\r\n`); };
        currentTerminalSocket.onerror = (error) => { currentTerminal.write('\r\n\x1b[31m[WEBSOCKET CONNECTION ERROR]\x1b[0m\r\n'); console.error('WebSocket Error:', error); };
    }

    editorSaveBtn.addEventListener('click', saveFileContent);
    editorExitBtn.addEventListener('click', exitEditor);

    function showToolsMenu(buttonEl) {
        const row = buttonEl.closest('tr');
        const status = row.dataset.status;
        const isStopped = status === 'stopped';

        toolsContextMenu.querySelector('[data-action="terminal"]').disabled = false;
        toolsContextMenu.querySelector('[data-action="script"]').disabled = !isStopped;

        const rect = buttonEl.getBoundingClientRect();
        toolsContextMenu.style.display = 'block';
        toolsContextMenu.style.left = `${rect.left}px`;
        toolsContextMenu.style.top = `${rect.bottom + 5}px`;

        currentMenuInstance = {
            id: row.dataset.id,
            name: row.querySelector('[data-field="name"]').value || row.dataset.originalName
        };
    }

    function hideToolsMenu() {
        toolsContextMenu.style.display = 'none';
        currentMenuInstance = null;
    }

    // MASTER EVENT LISTENER FOR THE TABLE BODY
    instancesTbody.addEventListener('click', async (event) => {
        const target = event.target.closest('[data-action]');
        if (!target || target.disabled || target.classList.contains('disabled')) return;
        if (target.closest('.context-menu')) return;

        const action = target.dataset.action;

        if (action === 'tools_menu') {
            showToolsMenu(target);
            return;
        }
        hideToolsMenu();

        const row = target.closest('tr');
        const instanceId = row.dataset.id;

        if (action === 'start' || action === 'stop' || action === 'deactivate') {
            target.disabled = true;
            const endpoint = action === 'deactivate' ? `/api/instances/${instanceId}/deactivate` : `/api/instances/${instanceId}/${action}`;
            try {
                const response = await fetch(endpoint, { method: 'POST' });
                if (!response.ok) throw new Error((await response.json()).detail);
                await fetchAndRenderInstances();
            } catch (error) {
                alert(`Error: ${error.message}`);
                await fetchAndRenderInstances();
            }
        } else if (action === 'activate') {
            target.disabled = true;
            try {
                let response = await fetch(`/api/instances/${instanceId}/activate`, { method: 'POST' });
                let result = await response.json();

                if (response.status === 400) throw new Error(result.detail);

                if (result.conflict) {
                    if (confirm(`Port conflict: This port is used by "${result.conflicting_instance_name}".\n\nDo you want to force activation, deactivating the other instance?`)) {
                        response = await fetch(`/api/instances/${instanceId}/activate?force=true`, { method: 'POST' });
                        result = await response.json();
                        if (!response.ok) throw new Error(result.detail || 'Forced activation failed.');
                    }
                } else if (!result.success) {
                    throw new Error(result.message);
                }
                await fetchAndRenderInstances();
            } catch (error) {
                alert(`Error: ${error.message}`);
                await fetchAndRenderInstances();
            }

        } else if (action === 'save') {
            const data = {
                name: row.querySelector('[data-field="name"]').value,
                base_blueprint: row.querySelector('[data-field="base_blueprint"]').value,
                port: parseInt(row.querySelector('[data-field="port"]').value, 10),
                access_pattern: row.querySelector('[data-field="access_pattern"]').value,
                gpu_ids: row.querySelector('input[data-field="gpu_ids"]').value || null,
                // autostart and persistent_mode are not in the new row for simplicity, add if needed
            };
            try {
                const response = await fetch('/api/instances/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
                if (!response.ok) throw new Error((await response.json()).detail);
                row.remove();
                await fetchAndRenderInstances();
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        } else if (action === 'delete') {
            if (confirm('Are you sure you want to delete this instance? This will move its config to the trashcan.')) {
                try {
                    const response = await fetch(`/api/instances/${instanceId}`, { method: 'DELETE' });
                    if (!response.ok) throw new Error((await response.json()).detail);
                    await fetchAndRenderInstances();
                } catch (error) {
                    alert(`Error: ${error.message}`);
                }
            }
        } else if (action === 'logs') {
            hideAllToolViews();
            logViewerContainer.classList.remove('hidden');
            toolsPaneTitle.textContent = `Logs: ${row.dataset.originalName}`;
            logContentArea.textContent = 'Loading logs...';
            activeLogInstanceId = instanceId;
            logSize = 0;
            const fetchLogs = async () => {
                if (!activeLogInstanceId) return;
                try {
                    const response = await fetch(`/api/instances/${activeLogInstanceId}/logs?offset=${logSize}`);
                    if (!response.ok) throw new Error('Logs unavailable.');
                    const data = await response.json();
                    const isScrolled = logViewerContainer.scrollHeight - logViewerContainer.scrollTop <= logViewerContainer.clientHeight + 2;
                    if (data.content) {
                        if (logContentArea.textContent === 'Loading logs...') logContentArea.textContent = '';
                        logContentArea.appendChild(document.createTextNode(data.content));
                        logSize = data.size;
                        if (isScrolled) logViewerContainer.scrollTop = logViewerContainer.scrollHeight;
                    }
                } catch (error) { clearInterval(activeLogInterval); activeLogInstanceId = null; }
            };
            fetchLogs();
            activeLogInterval = setInterval(fetchLogs, 2000);
        } else if (action === 'view') {
            openInstanceView(target.dataset.url, row.dataset.originalName);
        } else if (action === 'cancel_new') {
            row.remove();
            if (instancesTbody.childElementCount === 0) fetchAndRenderInstances();
        }
    });

    // Listener for access pattern changes
    instancesTbody.addEventListener('change', async (event) => {
        const target = event.target;
        if (target.dataset.field === 'access_pattern') {
            const row = target.closest('tr');
            const instanceId = row.dataset.id;
            const newPattern = target.value;
            try {
                const response = await fetch(`/api/instances/${instanceId}/access-pattern`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ access_pattern: newPattern })
                });
                if (!response.ok) throw new Error((await response.json()).detail);
                // No full re-render needed, just update the Open button URL
                const instanceData = {
                    name: row.dataset.originalName,
                    port: row.querySelector('[data-field="port"]').value,
                    access_pattern: newPattern
                };
                const openButton = row.querySelector('[data-action="open"]');
                const viewButton = row.querySelector('[data-role="view-button"]');
                const newUrl = buildInstanceUrl(instanceData);
                openButton.href = newUrl;
                viewButton.dataset.url = newUrl;
            } catch (error) {
                alert(`Failed to update access pattern: ${error.message}`);
                target.value = row.dataset.originalAccessPattern; // Revert on failure
            }
        }
    });

    toolsContextMenu.addEventListener('click', (event) => {
        const target = event.target.closest('[data-action]');
        if (!target || target.disabled) return;
        const action = target.dataset.action;
        if (currentMenuInstance) {
            if (action === 'script') openEditor(currentMenuInstance.id, currentMenuInstance.name, 'script');
            else if (action === 'terminal') openTerminal(currentMenuInstance.id, currentMenuInstance.name);
        }
        hideToolsMenu();
    });

    document.addEventListener('click', (event) => { if (!event.target.closest('.context-menu') && !event.target.closest('[data-action="tools_menu"]')) hideToolsMenu(); });

    async function initializeApp() {
        await fetchAndStoreBlueprints();
        await fetchAndRenderInstances();
        updateSystemStats();
        showWelcomeScreen();
        if (instancesPollInterval) clearInterval(instancesPollInterval);
        instancesPollInterval = setInterval(fetchAndRenderInstances, 2000);
        setInterval(updateSystemStats, 2000);
    }

    const cpuProgress = document.getElementById('cpu-progress');
    const cpuPercentText = document.getElementById('cpu-percent-text');
    const ramProgress = document.getElementById('ram-progress');
    const ramUsageText = document.getElementById('ram-usage-text');
    const gpuStatsContainer = document.getElementById('gpu-stats-container');
    const gpuStatTemplate = document.getElementById('gpu-stat-template');
    function formatBytes(bytes, d = 2) { if (bytes === 0) return '0 Bytes'; const k = 1024; const i = Math.floor(Math.log(bytes) / Math.log(k)); return `${parseFloat((bytes / Math.pow(k, i)).toFixed(d < 0 ? 0 : d))} ${['Bytes', 'KB', 'MB', 'GB', 'TB'][i]}`; }
    async function updateSystemStats() { try { const r = await fetch('/api/system/stats'); if (!r.ok) return; const s = await r.json(); cpuProgress.style.width = `${s.cpu_percent}%`; cpuPercentText.textContent = `${s.cpu_percent.toFixed(1)}%`; ramProgress.style.width = `${s.ram.percent}%`; ramUsageText.textContent = `${formatBytes(s.ram.used)} / ${formatBytes(s.ram.total)}`; gpuStatsContainer.innerHTML = ''; if (s.gpus && s.gpus.length > 0) { s.gpus.forEach(g => { const e = gpuStatTemplate.content.cloneNode(true); e.querySelector('.gpu-name').textContent = `GPU ${g.id}: ${g.name}`; e.querySelector('.vram-progress').style.width = `${g.vram.percent}%`; e.querySelector('.vram-usage-text').textContent = `${formatBytes(g.vram.used)} / ${formatBytes(g.vram.total)}`; e.querySelector('.util-progress').style.width = `${g.utilization_percent}%`; e.querySelector('.util-percent-text').textContent = `${g.utilization_percent}%`; gpuStatsContainer.appendChild(e); }); } else { gpuStatsContainer.innerHTML = '<p style="text-align:center;color:#aaa;">No NVIDIA GPUs detected.</p>'; } } catch (e) { console.warn("Could not fetch system stats:", e); } }

    initializeApp();

    const SPLIT_STORAGE_KEY = 'aikoreSplitSizes';
    let savedSizes = { vertical: [60, 40], horizontal: [65, 35] };
    try { const stored = localStorage.getItem(SPLIT_STORAGE_KEY); if (stored) { const parsed = JSON.parse(stored); if (parsed.vertical && parsed.horizontal) savedSizes = parsed; } } catch (e) { console.error("Failed to load split sizes.", e); }
    Split(['#instance-pane', '#bottom-split'], { sizes: savedSizes.vertical, minSize: [200, 150], gutterSize: 5, direction: 'vertical', onDragEnd: (s) => { savedSizes.vertical = s; localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(savedSizes)); } });
    Split(['#tools-pane', '#monitoring-pane'], { sizes: savedSizes.horizontal, minSize: [300, 200], gutterSize: 5, onDragEnd: (s) => { savedSizes.horizontal = s; localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(savedSizes)); if (fitAddon) fitAddon.fit(); } });

    const toolsPane = document.getElementById('tools-pane');
    const resizeObserver = new ResizeObserver(() => { if (fitAddon) { try { fitAddon.fit(); } catch (e) { /* Ignore */ } } });
    resizeObserver.observe(toolsPane);
});