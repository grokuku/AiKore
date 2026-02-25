export const DOM = {
    instancesTable: document.getElementById('instances-table'),
    addInstanceBtn: document.querySelector('.add-new-btn'),
    toolsPaneTitle: document.getElementById('tools-pane-title'),
    welcomeScreenContainer: document.getElementById('welcome-screen-container'),
    welcomeIframe: document.getElementById('welcome-iframe'),
    logViewerContainer: document.getElementById('log-viewer-container'),
    logContentArea: document.getElementById('log-content-area'),
    editorContainer: document.getElementById('editor-container'),
    editorUpdateBtn: document.getElementById('editor-update-btn'),
    editorSaveCustomBtn: document.getElementById('editor-save-custom-btn'),
    instanceViewContainer: document.getElementById('instance-view-container'),
    instanceIframe: document.getElementById('instance-iframe'),
    terminalViewContainer: document.getElementById('terminal-view-container'),
    terminalContent: document.getElementById('terminal-content'),
    versionCheckContainer: document.getElementById('version-check-container'),
    versionCheckVersionsArea: document.getElementById('version-check-versions-area'),
    versionCheckConflictsArea: document.getElementById('version-check-conflicts-area'),
    toolsCloseBtn: document.getElementById('tools-close-btn'),
    toolsContextMenu: document.getElementById('tools-context-menu'),
    deleteModal: document.getElementById('delete-modal'),
    overwriteModal: document.getElementById('overwrite-modal'),
    rebuildModal: document.getElementById('rebuild-modal'),
    restartConfirmModal: document.getElementById('restart-confirm-modal'),
    saveBlueprintModal: document.getElementById('save-blueprint-modal'),
    blueprintFilenameInput: document.getElementById('blueprint-filename-input'),
    updateConfirmModal: document.getElementById('update-confirm-modal'),
    cpuProgress: document.getElementById('cpu-progress'),
    cpuPercentText: document.getElementById('cpu-percent-text'),
    ramProgress: document.getElementById('ram-progress'),
    ramUsageText: document.getElementById('ram-usage-text'),
    gpuStatsContainer: document.getElementById('gpu-stats-container'),
    gpuStatTemplate: document.getElementById('gpu-stat-template'),
};

export const state = {
    availableBlueprints: { stock: [], custom: [] },
    availablePorts:[],
    systemInfo: { gpu_count: 0, gpus:[] },
    // --- NEW: Custom Versions Configuration ---
    // --- NEW: Custom Versions Configuration ---
    versions: {
        python:['3.10', '3.11', '3.12', '3.13', '3.14', '3.15'],
        cuda:['11.8', '12.1', '12.4', '12.6', '12.8', '13.0', '13.1'],
        torchCache: {} // Will store torch versions fetched dynamically per cuda version
    },
    currentMenuInstance: null,
    instanceToDeleteId: null,
    instanceToRebuild: null,
    instanceToUpdate: null,
    activeLogInstanceId: null,
    activeLogInterval: null,
    logSize: 0,
    editorState: {
        instanceId: null,
        instanceName: null,
        fileType: null,
        baseBlueprint: null,
    },
    codeEditor: null,
    currentTerminal: null,
    currentTerminalSocket: null,
    fitAddon: null,
    instancesPollInterval: null,
    viewResizeObserver: null,
    split: {
        savedSizes: { vertical:[60, 40], horizontal: [65, 35] }
    }
};