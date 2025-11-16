import { state, DOM } from './state.js';
import { fetchLogs, performVersionCheck, fetchFileContent } from './api.js';

function hideAllToolViews() {
    DOM.welcomeScreenContainer.classList.add('hidden');
    DOM.logViewerContainer.classList.add('hidden');
    DOM.editorContainer.classList.add('hidden');
    DOM.instanceViewContainer.classList.add('hidden');
    DOM.terminalViewContainer.classList.add('hidden');
    DOM.versionCheckContainer.classList.add('hidden');
    DOM.toolsCloseBtn.classList.add('hidden');

    DOM.instanceIframe.src = 'about:blank';
    DOM.welcomeIframe.src = 'about:blank';
    clearInterval(state.activeLogInterval);
    state.activeLogInstanceId = null;
    closeTerminal();
    if (state.viewResizeObserver) {
        state.viewResizeObserver.disconnect();
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

    const row = DOM.instancesTbody.querySelector(`tr[data-id="${instanceId}"]`);
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
                    if (DOM.logContentArea.textContent === 'Loading logs...') DOM.logContentArea.textContent = '';
                    DOM.logContentArea.appendChild(document.createTextNode(data.content));
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
