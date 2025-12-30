import { state, DOM } from './state.js';
import { fetchLogs, performVersionCheck, fetchFileContent } from './api.js';

const ansi_up = new AnsiUp();

function hideAllToolViews() {
    // Hide all containers
    [
        DOM.welcomeScreenContainer,
        DOM.logViewerContainer,
        DOM.editorContainer,
        DOM.instanceViewContainer,
        DOM.terminalViewContainer,
        DOM.versionCheckContainer
    ].forEach(el => el.classList.add('hidden'));

    // Handle new builder container if it exists dynamically or statically
    const builderContainer = document.getElementById('builder-container');
    if (builderContainer) builderContainer.classList.add('hidden');

    DOM.toolsCloseBtn.classList.add('hidden');

    // Reset sources and intervals
    DOM.instanceIframe.src = 'about:blank';
    DOM.welcomeIframe.src = 'about:blank';
    
    clearInterval(state.activeLogInterval);
    state.activeLogInstanceId = null;
    
    closeTerminal(); // Closes instance terminal
    closeBuilderTerminal(); // Closes builder terminal
    
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
let builderSplit = null; // New: Store split instance

async function fetchBuilderInfo() {
    const res = await fetch('/api/builder/info');
    return await res.json();
}

async function fetchWheelsList() {
    const res = await fetch('/api/builder/wheels');
    return await res.json();
}

async function deleteWheel(filename) {
    if(!confirm(`Delete ${filename}?`)) return;
    await fetch(`/api/builder/wheels/${filename}`, { method: 'DELETE' });
    renderWheelsTable(); // Refresh
}

async function renderWheelsTable() {
    const tbody = document.getElementById('wheels-table-body');
    if(!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5">Loading...</td></tr>';
    
    try {
        const wheels = await fetchWheelsList();
        tbody.innerHTML = '';
        if(wheels.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:#666;">No wheels built yet.</td></tr>';
            return;
        }

        wheels.forEach(w => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td title="${w.filename}">${w.filename.length > 20 ? w.filename.substring(0,18)+'...' : w.filename}</td>
                <td>${w.cuda_arch}</td>
                <td>${w.size_mb} MB</td>
                <td>${w.created_at}</td>
                <td class="wheel-actions">
                    <button class="btn-icon btn-delete" title="Delete">🗑</button>
                </td>
            `;
            // Delete action
            tr.querySelector('.btn-delete').onclick = () => deleteWheel(w.filename);
            tbody.appendChild(tr);
        });
    } catch(e) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:red">Error loading wheels</td></tr>`;
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
    // Don't destroy Split here, we keep the layout
    
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
    container.innerHTML = ''; // Clear previous
    
    builderTerminal = new Terminal({
        cursorBlink: false,
        disableStdin: true, // Read-only
        fontSize: 12,
        fontFamily: 'Courier New, Courier, monospace',
        theme: { background: '#000000', foreground: '#e0e0e0' },
        convertEol: true // FIX: Handles \n vs \r\n to prevent staircase effect
    });
    
    builderFitAddon = new FitAddon.FitAddon();
    builderTerminal.loadAddon(builderFitAddon);
    builderTerminal.open(container);
    builderFitAddon.fit();

    builderResizeObserver = new ResizeObserver(() => {
        if (builderFitAddon) {
            try { builderFitAddon.fit(); } catch(e) {}
        }
    });
    builderResizeObserver.observe(container);
}

async function startBuild() {
    const presetSelect = document.getElementById('builder-preset');
    const archSelect = document.getElementById('builder-arch');
    const pythonSelect = document.getElementById('builder-python');
    const cudaSelect = document.getElementById('builder-cuda');
    const customUrlInput = document.getElementById('builder-custom-url');
    const btn = document.getElementById('btn-start-build');

    const payload = {
        preset: presetSelect.value,
        arch: archSelect.value,
        git_url: customUrlInput.value,
        python_ver: pythonSelect.value,
        cuda_ver: cudaSelect.value
    };

    btn.disabled = true;
    
    // Animation Logic
    let dots = 0;
    btn.textContent = "BUILDING";
    builderBtnInterval = setInterval(() => {
        dots = (dots + 1) % 4;
        btn.textContent = "BUILDING" + ".".repeat(dots);
    }, 500);
    
    // Reset Terminal
    if(builderTerminal) builderTerminal.clear();
    else initBuilderTerminal();

    // Connect WS
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
    
    // Create Layout if not exists
    let container = document.getElementById('builder-container');
    if (!container) {
        const html = `
        <div id="builder-container">
            <div id="builder-top-pane">
                <div id="builder-options">
                    <div class="builder-field">
                        <label>Module Preset</label>
                        <select id="builder-preset"></select>
                    </div>
                    
                    <div class="builder-field" id="builder-field-custom" style="display:none;">
                        <label>Git URL / Package Name</label>
                        <input type="text" id="builder-custom-url" placeholder="https://github.com/user/repo.git">
                    </div>

                    <div class="builder-field">
                        <label>Python Version</label>
                        <select id="builder-python">
                            <option value="3.12" selected>3.12 (Default)</option>
                            <option value="3.11">3.11</option>
                            <option value="3.10">3.10</option>
                        </select>
                    </div>

                    <div class="builder-field">
                        <label>PyTorch CUDA Version</label>
                        <select id="builder-cuda">
                            <option value="cu130" selected>CUDA 13.0 (Default)</option>
                            <option value="cu124">CUDA 12.4</option>
                            <option value="cu121">CUDA 12.1</option>
                            <option value="cu118">CUDA 11.8</option>
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

                    <button id="btn-start-build">BUILD MODULE</button>
                </div>
                <div id="builder-wheels">
                    <div style="padding:0.5rem; background:#252545; color:#fff; font-weight:bold; border-bottom:1px solid #444;">Available Wheels</div>
                    <div id="wheels-table-container">
                        <table class="wheels-table">
                            <thead>
                                <tr>
                                    <th>Filename</th>
                                    <th>Arch</th>
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

        // Initialize Split.js for the top pane (2/3 options, 1/3 wheels)
        Split(['#builder-options', '#builder-wheels'], {
            sizes: [66, 34],
            minSize: [200, 200],
            gutterSize: 5,
            cursor: 'col-resize'
        });
    }

    container.classList.remove('hidden');
    DOM.toolsCloseBtn.classList.remove('hidden');
    DOM.toolsPaneTitle.textContent = "Tools / Module Builder (Experimental)";

    const info = await fetchBuilderInfo();
    
    const presetSelect = document.getElementById('builder-preset');
    presetSelect.innerHTML = '';
    for(const [key, val] of Object.entries(info.presets)) {
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = val.label;
        presetSelect.appendChild(opt);
    }
    
    const archSelect = document.getElementById('builder-arch');
    if(!archSelect.querySelector('option[value="auto"]')) {
        const autoOpt = document.createElement('option');
        autoOpt.value = info.detected_arch;
        autoOpt.textContent = `Auto-Detect (${info.detected_arch}) - Recommended`;
        autoOpt.selected = true;
        archSelect.prepend(autoOpt);
    }

    renderWheelsTable();
    initBuilderTerminal();
}

// --- STANDARD TOOLS EXPORTS (Preserved) ---

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