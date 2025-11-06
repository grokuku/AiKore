document.addEventListener('DOMContentLoaded', () => {
    const instancesTbody = document.getElementById('instances-tbody');
    const addInstanceBtn = document.querySelector('.add-new-btn');
    let availableBlueprints = [];
    let systemInfo = { gpu_count: 0 };

    const toolsPaneTitle = document.getElementById('tools-pane-title');
    const welcomeScreenContainer = document.getElementById('welcome-screen-container');
    const welcomeIframe = document.getElementById('welcome-iframe');
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
    const toolsCloseBtn = document.getElementById('tools-close-btn');

    const toolsContextMenu = document.getElementById('tools-context-menu');
    let currentMenuInstance = null;

    const deleteModal = document.getElementById('delete-modal');
    const overwriteModal = document.getElementById('overwrite-modal');
    let instanceToDeleteId = null;

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

    let viewResizeObserver = null;

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
        toolsCloseBtn.classList.add('hidden');

        instanceIframe.src = 'about:blank';
        welcomeIframe.src = 'about:blank';
        clearInterval(activeLogInterval);
        activeLogInstanceId = null;
        closeTerminal();
        if (viewResizeObserver) {
            viewResizeObserver.disconnect();
        }
    }

    function showWelcomeScreen() {
        hideAllToolViews();
        welcomeScreenContainer.classList.remove('hidden');
        welcomeIframe.src = '/static/welcome/index.html';
        toolsPaneTitle.textContent = 'Tools / Welcome';
    }

    async function fetchSystemInfo() {
        try {
            const response = await fetch('/api/system/info');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            systemInfo = await response.json();
        } catch (error) {
            console.error("Failed to fetch system info:", error);
            systemInfo = { gpu_count: 0 };
        }
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

    function checkRowForChanges(row) {
        const updateButton = row.querySelector('button[data-action="update"]');
        if (!updateButton) return;

        const nameField = row.querySelector('input[data-field="name"]');
        const autostartField = row.querySelector('input[data-field="autostart"]');
        const hostnameField = row.querySelector('input[data-field="hostname"]');

        const selectedGpuIds = Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(',');

        let changed = false;
        if (nameField.value !== row.dataset.originalName) changed = true;
        if (selectedGpuIds !== row.dataset.originalGpuIds) changed = true;
        if (autostartField.checked.toString() !== row.dataset.originalAutostart) changed = true;
        if ((hostnameField.value || '') !== (row.dataset.originalHostname || '')) changed = true;

        updateButton.disabled = !changed;
    }

    function buildInstanceUrl(row, forView = false) {
        const isStarted = row.dataset.status === 'started';
        if (!isStarted) return '#';

        const customHostname = row.dataset.hostname;
        const isPersistent = row.dataset.persistentMode === 'true';
        const port = isPersistent ? row.dataset.persistentPort : row.dataset.port;

        let baseUrl = '';
        if (customHostname) {
            baseUrl = customHostname.startsWith('http') ? customHostname : `http://${customHostname}`;
        } else {
            baseUrl = `${window.location.protocol}//${window.location.hostname}:${port}`;
        }

        if (isPersistent) {
            return forView ? `${baseUrl}/vnc.html?resize=remote` : baseUrl;
        } else {
            return baseUrl;
        }
    }

    function updateInstanceRow(row, instance) {
        const isStarted = instance.status === 'started';
        const isStopped = instance.status === 'stopped';
        const isActive = !isStopped;

        row.dataset.status = instance.status;
        row.dataset.port = instance.port || '';
        row.dataset.persistentPort = instance.persistent_port || '';
        row.dataset.persistentMode = String(instance.persistent_mode);
        row.dataset.name = instance.name;
        row.dataset.hostname = instance.hostname || '';

        const statusSpan = row.querySelector('.status');
        statusSpan.textContent = instance.status;
        statusSpan.className = `status status-${instance.status.toLowerCase()}`;

        const hostnameInput = row.querySelector('[data-field="hostname"]');
        if (hostnameInput) hostnameInput.value = instance.hostname || '';

        const displayPort = instance.persistent_mode ? instance.persistent_port : instance.port;
        row.cells[8].textContent = displayPort || 'N/A';

        row.querySelector('[data-action="start"]').disabled = isActive;
        row.querySelector('[data-action="stop"]').disabled = isStopped;
        row.querySelector('[data-action="delete"]').disabled = isActive;

        const openButton = row.querySelector('[data-action="open"]');
        const viewButton = row.querySelector('[data-action="view"]');

        const openHref = buildInstanceUrl(row, false);

        openButton.href = openHref;
        openButton.classList.toggle('disabled', openHref === '#');
        viewButton.disabled = !isStarted;

        checkRowForChanges(row);
    }

    function renderInstanceRow(instance, isNew = false) {
        const row = document.createElement('tr');
        row.dataset.id = instance.id;
        row.dataset.isNew = String(isNew);

        row.dataset.originalName = instance.name || '';
        row.dataset.originalBlueprint = instance.base_blueprint || '';
        row.dataset.originalGpuIds = instance.gpu_ids || '';
        row.dataset.originalAutostart = String(instance.autostart);
        row.dataset.originalPersistentMode = String(instance.persistent_mode);
        row.dataset.originalHostname = instance.hostname || '';

        row.dataset.status = instance.status;
        row.dataset.name = instance.name || '';
        row.dataset.port = instance.port || '';
        row.dataset.persistentPort = instance.persistent_port || '';
        row.dataset.persistentMode = String(instance.persistent_mode);
        row.dataset.hostname = instance.hostname || '';

        const isStarted = instance.status === 'started';
        const isStopped = instance.status === 'stopped';
        const isActive = !isStopped;

        const handleCell = row.insertCell();
        if (!isNew) {
            handleCell.classList.add('drag-handle');
            handleCell.innerHTML = '&#x2630;';
        }

        const nameInput = document.createElement('input');
        nameInput.type = 'text';
        nameInput.value = instance.name || '';
        nameInput.dataset.field = 'name';
        nameInput.required = true;
        nameInput.disabled = !isNew && isActive;
        row.insertCell().appendChild(nameInput);

        const blueprintSelect = createBlueprintSelect(instance.base_blueprint);
        blueprintSelect.disabled = !isNew;
        row.insertCell().appendChild(blueprintSelect);

        const gpuCell = row.insertCell();
        const gpuContainer = document.createElement('div');
        gpuContainer.className = 'gpu-checkbox-container';
        const assignedGpus = (instance.gpu_ids || '').split(',').filter(id => id);
        for (let i = 0; i < systemInfo.gpu_count; i++) {
            const label = document.createElement('label');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.name = `gpu_id_${instance.id || 'new'}_${i}`;
            checkbox.value = i;
            if (assignedGpus.includes(String(i))) {
                checkbox.checked = true;
            }
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(` ${i}`));
            gpuContainer.appendChild(label);
        }
        if (systemInfo.gpu_count === 0) {
            gpuContainer.textContent = 'N/A';
        }
        gpuCell.appendChild(gpuContainer);

        const autostartCheckbox = document.createElement('input');
        autostartCheckbox.type = 'checkbox';
        autostartCheckbox.checked = instance.autostart;
        autostartCheckbox.dataset.field = 'autostart';
        row.insertCell().appendChild(autostartCheckbox);

        const persistentModeCheckbox = document.createElement('input');
        persistentModeCheckbox.type = 'checkbox';
        persistentModeCheckbox.checked = instance.persistent_mode;
        persistentModeCheckbox.dataset.field = 'persistent_mode';
        persistentModeCheckbox.disabled = !isNew;
        row.insertCell().appendChild(persistentModeCheckbox);

        row.insertCell().innerHTML = `<span class="status status-${instance.status.toLowerCase()}">${instance.status}</span>`;

        const hostnameInput = document.createElement('input');
        hostnameInput.type = 'text';
        hostnameInput.value = instance.hostname || '';
        hostnameInput.placeholder = 'e.g., my-app.local';
        hostnameInput.dataset.field = 'hostname';
        row.insertCell().appendChild(hostnameInput);

        const portCell = row.insertCell();
        if (isNew) {
            const portInput = document.createElement('input');
            portInput.type = 'number';
            portInput.placeholder = 'Auto';
            portInput.dataset.field = 'port';
            portInput.min = '1';
            portInput.max = '65535';
            portCell.appendChild(portInput);
        } else {
            const displayPort = instance.persistent_mode ? instance.persistent_port : instance.port;
            portCell.textContent = displayPort || 'N/A';
        }

        const actionsCell = row.insertCell();
        actionsCell.classList.add('actions-column');
        if (isNew) {
            actionsCell.innerHTML = `
                <button class="action-btn" data-action="save" data-id="new" disabled>Save</button>
                <button class="action-btn" data-action="cancel_new">Cancel</button>
                <!-- Empty buttons for alignment -->
                <span class="action-btn-placeholder"></span>
                <span class="action-btn-placeholder"></span>
                <span class="action-btn-placeholder"></span>
                <span class="action-btn-placeholder"></span>
                <span class="action-btn-placeholder"></span>
                <span class="action-btn-placeholder"></span>`;
        } else {
            const openHref = buildInstanceUrl(row, false);
            actionsCell.innerHTML = `
                <button class="action-btn" data-action="start" data-id="${instance.id}" ${isActive ? 'disabled' : ''}>Start</button>
                <button class="action-btn" data-action="stop" data-id="${instance.id}" ${isStopped ? 'disabled' : ''}>Stop</button>
                <button class="action-btn" data-action="logs" data-id="${instance.id}">Logs</button>
                <button class="action-btn" data-action="tools_menu" data-id="${instance.id}">Tools</button>
                <button class="action-btn" data-action="update" data-id="${instance.id}" disabled>Update</button>
                <button class="action-btn" data-action="delete" data-id="${instance.id}" ${isActive ? 'disabled' : ''}>Delete</button>
                <button class="action-btn" data-action="view" data-id="${instance.id}" ${!isStarted ? 'disabled' : ''}>View</button>
                <a href="${openHref}" class="action-btn ${openHref === '#' ? 'disabled' : ''}" data-action="open" data-id="${instance.id}" target="_blank">Open</a>`;
        }

        const allFields = row.querySelectorAll('input, select');
        if (isNew) {
            const saveButton = row.querySelector('button[data-action="save"]');
            allFields.forEach(field => field.addEventListener('input', () => {
                const name = row.querySelector('input[data-field="name"]').value;
                const bp = row.querySelector('select[data-field="base_blueprint"]').value;
                saveButton.disabled = !name || !bp;
            }));
        } else {
            allFields.forEach(field => field.addEventListener('input', () => checkRowForChanges(row)));
        }
        return row;
    }

    const INSTANCE_ORDER_KEY = 'aikoreInstanceOrder';

    async function fetchAndRenderInstances() {
        try {
            // --- CRITICAL FIX: Preserve the "new instance" row during polling ---
            const newInstanceRow = instancesTbody.querySelector('tr[data-is-new="true"]');

            const response = await fetch('/api/instances/');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            let instances = await response.json();

            const savedOrder = JSON.parse(localStorage.getItem(INSTANCE_ORDER_KEY) || '[]');
            if (savedOrder.length > 0) {
                instances.sort((a, b) => {
                    const indexA = savedOrder.indexOf(String(a.id));
                    const indexB = savedOrder.indexOf(String(b.id));
                    if (indexA !== -1 && indexB !== -1) return indexA - indexB;
                    if (indexA !== -1) return -1;
                    if (indexB !== -1) return 1;
                    return 0;
                });
            }

            const existingRows = new Map([...instancesTbody.querySelectorAll('tr[data-id]:not([data-is-new="true"])')].map(row => [row.dataset.id, row]));
            const fragment = document.createDocumentFragment();

            instances.forEach(instance => {
                const instanceIdStr = String(instance.id);
                let row = existingRows.get(instanceIdStr);
                if (row) {
                    updateInstanceRow(row, instance);
                    existingRows.delete(instanceIdStr);
                } else {
                    row = renderInstanceRow(instance);
                }
                fragment.appendChild(row);
            });

            instancesTbody.innerHTML = ''; // Clear the table
            instancesTbody.appendChild(fragment); // Append the updated/correct rows

            if (newInstanceRow) {
                instancesTbody.appendChild(newInstanceRow); // Add the "new instance" row back
            }

            if (instancesTbody.childElementCount === 0) {
                instancesTbody.innerHTML = `<tr class="no-instances-row"><td colspan="10" style="text-align: center;">No instances created yet.</td></tr>`;
            }
        } catch (error) {
            console.error("Failed to fetch instances:", error);
            if (instancesPollInterval) clearInterval(instancesPollInterval);
            instancesTbody.innerHTML = `<tr><td colspan="10" style="text-align:center;">Error loading data. Check console.</td></tr>`;
        }
    }

    async function addNewInstanceRow() {
        if (document.querySelector('tr[data-is-new="true"]')) return;
        const noInstancesRow = instancesTbody.querySelector('.no-instances-row');
        if (noInstancesRow) noInstancesRow.remove();
        const newInstance = { id: 'new', autostart: false, persistent_mode: false, status: 'stopped' };
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
        toolsCloseBtn.classList.remove('hidden');
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

    function openInstanceView(instanceName, url) {
        hideAllToolViews();
        instanceViewContainer.classList.remove('hidden');
        toolsCloseBtn.classList.remove('hidden');
        toolsPaneTitle.textContent = `View: ${instanceName}`;
        if (!url || url === '#') {
            instanceIframe.src = 'about:blank';
            console.error("Cannot open view: instance URL is missing or instance is stopped.");
            return;
        }
        instanceIframe.src = url;
        if (viewResizeObserver) {
            viewResizeObserver.observe(instanceViewContainer);
        }
    }

    function openTerminal(instanceId, instanceName) {
        hideAllToolViews();
        terminalViewContainer.classList.remove('hidden');
        toolsCloseBtn.classList.remove('hidden');
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
            currentTerminal.onData(data => {
                if (currentTerminalSocket && currentTerminalSocket.readyState === WebSocket.OPEN) currentTerminalSocket.send(data);
            });
            currentTerminal.onResize(size => {
                if (currentTerminalSocket && currentTerminalSocket.readyState === WebSocket.OPEN) {
                    currentTerminalSocket.send(JSON.stringify({ type: 'resize', cols: size.cols, rows: size.rows }));
                }
            });
        };
        currentTerminalSocket.onmessage = (event) => { currentTerminal.write(new Uint8Array(event.data)); };
        currentTerminalSocket.onclose = (event) => {
            currentTerminal.write(`\r\n\x1b[31m[CLOSED]\x1b[0m ${event.reason || ''}\r\n`);
        };
        currentTerminalSocket.onerror = (error) => {
            currentTerminal.write('\r\n\x1b[31m[ERROR]\x1b[0m\r\n'); console.error('WebSocket Error:', error);
        };
    }

    editorSaveBtn.addEventListener('click', saveFileContent);
    editorExitBtn.addEventListener('click', exitEditor);

    function showToolsMenu(buttonEl) {
        const row = buttonEl.closest('tr');
        const status = row.dataset.status;
        const isStopped = status === 'stopped';
        toolsContextMenu.querySelector('[data-action="script"]').disabled = !isStopped;
        const rect = buttonEl.getBoundingClientRect();
        toolsContextMenu.style.display = 'block';
        toolsContextMenu.style.left = `${rect.left}px`;
        toolsContextMenu.style.top = `${rect.bottom + 5}px`;
        currentMenuInstance = { id: row.dataset.id, name: row.dataset.name };
    }

    function hideToolsMenu() {
        toolsContextMenu.style.display = 'none';
        currentMenuInstance = null;
    }

    function hideAllModals() {
        deleteModal.classList.add('hidden');
        overwriteModal.classList.add('hidden');
        instanceToDeleteId = null;
    }

    instancesTbody.addEventListener('click', async (event) => {
        const target = event.target.closest('[data-action]');
        if (!target) return;
        if (target.closest('.context-menu')) return;
        if (target.disabled || target.classList.contains('disabled')) return;
        const action = target.dataset.action;
        if (action === 'tools_menu') { showToolsMenu(target); return; }
        hideToolsMenu();
        const row = target.closest('tr');
        const instanceId = row.dataset.id;

        if (action === 'start' || action === 'stop') {
            target.disabled = true;
            try {
                const response = await fetch(`/api/instances/${instanceId}/${action}`, { method: 'POST' });
                if (!response.ok) throw new Error((await response.json()).detail);
                await fetchAndRenderInstances();
            } catch (error) { alert(`Error: ${error.message}`); await fetchAndRenderInstances(); }
        } else if (action === 'save') {
            const portValue = row.querySelector('input[data-field="port"]').value;
            const data = {
                name: row.querySelector('input[data-field="name"]').value,
                base_blueprint: row.querySelector('select[data-field="base_blueprint"]').value,
                gpu_ids: Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(','),
                autostart: row.querySelector('input[data-field="autostart"]').checked,
                persistent_mode: row.querySelector('input[data-field="persistent_mode"]').checked,
                hostname: row.querySelector('input[data-field="hostname"]').value || null,
                port: portValue ? parseInt(portValue, 10) : null
            };
            try {
                const response = await fetch('/api/instances/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
                if (!response.ok) throw new Error((await response.json()).detail);
                row.remove();
                await fetchAndRenderInstances();
            } catch (error) { alert(`Error: ${error.message}`); }
        } else if (action === 'update') {
            const data = {
                name: row.querySelector('input[data-field="name"]').value,
                gpu_ids: Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(','),
                autostart: row.querySelector('input[data-field="autostart"]').checked,
                hostname: row.querySelector('input[data-field="hostname"]').value || null,
            };
            target.textContent = 'Updating...'; target.disabled = true;
            try {
                const response = await fetch(`/api/instances/${instanceId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
                if (!response.ok) throw new Error((await response.json()).detail);
                const updatedInstance = await response.json();
                row.dataset.originalName = updatedInstance.name;
                row.dataset.originalGpuIds = updatedInstance.gpu_ids || '';
                row.dataset.originalAutostart = String(updatedInstance.autostart);
                row.dataset.originalHostname = updatedInstance.hostname || '';
                await fetchAndRenderInstances();
            } catch (error) { alert(`Error: ${error.message}`); }
            finally { target.textContent = 'Update'; }
        } else if (action === 'delete') {
            instanceToDeleteId = instanceId;
            document.getElementById('delete-modal-instance-name').textContent = row.dataset.name;
            deleteModal.classList.remove('hidden');
        } else if (action === 'logs') {
            hideAllToolViews();
            logViewerContainer.classList.remove('hidden');
            toolsCloseBtn.classList.remove('hidden');
            toolsPaneTitle.textContent = `Logs: ${row.dataset.name}`;
            logContentArea.textContent = 'Loading logs...';
            activeLogInstanceId = instanceId;
            logSize = 0;
            const fetchLogs = async () => {
                if (!activeLogInstanceId) return;
                try {
                    const response = await fetch(`/api/instances/${activeLogInstanceId}/logs?offset=${logSize}`);
                    if (!response.ok) throw new Error('Instance stopped or logs unavailable.');
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
            const url = buildInstanceUrl(row, true);
            openInstanceView(row.dataset.name, url);
        } else if (action === 'cancel_new') {
            row.remove();
            if (instancesTbody.childElementCount === 0) fetchAndRenderInstances();
        }
    });

    toolsContextMenu.addEventListener('click', (event) => {
        const target = event.target.closest('[data-action]');
        if (!target || target.disabled) return;
        const action = target.dataset.action;
        if (currentMenuInstance) {
            if (action === 'script') {
                openEditor(currentMenuInstance.id, currentMenuInstance.name, 'script');
            } else if (action === 'terminal') {
                openTerminal(currentMenuInstance.id, currentMenuInstance.name);
            }
        }
        hideToolsMenu();
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.context-menu') && !event.target.closest('[data-action="tools_menu"]')) {
            hideToolsMenu();
        }
    });

    async function handleDelete(options) {
        if (!instanceToDeleteId) return;
        try {
            const response = await fetch(`/api/instances/${instanceToDeleteId}`, {
                method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options)
            });
            if (response.status === 409) {
                deleteModal.classList.add('hidden');
                document.getElementById('overwrite-modal-instance-name').textContent = document.getElementById('delete-modal-instance-name').textContent;
                overwriteModal.classList.remove('hidden');
                return;
            }
            if (!response.ok) throw new Error((await response.json()).detail);
            hideAllModals();
            await fetchAndRenderInstances();
        } catch (error) { alert(`Error: ${error.message}`); hideAllModals(); }
    }

    deleteModal.addEventListener('click', (e) => {
        const action = e.target.id;
        if (action === 'delete-btn-cancel') hideAllModals();
        else if (action === 'delete-btn-trash') handleDelete({ mode: 'trash', overwrite: false });
        else if (action === 'delete-btn-permanent') handleDelete({ mode: 'permanent', overwrite: false });
    });

    overwriteModal.addEventListener('click', (e) => {
        const action = e.target.id;
        if (action === 'overwrite-btn-cancel') hideAllModals();
        else if (action === 'overwrite-btn-confirm') handleDelete({ mode: 'trash', overwrite: true });
    });

    async function initializeApp() {
        await fetchSystemInfo();
        await fetchAndStoreBlueprints();
        await fetchAndRenderInstances();
        updateSystemStats();
        showWelcomeScreen();
        if (instancesPollInterval) clearInterval(instancesPollInterval);
        instancesPollInterval = setInterval(fetchAndRenderInstances, 2000);
        setInterval(updateSystemStats, 2000);

        toolsCloseBtn.addEventListener('click', showWelcomeScreen);

        new Sortable(instancesTbody, {
            animation: 150, handle: '.drag-handle', ghostClass: 'sortable-ghost', dragClass: 'sortable-drag',
            onEnd: function (evt) {
                const rows = instancesTbody.querySelectorAll('tr[data-id]');
                const newOrder = Array.from(rows).map(row => row.dataset.id).filter(id => id && id !== 'new');
                localStorage.setItem(INSTANCE_ORDER_KEY, JSON.stringify(newOrder));
            },
        });
    }

    const cpuProgress = document.getElementById('cpu-progress'); const cpuPercentText = document.getElementById('cpu-percent-text'); const ramProgress = document.getElementById('ram-progress'); const ramUsageText = document.getElementById('ram-usage-text'); const gpuStatsContainer = document.getElementById('gpu-stats-container'); const gpuStatTemplate = document.getElementById('gpu-stat-template'); function formatBytes(bytes, decimals = 2) { if (bytes === 0) return '0 Bytes'; const k = 1024; const dm = decimals < 0 ? 0 : decimals; const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']; const i = Math.floor(Math.log(bytes) / Math.log(k)); return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]; } async function updateSystemStats() { try { const response = await fetch('/api/system/stats'); if (!response.ok) return; const stats = await response.json(); cpuProgress.style.width = `${stats.cpu_percent}%`; cpuPercentText.textContent = `${stats.cpu_percent.toFixed(1)}%`; ramProgress.style.width = `${stats.ram.percent}%`; ramUsageText.textContent = `${formatBytes(stats.ram.used)} / ${formatBytes(stats.ram.total)}`; gpuStatsContainer.innerHTML = ''; if (stats.gpus && stats.gpus.length > 0) { stats.gpus.forEach(gpu => { const gpuEl = gpuStatTemplate.content.cloneNode(true); gpuEl.querySelector('.gpu-name').textContent = `GPU ${gpu.id}: ${gpu.name}`; gpuEl.querySelector('.vram-progress').style.width = `${gpu.vram.percent}%`; gpuEl.querySelector('.vram-usage-text').textContent = `${formatBytes(gpu.vram.used)} / ${formatBytes(gpu.vram.total)}`; gpuEl.querySelector('.util-progress').style.width = `${gpu.utilization_percent}%`; gpuEl.querySelector('.util-percent-text').textContent = `${gpu.utilization_percent}%`; gpuStatsContainer.appendChild(gpuEl); }); } else { gpuStatsContainer.innerHTML = '<p style="text-align:center;color:#aaa;">No NVIDIA GPUs detected.</p>'; } } catch (error) { console.warn("Could not fetch system stats:", error); } }

    initializeApp();

    const SPLIT_STORAGE_KEY = 'aikoreSplitSizes';
    let savedSizes = { vertical: [60, 40], horizontal: [65, 35] };
    try { const storedSizes = localStorage.getItem(SPLIT_STORAGE_KEY); if (storedSizes) { const parsedSizes = JSON.parse(storedSizes); if (parsedSizes.vertical && parsedSizes.horizontal) { savedSizes = parsedSizes; } } } catch (e) { console.error("Failed to load or parse split sizes from localStorage.", e); }
    Split(['#instance-pane', '#bottom-split'], { sizes: savedSizes.vertical, minSize: [200, 150], gutterSize: 5, direction: 'vertical', cursor: 'row-resize', onDragEnd: function (sizes) { savedSizes.vertical = sizes; localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(savedSizes)); } });
    Split(['#tools-pane', '#monitoring-pane'], { sizes: savedSizes.horizontal, minSize: [300, 200], gutterSize: 5, direction: 'horizontal', cursor: 'col-resize', onDragEnd: function (sizes) { savedSizes.horizontal = sizes; localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(savedSizes)); } });

    viewResizeObserver = new ResizeObserver(() => { if (instanceIframe && instanceIframe.contentWindow) { instanceIframe.contentWindow.dispatchEvent(new Event('resize')); } });

    const toolsPane = document.getElementById('tools-pane');
    const resizeObserver = new ResizeObserver(() => { if (fitAddon) { try { fitAddon.fit(); } catch (e) { } } });
    resizeObserver.observe(toolsPane);
});