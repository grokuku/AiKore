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
    // --- Custom Versions Configuration ---
    versions: {
        python: [],        // Filled dynamically from /api/builder/versions/python
        cuda: [],          // Filled dynamically from /api/builder/versions/cuda (objects: {cu, version})
        torchCache: {}     // Filled dynamically per CUDA version from /api/builder/versions/torch/{cu}
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
    // --- Persistent terminals: keyed by instance ID ---
    terminals: {},  // { instanceId: { terminal: Terminal, fitAddon: FitAddon, socket: WebSocket, instanceName: string } }
    instancesPollInterval: null,
    pollTimeoutId: null,
    isPolling: false,
    viewResizeObserver: null,
    pendingUpdates: [],
    currentWheelsInstanceId: null,
    split: {
        savedSizes: { vertical:[60, 40], horizontal: [65, 35] }
    },
    zoom: {
        instance: 100,
        tools: {
            welcome: 100,
            logs: 100,
            editor: 100,
            terminal: 100,
            versionCheck: 100,
            builder: 100,
            wheels: 100
        },
        monitoring: 100
    },
    activeToolView: 'welcome'
};