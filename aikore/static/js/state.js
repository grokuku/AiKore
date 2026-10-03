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
    // Panneau System Monitoring : contenu entièrement construit par ui.js
    // (cartes CPU/GPU ou lignes denses selon state.monitorMode).
    systemStatsContainer: document.getElementById('system-stats-container'),
};

export const state = {
    availableBlueprints: { stock: [], custom: [] },
    availablePorts:[],
    systemInfo: { gpu_count: 0, gpus:[] },
    // Latest /api/system/stats payload (cached so GPU cells can degrade to it
    // when /api/system/info has not answered yet during the progressive boot).
    systemStats: null,
    // Monitoring display mode ('normal' | 'compact'). Restored from
    // localStorage['aikoreMonitorMode'] by main.js at boot; drives the layout
    // built by ui.js (rebuild only when the mode or the device list changes).
    monitorMode: 'normal',
    // Rolling GPU utilization history for the normal-mode sparklines:
    // { gpus: { [gpuId]: number[] } }, capped by ui.js (~1 min at 2 s poll).
    monitorHistory: { gpus: {} },
    // Becomes true once the GPU list has been revealed from any source; guards
    // against repeatedly rebuilding the GPU checkboxes on every stats poll.
    gpuDataLoaded: false,
    // Last GPU count used to build the cells (avoid needless DOM rebuilds).
    lastGpuCount: -1,
    // --- Custom Versions Configuration ---
    versions: {
        python: ["3.15", "3.14", "3.13", "3.12", "3.11", "3.10"],  // Fallback; replaced by /api/builder/versions/python
        cuda: [                                                                  // Fallback; replaced by /api/builder/versions/cuda
            {cu: "cu131", version: "13.1"},
            {cu: "cu130", version: "13.0"},
            {cu: "cu128", version: "12.8"},
            {cu: "cu126", version: "12.6"},
            {cu: "cu124", version: "12.4"},
            {cu: "cu121", version: "12.1"},
            {cu: "cu118", version: "11.8"}
        ],
        torchCache: {}     // Filled dynamically per CUDA version from /api/builder/versions/torch/{cu}
    },
    currentMenuInstance: null,
    instanceToDeleteId: null,
    instanceToRebuild: null,
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
            wheels: 100,
            instanceView: 100
        },
        monitoring: 100
    },
    activeToolView: 'welcome'
};