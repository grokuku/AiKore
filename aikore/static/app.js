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
    // NEW: Terminal elements
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

    // NEW: Terminal state variables
    let currentTerminal = null;
    let currentTerminalSocket = null;
    let fitAddon = null;

    let instancesPollInterval = null;

    // NEW: Centralized function to close the terminal connection
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

    // NEW: Centralized function to hide all views in the tools pane
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

    function checkRowForChanges(row) {
        const updateButton = row.querySelector('button[data-action="update"]');
        if (!updateButton) return;
        const nameField = row.querySelector('input[data-field="name"]');
        const gpuIdsField = row.querySelector('input[data-field="gpu_ids"]');
        const autostartField = row.querySelector('input[data-field="autostart"]');
        const persistentModeField = row.querySelector('input[data-field="persistent_mode"]');
        let changed = false;
        if (nameField.value !== row.dataset.originalName) changed = true;
        if (gpuIdsField.value !== row.dataset.originalGpuIds) changed = true;
        if (autostartField.checked.toString() !== row.dataset.originalAutostart) changed = true;
        if (persistentModeField.checked.toString() !== row.dataset.originalPersistentMode) changed = true;
        updateButton.disabled = !changed;
    }

    function updateInstanceRow(row, instance) {
        const isStarted = instance.status === 'started';
        const isStopped = instance.status === 'stopped';
        const isActive = !isStopped;

        row.dataset.status = instance.status; // Store status for context menu

        const statusSpan = row.querySelector('.status');
        statusSpan.textContent = instance.status;
        statusSpan.className = `status status-${instance.status.toLowerCase()}`;
        row.cells[6].textContent = instance.port || 'N/A';
        row.querySelector('[data-action="start"]').disabled = isActive;
        row.querySelector('[data-action="stop"]').disabled = isStopped;
        // CORRECTED: The main tools button is no longer disabled here.
        // row.querySelector('[data-action="tools_menu"]').disabled = isActive;
        row.querySelector('[data-action="delete"]').disabled = isActive;
        const openButton = row.querySelector('[data-action="open"]');
        if (isStarted) {
            openButton.href = `/app/${instance.name}/`;
            openButton.classList.remove('disabled');
        } else {
            openButton.href = '#';
            openButton.classList.add('disabled');
        }
        const viewButton = row.querySelector('[data-action="view"]');
        viewButton.disabled = !isStarted;
        checkRowForChanges(row);
    }

    function renderInstanceRow(instance, isNew = false) {
        const row = document.createElement('tr');
        row.dataset.id = instance.id;
        row.dataset.isNew = String(isNew);
        row.dataset.status = instance.status; // Store status for context menu
        row.dataset.originalName = instance.name || '';
        row.dataset.originalBlueprint = instance.base_blueprint || '';
        row.dataset.originalGpuIds = instance.gpu_ids || '';
        row.dataset.originalAutostart = String(instance.autostart);
        row.dataset.originalPersistentMode = String(instance.persistent_mode);
        const isStarted = instance.status === 'started';
        const isStopped = instance.status === 'stopped';
        const isActive = !isStopped;
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
        row.insertCell().innerHTML = `<span class="status status-${instance.status.toLowerCase()}">${instance.status}</span>`;
        row.insertCell().textContent = instance.port || 'N/A';
        const actionsCell = row.insertCell();
        actionsCell.classList.add('actions-column');
        if (isNew) {
            actionsCell.innerHTML = `
                <button class="action-btn" data-action="save" data-id="new" disabled>Save</button>
                <button class="action-btn" data-action="cancel_new">Cancel</button>
                <button class="action-btn" data-action="logs" disabled>Logs</button>
                <button class="action-btn" data-action="tools_menu" disabled>Tools</button>
                <button class="action-btn" data-action="update" disabled>Update</button>
                <button class="action-btn" data-action="delete" disabled>Delete</button>
                <button class="action-btn" data-action="view" disabled>View</button>
                <a href="#" class="action-btn disabled" data-action="open">Open</a>`;
        } else {
            actionsCell.innerHTML = `
                <button class="action-btn" data-action="start" data-id="${instance.id}" ${isActive ? 'disabled' : ''}>Start</button>
                <button class="action-btn" data-action="stop" data-id="${instance.id}" ${isStopped ? 'disabled' : ''}>Stop</button>
                <button class="action-btn" data-action="logs" data-id="${instance.id}">Logs</button>
                <button class="action-btn" data-action="tools_menu" data-id="${instance.id}">Tools</button>
                <button class="action-btn" data-action="update" data-id="${instance.id}" disabled>Update</button>
                <button class="action-btn" data-action="delete" data-id="${instance.id}" ${isActive ? 'disabled' : ''}>Delete</button>
                <button class="action-btn" data-action="view" data-id="${instance.id}" ${!isStarted ? 'disabled' : ''}>View</button>
                <a href="${isStarted ? `/app/${instance.name}/` : '#'}" class="action-btn ${!isStarted ? 'disabled' : ''}" data-action="open" data-id="${instance.id}" target="_blank">Open</a>`;
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

    async function fetchAndRenderInstances() {
        try {
            const response = await fetch('/api/instances/');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const instances = await response.json();
            const existingRows = new Map([...instancesTbody.querySelectorAll('tr[data-id]')].map(row => [row.dataset.id, row]));
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
            for (const row of existingRows.values()) {
                if (row.dataset.isNew !== 'true') row.remove();
            }
            if (instancesTbody.childElementCount === 0 && !document.querySelector('tr[data-is-new="true"]')) {
                instancesTbody.innerHTML = `<tr class="no-instances-row"><td colspan="8" style="text-align: center;">No instances created yet.</td></tr>`;
            }
        } catch (error) {
            console.error("Failed to fetch instances:", error);
            if (instancesPollInterval) clearInterval(instancesPollInterval);
            instancesTbody.innerHTML = `<tr><td colspan="8" style="text-align:center;">Error loading data. Check console.</td></tr>`;
        }
    }

    function addNewInstanceRow() {
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

    function openInstanceView(instanceName) {
        hideAllToolViews();
        instanceViewContainer.classList.remove('hidden');
        toolsPaneTitle.textContent = `View: ${instanceName}`;
        instanceIframe.src = `/app/${instanceName}/`;
    }

    function openTerminal(instanceId, instanceName) {
        hideAllToolViews();

        terminalViewContainer.classList.remove('hidden');
        toolsPaneTitle.textContent = `Terminal: ${instanceName}`;

        currentTerminal = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            fontFamily: 'Courier New, Courier, monospace',
            theme: {
                background: '#111111',
                foreground: '#e0e0e0',
                cursor: '#e0e0e0',
            }
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
            currentTerminal.onData(data => {
                if (currentTerminalSocket && currentTerminalSocket.readyState === WebSocket.OPEN) {
                    currentTerminalSocket.send(data);
                }
            });
        };

        currentTerminalSocket.onmessage = (event) => {
            // CORRECTED: The typo Uint8_Array is now Uint8Array
            currentTerminal.write(new Uint8Array(event.data));
        };

        currentTerminalSocket.onclose = (event) => {
            const reason = event.reason ? `: ${event.reason}` : '';
            currentTerminal.write(`\r\n\r\n\x1b[31m[CONNECTION CLOSED]\x1b[0m Code: ${event.code}${reason}\r\n`);
        };

        currentTerminalSocket.onerror = (error) => {
            currentTerminal.write('\r\n\x1b[31m[WEBSOCKET CONNECTION ERROR]\x1b[0m\r\n');
            console.error('WebSocket Error:', error);
        };
    }

    editorSaveBtn.addEventListener('click', saveFileContent);
    editorExitBtn.addEventListener('click', exitEditor);

    function showToolsMenu(buttonEl) {
        const row = buttonEl.closest('tr');
        const status = row.dataset.status;
        const isStopped = status === 'stopped';

        // Set disabled state of menu items based on instance status
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

    instancesTbody.addEventListener('click', async (event) => {
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

        if (action === 'start' || action === 'stop') {
            target.disabled = true;
            try {
                const response = await fetch(`/api/instances/${instanceId}/${action}`, { method: 'POST' });
                if (!response.ok) throw new Error((await response.json()).detail);
                await fetchAndRenderInstances();
            } catch (error) {
                alert(`Error: ${error.message}`);
                await fetchAndRenderInstances();
            }
        } else if (action === 'save') {
            const data = {
                name: row.querySelector('input[data-field="name"]').value,
                base_blueprint: row.querySelector('select[data-field="base_blueprint"]').value,
                gpu_ids: row.querySelector('input[data-field="gpu_ids"]').value || null,
                autostart: row.querySelector('input[data-field="autostart"]').checked,
                persistent_mode: row.querySelector('input[data-field="persistent_mode"]').checked,
            };
            try {
                const response = await fetch('/api/instances/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
                if (!response.ok) throw new Error((await response.json()).detail);
                row.remove();
                await fetchAndRenderInstances();
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        } else if (action === 'update') {
            alert('Update functionality is the next logical step to implement!');
        } else if (action === 'delete') {
            if (confirm('Are you sure you want to delete this instance?')) {
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
            toolsPaneTitle.textContent = `Logs: ${row.querySelector('[data-field="name"]').value || row.dataset.originalName}`;
            logContentArea.textContent = 'Loading logs...';
            activeLogInstanceId = instanceId;
            logSize = 0;
            const fetchLogs = async () => {
                if (!activeLogInstanceId) return;
                try {
                    const url = `/api/instances/${activeLogInstanceId}/logs?offset=${logSize}`;
                    const response = await fetch(url);
                    if (!response.ok) throw new Error('Instance stopped or logs unavailable.');
                    const data = await response.json();
                    const isScrolledToBottom = logViewerContainer.scrollHeight - logViewerContainer.scrollTop <= logViewerContainer.clientHeight + 2;
                    if (data.content) {
                        if (logContentArea.textContent === 'Loading logs...') logContentArea.textContent = '';
                        logContentArea.appendChild(document.createTextNode(data.content));
                        logSize = data.size;
                        if (isScrolledToBottom) logViewerContainer.scrollTop = logViewerContainer.scrollHeight;
                    }
                } catch (error) {
                    clearInterval(activeLogInterval);
                    activeLogInstanceId = null;
                }
            };
            fetchLogs();
            activeLogInterval = setInterval(fetchLogs, 2000);
        } else if (action === 'view') {
            openInstanceView(row.querySelector('[data-field="name"]').value || row.dataset.originalName);
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
    function formatBytes(bytes, decimals = 2) { if (bytes === 0) return '0 Bytes'; const k = 1024; const dm = decimals < 0 ? 0 : decimals; const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']; const i = Math.floor(Math.log(bytes) / Math.log(k)); return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]; }
    async function updateSystemStats() { try { const response = await fetch('/api/system/stats'); if (!response.ok) return; const stats = await response.json(); cpuProgress.style.width = `${stats.cpu_percent}%`; cpuPercentText.textContent = `${stats.cpu_percent.toFixed(1)}%`; ramProgress.style.width = `${stats.ram.percent}%`; ramUsageText.textContent = `${formatBytes(stats.ram.used)} / ${formatBytes(stats.ram.total)}`; gpuStatsContainer.innerHTML = ''; if (stats.gpus && stats.gpus.length > 0) { stats.gpus.forEach(gpu => { const gpuEl = gpuStatTemplate.content.cloneNode(true); gpuEl.querySelector('.gpu-name').textContent = `GPU ${gpu.id}: ${gpu.name}`; gpuEl.querySelector('.vram-progress').style.width = `${gpu.vram.percent}%`; gpuEl.querySelector('.vram-usage-text').textContent = `${formatBytes(gpu.vram.used)} / ${formatBytes(gpu.vram.total)}`; gpuEl.querySelector('.util-progress').style.width = `${gpu.utilization_percent}%`; gpuEl.querySelector('.util-percent-text').textContent = `${gpu.utilization_percent}%`; gpuStatsContainer.appendChild(gpuEl); }); } else { gpuStatsContainer.innerHTML = '<p style="text-align:center;color:#aaa;">No NVIDIA GPUs detected.</p>'; } } catch (error) { console.warn("Could not fetch system stats:", error); } }

    initializeApp();

    const SPLIT_STORAGE_KEY = 'aikoreSplitSizes';
    let savedSizes = { vertical: [60, 40], horizontal: [65, 35] };
    try {
        const storedSizes = localStorage.getItem(SPLIT_STORAGE_KEY);
        if (storedSizes) {
            const parsedSizes = JSON.parse(storedSizes);
            if (parsedSizes.vertical && parsedSizes.horizontal) {
                savedSizes = parsedSizes;
            }
        }
    } catch (e) {
        console.error("Failed to load or parse split sizes from localStorage.", e);
    }
    const verticalSplit = Split(['#instance-pane', '#bottom-split'], {
        sizes: savedSizes.vertical,
        minSize: [200, 150],
        gutterSize: 5,
        direction: 'vertical',
        cursor: 'row-resize',
        onDragEnd: function (sizes) {
            savedSizes.vertical = sizes;
            localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(savedSizes));
        }
    });
    const horizontalSplit = Split(['#tools-pane', '#monitoring-pane'], {
        sizes: savedSizes.horizontal,
        minSize: [300, 200],
        gutterSize: 5,
        direction: 'horizontal',
        cursor: 'col-resize',
        onDragEnd: function (sizes) {
            savedSizes.horizontal = sizes;
            localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(savedSizes));
        }
    });

    // NEW: Resize observer for terminal
    const toolsPane = document.getElementById('tools-pane');
    const resizeObserver = new ResizeObserver(() => {
        if (fitAddon) {
            try {
                // This can sometimes throw an error if the terminal isn't fully visible
                // when the pane is first rendered. A try/catch block makes it robust.
                fitAddon.fit();
            } catch (e) {
                // We can safely ignore these errors.
            }
        }
    });
    resizeObserver.observe(toolsPane);
});