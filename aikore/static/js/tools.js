import { state, DOM } from './state.js';
import { fetchLogs, performVersionCheck, fetchFileContent, fetchTorchVersions } from './api.js';
import { showToast } from './ui.js';

const ansi_up = new AnsiUp();

function hideAllToolViews() {
    [
        DOM.welcomeScreenContainer,
        DOM.logViewerContainer,
        DOM.editorContainer,
        DOM.instanceViewContainer,
        DOM.terminalViewContainer,
        DOM.versionCheckContainer
    ].forEach(el => el.classList.add('hidden'));

    const builderContainer = document.getElementById('builder-container');
    if (builderContainer) builderContainer.classList.add('hidden');

    const wheelsMgr = document.getElementById('wheels-manager-container');
    if (wheelsMgr) wheelsMgr.classList.add('hidden');

    DOM.toolsCloseBtn.classList.add('hidden');

    DOM.instanceIframe.src = 'about:blank';
    DOM.welcomeIframe.src = 'about:blank';

    clearInterval(state.activeLogInterval);
    state.activeLogInstanceId = null;

    closeTerminal();
    closeBuilderTerminal();

    if (state.viewResizeObserver) {
        state.viewResizeObserver.disconnect();
    }
}

// --- BUILDER LOGIC ---

let builderSocket = null;
let builderTerminal = null;
let builderFitAddon = null;
let builderBtnInterval = null;
let builderResizeObserver = null;

async function fetchBuilderInfo() {
    const res = await fetch('/api/builder/info');
    return await res.json();
}

// CHANGED: Now uses the centralized API call and caching mechanism
async function populateTorchVersions() {
    const cudaSelect = document.getElementById('builder-cuda');
    const torchSelect = document.getElementById('builder-torch');

    if (!cudaSelect || !torchSelect) return;

    const cudaVer = cudaSelect.value;
    torchSelect.innerHTML = '<option>Loading...</option>';
    torchSelect.disabled = true;

    try {
        // Check cache first
        let versions = state.versions.torchCache[cudaVer];
        if (!versions) {
            versions = await fetchTorchVersions(cudaVer);
            state.versions.torchCache[cudaVer] = versions;
        }

        torchSelect.innerHTML = '';

        if (!versions || versions.length === 0) {
            const opt = document.createElement('option');
            opt.textContent = "Error: No versions found";
            torchSelect.appendChild(opt);
        } else {
            versions.forEach((v, index) => {
                const opt = document.createElement('option');
                opt.value = v;
                opt.textContent = index === 0 ? `${v} (Latest)` : v;
                torchSelect.appendChild(opt);
            });
            torchSelect.selectedIndex = 0; // Default to newest
        }
    } catch (e) {
        console.error(e);
        torchSelect.innerHTML = '<option value="2.5.1">2.5.1 (Fallback)</option>';
    } finally {
        torchSelect.disabled = false;
    }
}

export async function renderBuilderStatus() {
    const btn = document.getElementById('btn-open-builder');
    if (!btn) return;

    try {
        const info = await fetchBuilderInfo();
        const isBuilding = info.status === 'building' || info.is_building === true;

        if (isBuilding) {
            if (btn.textContent === "Build Module") {
                btn.textContent = "BUILDING...";
            }
            btn.style.backgroundColor = "#e67e22";
            btn.style.borderColor = "#e67e22";
        } else {
            btn.textContent = "Build Module";
            btn.style.backgroundColor = "#6f42c1";
            btn.style.borderColor = "#6f42c1";
        }
    } catch (e) {
        // Silent fail
    }
}

async function fetchWheelsList() {
    const res = await fetch('/api/builder/wheels');
    return await res.json();
}

async function deleteWheel(filename) {
    if (!confirm(`Delete ${filename}?`)) return;
    await fetch(`/api/builder/wheels/${filename}`, { method: 'DELETE' });
    renderWheelsTable();
}

function downloadWheel(filename) {
    window.open(`/api/builder/wheels/${filename}/download`, '_blank');
}

async function renderWheelsTable() {
    const tbody = document.getElementById('wheels-table-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7">Loading...</td></tr>';

    try {
        const wheels = await fetchWheelsList();
        tbody.innerHTML = '';
        if (wheels.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#666;">No wheels built yet.</td></tr>';
            return;
        }

        wheels.forEach(w => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td title="${w.filename}">${w.filename}</td>
                <td>${w.cuda_arch}</td>
                <td>${w.cuda_ver || 'N/A'}</td>
                <td>${w.torch_ver || 'N/A'}</td>
                <td>${w.size_mb} MB</td>
                <td>${w.created_at}</td>
                <td class="wheel-actions">
                    <button class="btn-icon btn-download" title="Download">⬇</button>
                    <button class="btn-icon btn-delete" title="Delete">🗑</button>
                </td>
            `;
            tr.querySelector('.btn-delete').onclick = () => deleteWheel(w.filename);
            tr.querySelector('.btn-download').onclick = () => downloadWheel(w.filename);

            tbody.appendChild(tr);
        });
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" style="color:red">Error loading wheels</td></tr>`;
    }
}

function closeBuilderTerminal() {
    if (builderSocket) {
        builderSocket.close();
        builderSocket = null;
    }
    if (builderTerminal) {
        builderTerminal.dispose();
        builderTerminal = null;
        builderFitAddon = null;
    }
    if (builderResizeObserver) {
        builderResizeObserver.disconnect();
        builderResizeObserver = null;
    }

    if (builderBtnInterval) {
        clearInterval(builderBtnInterval);
        builderBtnInterval = null;
        const btn = document.getElementById('btn-start-build');
        if (btn) {
            btn.disabled = false;
            btn.textContent = "BUILD MODULE";
        }
    }
}

function initBuilderTerminal() {
    const container = document.getElementById('builder-terminal');
    container.innerHTML = '';

    builderTerminal = new Terminal({
        cursorBlink: false,
        disableStdin: true,
        fontSize: 12,
        fontFamily: 'Courier New, Courier, monospace',
        theme: { background: '#000000', foreground: '#e0e0e0' },
        convertEol: true
    });

    builderFitAddon = new FitAddon.FitAddon();
    builderTerminal.loadAddon(builderFitAddon);
    builderTerminal.open(container);
    builderFitAddon.fit();

    builderResizeObserver = new ResizeObserver(() => {
        if (builderFitAddon) {
            try { builderFitAddon.fit(); } catch (e) { }
        }
    });
    builderResizeObserver.observe(container);
}

function initTableResizers() {
    const table = document.querySelector('.wheels-table');
    if (!table) return;

    const headers = table.querySelectorAll('th');[1, 2, 3, 4, 5].forEach(index => {
        const th = headers[index];
        if (!th || th.querySelector('.resizer')) return;

        const resizer = document.createElement('div');
        resizer.classList.add('resizer');
        th.appendChild(resizer);
        createResizableColumn(th, resizer);
    });
}

function createResizableColumn(th, resizer) {
    let startX, startWidth;

    const onMouseDown = (e) => {
        e.preventDefault();
        startX = e.pageX;
        startWidth = th.offsetWidth;

        resizer.classList.add('resizing');

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    };

    const onMouseMove = (e) => {
        const diffX = e.pageX - startX;
        const newWidth = startWidth - diffX;

        if (newWidth > 30) {
            th.style.width = `${newWidth}px`;
        }
    };

    const onMouseUp = () => {
        resizer.classList.remove('resizing');
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    };

    resizer.addEventListener('mousedown', onMouseDown);
}

async function startBuild() {
    const presetSelect = document.getElementById('builder-preset');
    const archSelect = document.getElementById('builder-arch');
    const pythonSelect = document.getElementById('builder-python');
    const cudaSelect = document.getElementById('builder-cuda');
    const torchSelect = document.getElementById('builder-torch');
    const customUrlInput = document.getElementById('builder-custom-url');
    const btn = document.getElementById('btn-start-build');

    const payload = {
        preset: presetSelect.value,
        arch: archSelect.value,
        git_url: customUrlInput.value,
        python_ver: pythonSelect.value,
        cuda_ver: cudaSelect.value,
        torch_ver: torchSelect.value
    };

    btn.disabled = true;

    let dots = 0;
    btn.textContent = "BUILDING";
    builderBtnInterval = setInterval(() => {
        dots = (dots + 1) % 4;
        btn.textContent = "BUILDING" + ".".repeat(dots);
    }, 500);

    if (builderTerminal) builderTerminal.clear();
    else initBuilderTerminal();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    builderSocket = new WebSocket(`${protocol}//${window.location.host}/api/builder/build`);

    builderSocket.onopen = () => {
        builderSocket.send(JSON.stringify(payload));
    };

    builderSocket.onmessage = (event) => {
        builderTerminal.write(event.data);
    };

    builderSocket.onclose = () => {
        if (builderBtnInterval) {
            clearInterval(builderBtnInterval);
            builderBtnInterval = null;
        }
        btn.disabled = false;
        btn.textContent = "BUILD MODULE";
        renderWheelsTable();
    };
}

export async function showBuilderView() {
    hideAllToolViews();

    let container = document.getElementById('builder-container');
    if (!container) {

        // --- NEW: Dynamic Options Generation ---
        // Python Options
        const pyOptionsHtml = state.versions.python.map((v, i) =>
            `<option value="${v}">${v}${i === 0 ? ' (Latest)' : ''}</option>`
        ).join('');

        // CUDA Options
        // We expect state.versions.cuda to be like["13.0", "12.8", "12.6", ...]
        // But builder expects "cu130"
        const cudaOptionsHtml = state.versions.cuda.map((v, i) => {
            const cuFormat = 'cu' + v.replace('.', '');
            return `<option value="${cuFormat}">CUDA ${v}${i === 0 ? ' (Latest)' : ''}</option>`;
        }).join('');

        const html = `
        <div id="builder-container">
            <div id="builder-top-pane">
                <div id="builder-options">
                    
                    <div class="builder-field">
                        <label>Module Preset</label>
                        <select id="builder-preset"></select>
                    </div>
                    
                    <div class="builder-field">
                        <label>Python Version</label>
                        <select id="builder-python">
                            ${pyOptionsHtml}
                        </select>
                    </div>

                    <div class="builder-field" id="builder-field-custom" style="display:none;">
                        <label>Git URL / Package Name</label>
                        <input type="text" id="builder-custom-url" placeholder="https://github.com/user/repo.git">
                    </div>

                    <div class="builder-field">
                        <label>PyTorch Version (Dynamically Fetched)</label>
                        <select id="builder-torch">
                            <option>Loading...</option>
                        </select>
                    </div>

                    <div class="builder-field">
                        <label>PyTorch CUDA Version</label>
                        <select id="builder-cuda">
                            ${cudaOptionsHtml}
                        </select>
                    </div>
                    
                    <div class="builder-field">
                        <label>
                            Target GPU Architecture 
                            <a href="https://developer.nvidia.com/cuda/gpus" target="_blank" class="builder-info-link" title="Lookup GPU Compute Capability">(List)</a>
                        </label>
                        <select id="builder-arch">
                            <option value="12.0">12.0 (Blackwell - RTX 5090, B200)</option>
                            <option value="9.0">9.0 (Hopper - H100)</option>
                            <option value="8.9">8.9 (Ada Lovelace - RTX 4090, L40)</option>
                            <option value="8.6">8.6 (Ampere - RTX 3090, A40, A10)</option>
                            <option value="8.0">8.0 (Ampere - A100)</option>
                            <option value="7.5">7.5 (Turing - RTX 2080, T4)</option>
                            <option value="7.0">7.0 (Volta - V100)</option>
                            <option value="6.1">6.1 (Pascal - GTX 1080, Tesla P4)</option>
                        </select>
                    </div>

                    <div class="builder-field build-btn-container">
                        <button id="btn-start-build">BUILD MODULE</button>
                    </div>

                </div>
                <div id="builder-wheels">
                    <div style="padding:0.5rem; background:#252545; color:#fff; font-weight:bold; border-bottom:1px solid #444;">Available Wheels</div>
                    <div id="wheels-table-container">
                        <table class="wheels-table">
                            <thead>
                                <tr>
                                    <th>Filename</th>
                                    <th>Arch</th>
                                    <th>CUDA</th>
                                    <th>Torch</th>
                                    <th>Size</th>
                                    <th>Date</th>
                                    <th>Act</th>
                                </tr>
                            </thead>
                            <tbody id="wheels-table-body"></tbody>
                        </table>
                    </div>
                </div>
            </div>
            <div id="builder-logs">
                <div id="builder-logs-header">Build Logs output</div>
                <div id="builder-terminal"></div>
            </div>
        </div>
        `;
        DOM.logViewerContainer.insertAdjacentHTML('afterend', html);
        container = document.getElementById('builder-container');

        document.getElementById('btn-start-build').addEventListener('click', startBuild);
        document.getElementById('builder-preset').addEventListener('change', (e) => {
            const isCustom = e.target.value === 'custom';
            document.getElementById('builder-field-custom').style.display = isCustom ? 'flex' : 'none';
        });

        const cudaSelect = document.getElementById('builder-cuda');
        cudaSelect.addEventListener('change', populateTorchVersions);

        initTableResizers();
    }

    container.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = "Tools / Module Builder";

    const info = await fetchBuilderInfo();

    const presetSelect = document.getElementById('builder-preset');
    presetSelect.innerHTML = '';
    for (const [key, val] of Object.entries(info.presets)) {
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = val.label;
        presetSelect.appendChild(opt);
    }

    const archSelect = document.getElementById('builder-arch');
    if (!archSelect.querySelector('option[value="auto"]')) {
        const autoOpt = document.createElement('option');
        autoOpt.value = info.detected_arch;
        autoOpt.textContent = `Auto-Detect (${info.detected_arch}) - Recommended`;
        autoOpt.selected = true;
        archSelect.prepend(autoOpt);
    }

    await populateTorchVersions();

    renderWheelsTable();
    initBuilderTerminal();
}

// --- INSTANCE WHEELS MANAGER ---

let currentWheelsData = [];

export async function showInstanceWheelsManager(instanceId, instanceName) {
    hideAllToolViews();

    let container = document.getElementById('wheels-manager-container');
    if (!container) {
        const html = `
        <div id="wheels-manager-container" class="tools-view-container">
            <div class="toolbar-header">
                <div class="toolbar-info">
                    Select compiled modules to include in this instance. 
                    Files will be copied to <code>/wheels</code> folder.
                </div>
                <div class="toolbar-actions">
                    <button id="btn-wheels-refresh" class="btn-secondary" style="padding: 0.5rem 1rem; cursor:pointer;">Refresh</button>
                    <button id="btn-wheels-apply" class="btn-primary" style="padding: 0.5rem 1rem; background-color:#28a745; color:white; border:none; font-weight:bold; border-radius:4px; cursor:pointer;">APPLY CHANGES</button>
                </div>
            </div>
            <div class="wheels-manager-columns">
                <!-- Available Column -->
                <div class="wheels-column">
                    <h3>Available Wheels (Global)</h3>
                    <div class="table-container">
                        <table class="manager-table">
                            <thead>
                                <tr>
                                    <th>Filename</th>
                                    <th>Size</th>
                                    <th>Act</th>
                                </tr>
                            </thead>
                            <tbody id="wheels-available-body"></tbody>
                        </table>
                    </div>
                </div>
                <!-- Installed Column -->
                <div class="wheels-column">
                    <h3>Installed in Instance</h3>
                    <div class="table-container">
                        <table class="manager-table">
                            <thead>
                                <tr>
                                    <th>Filename</th>
                                    <th>Size</th>
                                    <th>Act</th>
                                </tr>
                            </thead>
                            <tbody id="wheels-installed-body"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        `;
        DOM.logViewerContainer.insertAdjacentHTML('afterend', html);
        container = document.getElementById('wheels-manager-container');

        // Event Listeners attached ONCE
        document.getElementById('btn-wheels-refresh').addEventListener('click', () => loadInstanceWheels(state.currentWheelsInstanceId));
        document.getElementById('btn-wheels-apply').addEventListener('click', () => saveInstanceWheels(state.currentWheelsInstanceId));
    }

    state.currentWheelsInstanceId = instanceId;

    container.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = `Manage Wheels: ${instanceName}`;

    await loadInstanceWheels(instanceId);
}

async function loadInstanceWheels(instanceId) {
    document.getElementById('wheels-available-body').innerHTML = '<tr><td colspan="3" style="text-align:center">Loading...</td></tr>';
    document.getElementById('wheels-installed-body').innerHTML = '<tr><td colspan="3" style="text-align:center">Loading...</td></tr>';

    try {
        const res = await fetch(`/api/instances/${instanceId}/wheels`);
        if (!res.ok) throw new Error("Failed to fetch");
        currentWheelsData = await res.json();

        renderManagerTables();

    } catch (e) {
        document.getElementById('wheels-available-body').innerHTML = `<tr><td colspan="3" style="color:red">Error: ${e.message}</td></tr>`;
        document.getElementById('wheels-installed-body').innerHTML = `<tr><td colspan="3" style="color:red">Error: ${e.message}</td></tr>`;
    }
}

// Function exposed to window to handle button clicks inside dynamically created HTML
window.toggleWheelState = function (filename, install) {
    const wheel = currentWheelsData.find(w => w.filename === filename);
    if (wheel) {
        wheel.installed = install;
        renderManagerTables();
    }
};

function renderManagerTables() {
    const availableBody = document.getElementById('wheels-available-body');
    const installedBody = document.getElementById('wheels-installed-body');

    availableBody.innerHTML = '';
    installedBody.innerHTML = '';

    const availableWheels = currentWheelsData.filter(w => !w.installed);
    const installedWheels = currentWheelsData.filter(w => w.installed);

    if (availableWheels.length === 0) {
        availableBody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:#888;">No global wheels available.</td></tr>';
    } else {
        availableWheels.forEach(w => {
            availableBody.innerHTML += `
                <tr>
                    <td title="${w.filename}">${w.filename}</td>
                    <td style="text-align:right;">${w.size_mb} MB</td>
                    <td class="action-cell">
                        <button class="btn-action install" onclick="window.toggleWheelState('${w.filename}', true)" title="Install">➕</button>
                    </td>
                </tr>
            `;
        });
    }

    if (installedWheels.length === 0) {
        installedBody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:#888;">No wheels currently installed.</td></tr>';
    } else {
        installedWheels.forEach(w => {
            installedBody.innerHTML += `
                <tr>
                    <td title="${w.filename}">${w.filename}</td>
                    <td style="text-align:right;">${w.size_mb} MB</td>
                    <td class="action-cell">
                        <button class="btn-action remove" onclick="window.toggleWheelState('${w.filename}', false)" title="Remove">❌</button>
                    </td>
                </tr>
            `;
        });
    }
}

async function saveInstanceWheels(instanceId) {
    const btn = document.getElementById('btn-wheels-apply');

    // Filter current state to get only the installed ones
    const filenames = currentWheelsData.filter(w => w.installed).map(w => w.filename);

    btn.disabled = true;
    btn.textContent = "SYNCING...";

    try {
        const res = await fetch(`/api/instances/${instanceId}/wheels`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filenames })
        });

        if (res.ok) {
            showToast("Wheels synchronized successfully", "success");
            await loadInstanceWheels(instanceId); // Reload to reflect actual server state
        } else {
            const err = await res.json();
            showToast(`Error: ${err.detail}`, "error");
        }
    } catch (e) {
        showToast(`Sync failed: ${e.message}`, "error");
    } finally {
        btn.disabled = false;
        btn.textContent = "APPLY CHANGES";
    }
}

export async function showVersionCheckView(instanceId, instanceName) {
    hideAllToolViews();
    DOM.versionCheckContainer.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = `Versions Check: ${instanceName}`;

    DOM.versionCheckVersionsArea.textContent = 'Running version checks...';
    DOM.versionCheckConflictsArea.textContent = 'Running dependency checks...';

    const data = await performVersionCheck(instanceId);
    DOM.versionCheckVersionsArea.textContent = data.versions;
    DOM.versionCheckConflictsArea.textContent = data.conflicts;
}

export function showWelcomeScreen() {
    hideAllToolViews();
    DOM.welcomeScreenContainer.classList.remove('hidden');
    DOM.welcomeIframe.src = '/static/welcome/index.html';
    DOM.toolsPaneTitle.textContent = 'Tools / Welcome';
}

export function exitEditor() {
    state.editorState = { instanceId: null, instanceName: null, fileType: null, baseBlueprint: null };
    if (state.codeEditor) {
        state.codeEditor.setValue('');
    }
    showWelcomeScreen();
}

export async function openEditor(instanceId, instanceName, fileType) {
    hideAllToolViews();
    DOM.editorContainer.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    const fileTypeName = fileType.charAt(0).toUpperCase() + fileType.slice(1);
    DOM.toolsPaneTitle.textContent = `Editing ${fileTypeName} for: ${instanceName}`;

    if (!state.codeEditor) {
        const textarea = document.getElementById('file-editor-textarea');
        state.codeEditor = CodeMirror.fromTextArea(textarea, {
            lineNumbers: true, mode: 'shell', theme: 'darcula',
            indentUnit: 4, smartIndent: true,
        });
    }

    state.codeEditor.setValue(`Loading ${fileType} content...`);
    setTimeout(() => state.codeEditor.refresh(), 1);

    const row = DOM.instancesTable.querySelector(`tr[data-id="${instanceId}"]`);
    const baseBlueprint = row ? row.dataset.originalBlueprint : null;
    state.editorState = { instanceId, instanceName, fileType, baseBlueprint };

    try {
        const content = await fetchFileContent(instanceId, fileType);
        state.codeEditor.setValue(content.content);
    } catch (error) {
        state.codeEditor.setValue(`[ERROR] Could not load file: ${error.message}`);
    }
}

export function openInstanceView(instanceName, url) {
    hideAllToolViews();
    DOM.instanceViewContainer.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = `View: ${instanceName}`;
    if (!url || url === '#') {
        DOM.instanceIframe.src = 'about:blank';
        return;
    }
    DOM.instanceIframe.src = url;
    if (state.viewResizeObserver) {
        state.viewResizeObserver.observe(DOM.instanceViewContainer);
    }
}

function closeTerminal() {
    if (state.currentTerminalSocket) {
        state.currentTerminalSocket.close();
        state.currentTerminalSocket = null;
    }
    if (state.currentTerminal) {
        state.currentTerminal.dispose();
        state.currentTerminal = null;
        state.fitAddon = null;
    }
}

export function openTerminal(instanceId, instanceName) {
    hideAllToolViews();
    DOM.terminalViewContainer.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = `Terminal: ${instanceName}`;
    state.currentTerminal = new Terminal({
        cursorBlink: true, fontSize: 14, fontFamily: 'Courier New, Courier, monospace',
        theme: { background: '#111111', foreground: '#e0e0e0', cursor: '#e0e0e0' }
    });
    state.fitAddon = new FitAddon.FitAddon();
    state.currentTerminal.loadAddon(state.fitAddon);
    DOM.terminalContent.innerHTML = '';
    state.currentTerminal.open(DOM.terminalContent);
    state.fitAddon.fit();
    state.currentTerminal.focus();
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/instances/${instanceId}/terminal`;
    state.currentTerminalSocket = new WebSocket(wsUrl);
    state.currentTerminalSocket.binaryType = 'arraybuffer';
    state.currentTerminalSocket.onopen = () => {
        const initialSize = { type: 'resize', cols: state.currentTerminal.cols, rows: state.currentTerminal.rows };
        state.currentTerminalSocket.send(JSON.stringify(initialSize));
        state.currentTerminal.onData(data => {
            if (state.currentTerminalSocket && state.currentTerminalSocket.readyState === WebSocket.OPEN) state.currentTerminalSocket.send(data);
        });
        state.currentTerminal.onResize(size => {
            if (state.currentTerminalSocket && state.currentTerminalSocket.readyState === WebSocket.OPEN) {
                state.currentTerminalSocket.send(JSON.stringify({ type: 'resize', cols: size.cols, rows: size.rows }));
            }
        });
    };
    state.currentTerminalSocket.onmessage = (event) => { state.currentTerminal.write(new Uint8Array(event.data)); };
    state.currentTerminalSocket.onclose = (event) => { state.currentTerminal.write(`\r\n\x1b[31m[CLOSED]\x1b[0m ${event.reason || ''}\r\n`); };
    state.currentTerminalSocket.onerror = (error) => { state.currentTerminal.write('\r\n\x1b[31m[ERROR]\x1b[0m\r\n'); };
}

export async function showLogViewer(instanceId, instanceName) {
    hideAllToolViews();
    DOM.logViewerContainer.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = `Logs: ${instanceName}`;
    DOM.logContentArea.textContent = 'Loading logs...';
    state.activeLogInstanceId = instanceId;
    state.logSize = 0;

    const updateLogs = async () => {
        if (!state.activeLogInstanceId) return;
        try {
            const data = await fetchLogs(state.activeLogInstanceId, state.logSize);
            if (data) {
                const isScrolled = DOM.logViewerContainer.scrollHeight - DOM.logViewerContainer.scrollTop <= DOM.logViewerContainer.clientHeight + 2;
                if (data.content) {
                    if (DOM.logContentArea.textContent === 'Loading logs...') DOM.logContentArea.innerHTML = '';
                    const logHtml = ansi_up.ansi_to_html(data.content);
                    DOM.logContentArea.insertAdjacentHTML('beforeend', logHtml);
                    state.logSize = data.size;
                    if (isScrolled) DOM.logViewerContainer.scrollTop = DOM.logViewerContainer.scrollHeight;
                }
            }
        } catch (error) {
            console.error("Failed to fetch logs:", error);
            clearInterval(state.activeLogInterval);
            state.activeLogInstanceId = null;
        }
    };

    await updateLogs();
    state.activeLogInterval = setInterval(updateLogs, 2000);
}