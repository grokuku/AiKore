import { state, DOM } from './state.js';
import { fetchLogs, performVersionCheck, fetchFileContent, fetchTorchVersions } from './api.js';
import { showToast } from './ui.js';

const ansi_up = new AnsiUp();

function setToolZoom(viewName) {
    if (window.__aikoreSetToolsZoom) window.__aikoreSetToolsZoom(viewName);
}

function hideAllToolViews({ keepBuilder = false } = {}) {
    [
        DOM.welcomeScreenContainer,
        DOM.logViewerContainer,
        DOM.editorContainer,
        DOM.instanceViewContainer,
        DOM.versionCheckContainer
    ].forEach(el => el.classList.add('hidden'));

    // Always hide the builder container visually. If a build is in progress,
    // we keep the WebSocket and terminal alive but hide the UI.
    const builderContainer = document.getElementById('builder-container');
    if (builderContainer) builderContainer.classList.add('hidden');

    const wheelsMgr = document.getElementById('wheels-manager-container');
    if (wheelsMgr) wheelsMgr.classList.add('hidden');

    DOM.toolsCloseBtn.classList.add('hidden');

    DOM.instanceIframe.src = 'about:blank';
    DOM.welcomeIframe.src = 'about:blank';

    clearInterval(state.activeLogInterval);
    state.activeLogInstanceId = null;

    // Always hide the terminal container. Terminals stay alive in state.terminals
    // and are re-shown when switching back.
    DOM.terminalViewContainer.classList.add('hidden');

    // Only destroy the builder terminal if no build is in progress
    if (!keepBuilder) {
        closeBuilderTerminal();
    }

    if (state.viewResizeObserver) {
        state.viewResizeObserver.disconnect();
    }
}

// --- PERSISTENT TERMINAL POOL ---

function _createTerminalForInstance(instanceId, instanceName) {
    const termState = {
        terminal: new Terminal({
            cursorBlink: true, fontSize: 14, fontFamily: 'Courier New, Courier, monospace',
            theme: { background: '#111111', foreground: '#e0e0e0', cursor: '#e0e0e0' }
        }),
        fitAddon: new FitAddon.FitAddon(),
        socket: null,
        instanceName: instanceName,
        resizeObserver: null
    };

    const container = document.createElement('div');
    container.id = `terminal-host-${instanceId}`;
    container.style.width = '100%';
    container.style.height = '100%';
    DOM.terminalContent.appendChild(container);

    termState.terminal.loadAddon(termState.fitAddon);
    termState.terminal.open(container);
    termState.fitAddon.fit();

    // WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/instances/${instanceId}/terminal`;
    const socket = new WebSocket(wsUrl);
    socket.binaryType = 'arraybuffer';
    termState.socket = socket;

    socket.onopen = () => {
        const initialSize = { type: 'resize', cols: termState.terminal.cols, rows: termState.terminal.rows };
        socket.send(JSON.stringify(initialSize));
        termState.terminal.onData(data => {
            if (socket && socket.readyState === WebSocket.OPEN) socket.send(data);
        });
        termState.terminal.onResize(size => {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: 'resize', cols: size.cols, rows: size.rows }));
            }
        });
    };

    socket.onmessage = (event) => {
        termState.terminal.write(new Uint8Array(event.data));
    };

    socket.onclose = (event) => {
        termState.terminal.write(`\r\n\x1b[31m[CLOSED]\x1b[0m ${event.reason || ''}\r\n`);
    };

    socket.onerror = () => {
        termState.terminal.write('\r\n\x1b[31m[ERROR]\x1b[0m\r\n');
    };

    // ResizeObserver for auto-fit
    termState.resizeObserver = new ResizeObserver(() => {
        if (termState.fitAddon && !DOM.terminalViewContainer.classList.contains('hidden')) {
            try { termState.fitAddon.fit(); } catch (e) { }
        }
    });
    termState.resizeObserver.observe(container);

    state.terminals[instanceId] = termState;
    return termState;
}

function _showTerminalInstance(instanceId) {
    // Hide all terminal hosts
    DOM.terminalContent.querySelectorAll('[id^="terminal-host-"]').forEach(el => {
        el.style.display = 'none';
    });

    let termState = state.terminals[instanceId];
    if (!termState) return;

    const hostEl = document.getElementById(`terminal-host-${instanceId}`);
    if (hostEl) {
        hostEl.style.display = '';
        // Refit after making visible
        requestAnimationFrame(() => {
            try { termState.fitAddon.fit(); } catch (e) { }
            termState.terminal.focus();
        });
    }
}

function closeTerminal(instanceId) {
    const termState = state.terminals[instanceId];
    if (!termState) return;

    if (termState.socket) {
        termState.socket.close();
        termState.socket = null;
    }
    if (termState.resizeObserver) {
        termState.resizeObserver.disconnect();
        termState.resizeObserver = null;
    }
    termState.terminal.dispose();

    const hostEl = document.getElementById(`terminal-host-${instanceId}`);
    if (hostEl) hostEl.remove();

    delete state.terminals[instanceId];
}

function closeAllTerminals() {
    Object.keys(state.terminals).forEach(id => closeTerminal(id));
}

function _disposeTerminalRef() {
    // Legacy: no longer needed, kept for compatibility
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
            const nameTd = document.createElement('td');
            nameTd.textContent = w.filename;
            nameTd.title = w.filename;
            const archTd = document.createElement('td');
            archTd.textContent = w.cuda_arch;
            const cudaTd = document.createElement('td');
            cudaTd.textContent = w.cuda_ver || 'N/A';
            const torchTd = document.createElement('td');
            torchTd.textContent = w.torch_ver || 'N/A';
            const sizeTd = document.createElement('td');
            sizeTd.textContent = `${w.size_mb} MB`;
            const dateTd = document.createElement('td');
            dateTd.textContent = w.created_at;
            const actionsTd = document.createElement('td');
            actionsTd.className = 'wheel-actions';
            const dlBtn = document.createElement('button');
            dlBtn.className = 'btn-icon btn-download';
            dlBtn.title = 'Download';
            dlBtn.textContent = '⬇';
            dlBtn.addEventListener('click', () => downloadWheel(w.filename));
            const delBtn = document.createElement('button');
            delBtn.className = 'btn-icon btn-delete';
            delBtn.title = 'Delete';
            delBtn.textContent = '🗑';
            delBtn.addEventListener('click', () => deleteWheel(w.filename));
            actionsTd.appendChild(dlBtn);
            actionsTd.appendChild(delBtn);
            tr.appendChild(nameTd);
            tr.appendChild(archTd);
            tr.appendChild(cudaTd);
            tr.appendChild(torchTd);
            tr.appendChild(sizeTd);
            tr.appendChild(dateTd);
            tr.appendChild(actionsTd);
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

    if (builderResizeObserver) builderResizeObserver.disconnect();
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
    // Don't destroy builder terminal if a build is in progress
    const isBuilding = builderSocket && builderSocket.readyState === WebSocket.OPEN;
    hideAllToolViews({ keepBuilder: isBuilding });

    let container = document.getElementById('builder-container');
    if (!container) {

        // --- NEW: Dynamic Options Generation ---
        // Python Options
        const pyOptionsHtml = state.versions.python.map((v, i) =>
            `<option value="${v}">${v}${i === 0 ? ' (Latest)' : ''}</option>`
        ).join('');

        // CUDA Options
        // We expect state.versions.cuda to be like ["13.0", "12.8", "12.6", ...]
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
    setToolZoom('builder');

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
    // Only init terminal if not already existing (builder keeps its state)
    if (!builderTerminal) {
        initBuilderTerminal();
    } else {
        // Re-attach ResizeObserver since the container might have been detached
        const container = document.getElementById('builder-terminal');
        if (builderResizeObserver) builderResizeObserver.disconnect();
        builderResizeObserver = new ResizeObserver(() => {
            if (builderFitAddon) {
                try { builderFitAddon.fit(); } catch (e) { }
            }
        });
        builderResizeObserver.observe(container);
        requestAnimationFrame(() => {
            try { builderFitAddon.fit(); } catch (e) { }
        });
    }
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
    setToolZoom('wheels');

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
        document.getElementById('wheels-available-body').innerHTML = `<tr><td colspan="3" style="color:red">Error: ${e.message.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</td></tr>`;
        document.getElementById('wheels-installed-body').innerHTML = `<tr><td colspan="3" style="color:red">Error: ${e.message.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</td></tr>`;
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
            const tr = document.createElement('tr');
            const nameTd = document.createElement('td');
            nameTd.textContent = w.filename;
            nameTd.title = w.filename;
            const sizeTd = document.createElement('td');
            sizeTd.style.textAlign = 'right';
            sizeTd.textContent = `${w.size_mb} MB`;
            const actTd = document.createElement('td');
            actTd.className = 'action-cell';
            const installBtn = document.createElement('button');
            installBtn.className = 'btn-action install';
            installBtn.title = 'Install';
            installBtn.textContent = '➕';
            installBtn.addEventListener('click', () => window.toggleWheelState(w.filename, true));
            actTd.appendChild(installBtn);
            tr.appendChild(nameTd);
            tr.appendChild(sizeTd);
            tr.appendChild(actTd);
            availableBody.appendChild(tr);
        });
    }

    if (installedWheels.length === 0) {
        installedBody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:#888;">No wheels currently installed.</td></tr>';
    } else {
        installedWheels.forEach(w => {
            const tr = document.createElement('tr');
            const nameTd = document.createElement('td');
            nameTd.textContent = w.filename;
            nameTd.title = w.filename;
            const sizeTd = document.createElement('td');
            sizeTd.style.textAlign = 'right';
            sizeTd.textContent = `${w.size_mb} MB`;
            const actTd = document.createElement('td');
            actTd.className = 'action-cell';
            const removeBtn = document.createElement('button');
            removeBtn.className = 'btn-action remove';
            removeBtn.title = 'Remove';
            removeBtn.textContent = '❌';
            removeBtn.addEventListener('click', () => window.toggleWheelState(w.filename, false));
            actTd.appendChild(removeBtn);
            tr.appendChild(nameTd);
            tr.appendChild(sizeTd);
            tr.appendChild(actTd);
            installedBody.appendChild(tr);
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
    setToolZoom('versionCheck');

    DOM.versionCheckVersionsArea.textContent = 'Running version checks...';
    DOM.versionCheckConflictsArea.textContent = 'Running dependency checks...';

    const data = await performVersionCheck(instanceId);
    DOM.versionCheckVersionsArea.textContent = data.versions;
    DOM.versionCheckConflictsArea.textContent = data.conflicts;
}

let welcomeResizeObserver = null;

export function showWelcomeScreen() {
    hideAllToolViews();
    DOM.welcomeScreenContainer.classList.remove('hidden');
    DOM.welcomeIframe.src = '/static/welcome/index.html';
    DOM.toolsPaneTitle.textContent = 'Tools / Welcome';
    setToolZoom('welcome');

    // Observe container resize and notify the iframe (fallback for iframe resize events)
    if (welcomeResizeObserver) welcomeResizeObserver.disconnect();
    welcomeResizeObserver = new ResizeObserver(() => {
        try {
            DOM.welcomeIframe.contentWindow?.postMessage({ type: 'aikore-resize' }, '*');
        } catch (e) { /* cross-origin, ignore */ }
    });
    welcomeResizeObserver.observe(DOM.welcomeScreenContainer);
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
    setToolZoom('editor');

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
    setToolZoom('welcome'); // View uses same zoom as welcome
    if (!url || url === '#') {
        DOM.instanceIframe.src = 'about:blank';
        return;
    }
    DOM.instanceIframe.src = url;
    if (state.viewResizeObserver) {
        state.viewResizeObserver.observe(DOM.instanceViewContainer);
    }
}

/**
 * Opens a terminal for the given instance.
 * If a terminal already exists for this instance, it is shown (not recreated).
 * If an active build is in progress, the builder is kept alive in the background.
 */
export function openTerminal(instanceId, instanceName) {
    const isBuilding = builderSocket && builderSocket.readyState === WebSocket.OPEN;

    hideAllToolViews({ keepBuilder: isBuilding });

    DOM.terminalViewContainer.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = `Terminal: ${instanceName}`;
    setToolZoom('terminal');

    // Reuse existing terminal if available
    if (state.terminals[instanceId]) {
        _showTerminalInstance(instanceId);
        return;
    }

    // Create new terminal
    DOM.terminalContent.innerHTML = '';
    const termState = _createTerminalForInstance(instanceId, instanceName);
    _showTerminalInstance(instanceId);
}

/**
 * Closes the terminal for a specific instance.
 * Called when the user explicitly wants to close a terminal.
 */
export function closeTerminalById(instanceId) {
    closeTerminal(instanceId);
}

export async function showLogViewer(instanceId, instanceName) {
    hideAllToolViews();
    DOM.logViewerContainer.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = `Logs: ${instanceName}`;
    setToolZoom('logs');
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