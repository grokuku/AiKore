import { state, DOM } from './state.js';
import { fetchInstances, fetchSystemInfo, fetchAndStoreBlueprints, fetchAvailablePorts, getSystemStats, fetchAvailablePythonVersions, fetchCudaVersions } from './api.js';
import { renderInstanceRow, updateSystemStats, setMonitorMode, checkRowForChanges, buildInstanceUrl, showToast, refreshAllGpuCells } from './ui.js';
import { setupModalEventHandlers } from './modals.js';
import { setupMainEventListeners } from './eventHandlers.js';
import { showWelcomeScreen, showBuilderView, renderBuilderStatus } from './tools.js';
import { HolafIcons } from '../vendor/holaf-icons.js';
import { initTheme } from './themes.js';
import { initThemeSelector } from './themeSelector.js';

const INSTANCE_ORDER_KEY = 'aikoreInstanceOrder';

// Recursive polling function to handle variable intervals
async function scheduleNextPoll(interval = 2000) {
    if (state.pollTimeoutId) clearTimeout(state.pollTimeoutId);
    state.pollTimeoutId = setTimeout(async () => {
        if (!state.isPolling) {
            state.isPolling = true;
            try {
                await fetchAndRenderInstances();
            } finally {
                state.isPolling = false;
            }
        }
    }, interval);
}

export async function fetchAndRenderInstances() {
    let nextInterval = 2000; // Default

    try {
        // If user is typing (row is dirty), we might still want to update statuses, 
        // but we must be careful not to overwrite input values.

        const activeElement = document.activeElement;
        const isInteracting = activeElement && activeElement.closest('#instances-table tr');

        const instances = await fetchInstances();

        // Check for 'starting' status to adjust polling speed
        const hasStartingInstance = instances.some(i => i.status === 'starting' || i.status === 'installing');
        if (hasStartingInstance) {
            nextInterval = 500;
        }

        if (isInteracting) {
            // Just schedule next and return, don't break UI
            scheduleNextPoll(nextInterval);
            return;
        }

        // --- NEW RENDERING LOGIC FOR GROUPING ---
        const instanceMap = new Map(instances.map(inst => [inst.id, { ...inst, children: [] }]));
        const rootInstances = [];

        instances.forEach(inst => {
            if (inst.parent_instance_id && instanceMap.has(inst.parent_instance_id)) {
                instanceMap.get(inst.parent_instance_id).children.push(instanceMap.get(inst.id));
            } else {
                rootInstances.push(instanceMap.get(inst.id));
            }
        });

        const savedOrder = JSON.parse(localStorage.getItem(INSTANCE_ORDER_KEY) || '[]');
        if (savedOrder.length > 0) {
            rootInstances.sort((a, b) => {
                const indexA = savedOrder.indexOf(String(a.id));
                const indexB = savedOrder.indexOf(String(b.id));
                if (indexA !== -1 && indexB !== -1) return indexA - indexB;
                if (indexA !== -1) return -1;
                if (indexB !== -1) return 1;
                return 0;
            });
        }

        const dirtyRows = document.querySelectorAll('tr.row-dirty');
        if (dirtyRows.length > 0) {
            // Partial Update Mode: Do not destroy structure
            instances.forEach(inst => {
                const row = DOM.instancesTable.querySelector(`tr[data-id="${inst.id}"]`);
                if (row) {
                    const statusSpan = row.querySelector('.status');
                    if (statusSpan && row.dataset.status !== inst.status) {
                        statusSpan.textContent = inst.status;
                        statusSpan.className = `status status-${inst.status.toLowerCase()}`;
                        row.dataset.status = inst.status;

                        const isActive = inst.status !== 'stopped';

                        // Update button.action-btn elements
                        const allButtons = row.querySelectorAll('button.action-btn');
                        allButtons.forEach(btn => {
                            const action = btn.dataset.action;
                            if (action === 'start') btn.disabled = isActive;
                            else if (action === 'stop') btn.disabled = !isActive;
                            else if (action === 'delete') btn.disabled = isActive;
                            else if (action === 'view') btn.disabled = (inst.status !== 'started');
                        });

                        // FIX: Also update the <a> Open link (was previously missed)
                        const openLink = row.querySelector('a[data-action="open"]');
                        if (openLink) {
                            const openHref = buildInstanceUrl(row, false);
                            openLink.href = openHref;
                            openLink.classList.toggle('disabled', openHref === '#');
                        }
                    }
                }
            });
        } else {
            // Full Re-render Mode: Destroy and Rebuild bodies

            // Remove existing tbodys (keep thead)
            const oldTbodies = DOM.instancesTable.querySelectorAll('tbody');
            oldTbodies.forEach(tb => tb.remove());

            // Helper to render a family
            const renderFamily = (parent, children) => {
                const tbody = document.createElement('tbody');
                tbody.classList.add('instance-group');
                tbody.dataset.groupId = parent.id;

                // 1. Parent Row
                const parentRow = renderInstanceRow(parent, false, 0);
                tbody.appendChild(parentRow);

                // 2. Children Rows
                if (children && children.length > 0) {
                    children.forEach(child => {
                        const childRow = renderInstanceRow(child, false, 1);
                        tbody.appendChild(childRow);
                    });
                }

                DOM.instancesTable.appendChild(tbody);
            };

            rootInstances.forEach(node => renderFamily(node, node.children));

        }

        if (rootInstances.length === 0) {
            // Create a temporary body for the empty message
            const emptyTbody = document.createElement('tbody');
            emptyTbody.innerHTML = `<tr class="no-instances-row"><td colspan="12" style="text-align: center;">No instances created yet.</td></tr>`;
            DOM.instancesTable.appendChild(emptyTbody);
        }

    } catch (error) {
        console.error("Failed to fetch instances:", error);
    } finally {
        scheduleNextPoll(nextInterval);
    }
}

// Refresh the table without racing a scheduled poll tick (state.isPolling
// guards against two concurrent DOM rebuilds; in the worst case the poll
// picks the new data up on its next pass).
async function refreshInstancesSafe() {
    if (state.isPolling) return;
    state.isPolling = true;
    try {
        await fetchAndRenderInstances();
    } finally {
        state.isPolling = false;
    }
}

async function initializeApp() {
    // --- THEME BOOT -------------------------------------------------------
    // Enregistre les packs hôte aikore (tokens + modal + toast), applique le
    // thème sauvegardé (localStorage['aikoreTheme']) ou aikore-dark, et pose
    // data-theme/data-mode sur <html> (le CSS s'y accroche). Les scripts defer
    // (holaf-tokens.js) sont exécutés avant DOMContentLoaded : l'API
    // window.HolafTokens est disponible ici. Le script inline du <head>
    // (anti-FOUC) a déjà posé les mêmes attributs au parsing ; initTheme les
    // repose à l'identique — aucun re-render contradictoire.
    initTheme();
    // Sélecteur de thème du header Instances : lit getCurrentTheme() → le
    // libellé/icône reflètent le thème restauré dès le boot.
    initThemeSelector();

    // --- FIRST RENDER (progressive display) -------------------------------
    // The instances table is rendered as soon as /api/instances answers.
    // It used to wait for the full init block below (system info / blueprints
    // / ports / python & CUDA version discovery), the slowest of which run
    // remote network operations (conda search subprocess, pytorch.org fetch,
    // each with multi-second timeouts) — leaving the table blank for many
    // seconds on page open. Dropdown payloads degrade to the built-in
    // fallbacks (state.js) and are re-rendered once the background init
    // below completes.
    try {
        await fetchAndRenderInstances();
        // Start polling immediately regardless of the remaining init steps
        // (fetchAndRenderInstances' finally-block already scheduled the next
        // tick, so the table keeps its status updates fresh from now on).
    } catch (error) {
        console.error("Initial instances fetch failed (will be retried by polling):", error);
    }

    // --- BACKGROUND INIT ---------------------------------------------------
    // Populates dropdown data (blueprints, ports, python/cuda versions, GPU
    // count). Non-fatal and non-blocking: a slow endpoint here no longer
    // prevents the table (and the rest of the UI) from appearing.
    (async () => {
        try {
            const [systemInfo, blueprints, ports, pyVersions, cudaVersions] = await Promise.all([
                fetchSystemInfo(),
                fetchAndStoreBlueprints(),
                fetchAvailablePorts(),
                fetchAvailablePythonVersions().catch(err => {
                    console.warn('Failed to fetch Python versions, using defaults:', err);
                    return null;
                }),
                fetchCudaVersions().catch(err => {
                    console.warn('Failed to fetch CUDA versions, using defaults:', err);
                    return null;
                })
            ]);
            // Store version data in shared state (only if fetch succeeded)
            if (pyVersions && pyVersions.length > 0) state.versions.python = pyVersions;
            if (cudaVersions && cudaVersions.length > 0) state.versions.cuda = cudaVersions;

            state.systemInfo = systemInfo;
            state.availableBlueprints = blueprints;
            state.availablePorts = ports.available_ports;

            // Authoritative GPU list is now known: (re)populate the instance GPU
            // checkboxes immediately instead of waiting for the next table render
            // (the table rendered before /api/system/info answered).
            try { refreshAllGpuCells(); } catch (e) { console.warn('GPU repopulate failed:', e); }

            // One refresh so the freshly loaded dropdown/blueprint/GPU data
            // shows up without waiting for the next poll tick.
            await refreshInstancesSafe();
        } catch (error) {
            // Non-fatal by design: the table already renders from fallbacks
            // and the poll loop keeps retrying. (Previously any failure here
            // replaced the whole document body with an error page.)
            console.error("Failed to initialize application data:", error);
            try { showToast(`Init data incomplete: ${error.message}`, 'error'); } catch (_) {}
        }
    })();

    // --- ADD ICONS TO STATIC BUTTONS ---
    // Runs once at boot on the buttons already present in index.html.
    // `replace: true` swaps a placeholder glyph (the × close button, the +
    // zoom buttons); otherwise the icon is PREPENDED, which keeps live children
    // intact — #global-save-btn notably wraps <span id="dirty-count"> that
    // updateGlobalSaveButton() keeps updating (flattening it would break them).
    // The builder button (#btn-open-builder) does not exist yet at this point:
    // it is injected below and gets its gear icon at creation time.
    const staticButtons = [
        { selector: '.add-new-btn', icon: 'plus' },
        { selector: '.context-item[data-action="terminal"]', icon: 'terminal' },
        { selector: '.context-item[data-action="script"]', icon: 'pencil' },
        { selector: '.context-item[data-action="manage-wheels"]', icon: 'folder' },
        { selector: '.context-item[data-action="version-check"]', icon: 'info' },
        { selector: '.context-item[data-action="rebuild-env"]', icon: 'refresh' },
        { selector: '.context-item[data-action="clone"]', icon: 'copy' },
        { selector: '.context-item[data-action="instantiate"]', icon: 'plus' },
        { selector: '.context-item[data-action="output_viewer"]', icon: 'eye' },
        { selector: '#global-save-btn', icon: 'check' },
        { selector: '#tools-close-btn', icon: 'x', size: 20, replace: true },
        { selector: '#editor-save-custom-btn', icon: 'file-text' },
        { selector: '#editor-update-btn', icon: 'refresh' },
        { selector: '.zoom-btn.zoom-in', icon: 'plus', replace: true },
        // Bascule du panneau System Monitoring : grille = normal, barres = compact.
        { selector: '.monitor-mode-btn[data-mode="normal"]', icon: 'layout', replace: true },
        { selector: '.monitor-mode-btn[data-mode="compact"]', icon: 'bar-chart', replace: true },
    ];

    staticButtons.forEach(({ selector, icon, size = 14, replace = false }) => {
        document.querySelectorAll(selector).forEach(btn => {
            // Idempotence: never inject a second SVG into the same button.
            if (btn.querySelector('svg')) return;
            const svg = HolafIcons.render(icon, { size });
            if (replace) btn.innerHTML = svg;
            // The trailing space is only a fallback inset for non-flex hosts;
            // flex buttons (.action-btn, .add-new-btn, .context-item) drop it
            // and rely on their own `gap`.
            else btn.insertAdjacentHTML('afterbegin', `${svg} `);
        });
    });

    // --- INJECT BUILDER BUTTON ---
    const buttons = document.querySelectorAll('button');
    let addBtn = null;
    for (const btn of buttons) {
        if (btn.textContent.trim() === 'Add New Instance') {
            addBtn = btn;
            break;
        }
    }

    if (addBtn) {
        const buildBtn = document.createElement('button');
        buildBtn.className = addBtn.className;
        buildBtn.id = 'btn-open-builder';
        // Icon applied at creation: this button is injected after the static
        // icons pass above. tools.js renderBuilderStatus() rewrites this label
        // from the stats poll and re-applies the same gear icon.
        buildBtn.innerHTML = `${HolafIcons.render('gear', { size: 14 })} Build Module`;
        buildBtn.style.marginRight = "10px";
        buildBtn.style.backgroundColor = "var(--ak-secondary)";
        buildBtn.style.borderColor = "var(--ak-secondary)";

        buildBtn.onclick = () => {
            showBuilderView();
        };

        addBtn.parentNode.insertBefore(buildBtn, addBtn);
    } else {
        console.warn("Could not find 'Add New Instance' button to inject Builder button.");
    }

    // (The instances polling loop was already started by the FIRST RENDER
    // above — fetchAndRenderInstances reschedules itself in its finally
    // block; no second call is needed here.)

    // --- MONITORING MODE (normal / compact) ---------------------------------
    // Toggle lives in the monitoring pane header, LEFT of the zoom controls.
    // The choice is persisted like the zoom levels (localStorage) and applied
    // here, before the first stats fetch resolves; ui.js (setMonitorMode)
    // rebuilds the panel immediately on change.
    const MONITOR_MODE_KEY = 'aikoreMonitorMode';
    const monitorModeButtons = document.querySelectorAll('.monitor-mode-btn');

    function applyMonitorMode(mode, { persist = true } = {}) {
        const next = mode === 'compact' ? 'compact' : 'normal';
        setMonitorMode(next);
        monitorModeButtons.forEach(btn => {
            const active = btn.dataset.mode === next;
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (persist) {
            try { localStorage.setItem(MONITOR_MODE_KEY, next); } catch (e) { /* stockage indisponible */ }
        }
    }

    let savedMonitorMode = 'normal';
    try {
        const storedMode = localStorage.getItem(MONITOR_MODE_KEY);
        if (storedMode === 'normal' || storedMode === 'compact') savedMonitorMode = storedMode;
    } catch (e) {
        console.warn('Failed to load monitoring mode:', e);
    }
    applyMonitorMode(savedMonitorMode, { persist: false });

    monitorModeButtons.forEach(btn => {
        btn.addEventListener('click', () => applyMonitorMode(btn.dataset.mode));
    });

    // Stats fetched WITHOUT blocking the boot sequence: /api/system/stats has
    // a fixed ~100ms floor (psutil.cpu_percent(interval=0.1) sleep) plus NVML
    // reads — it previously delayed showWelcomeScreen, the event listeners and
    // the Split panes. Fire-and-forget; the interval below refreshes it.
    getSystemStats().then(updateSystemStats);

    showWelcomeScreen();

    // System stats polling (pauses when tab is hidden)
    let statsIntervalId = null;
    const startStatsPolling = () => {
        if (statsIntervalId) return;
        statsIntervalId = setInterval(async () => {
            const stats = await getSystemStats();
            updateSystemStats(stats);

            // --- NEW: Polling builder status ---
            renderBuilderStatus();
        }, 2000);
    };
    const stopStatsPolling = () => {
        if (statsIntervalId) {
            clearInterval(statsIntervalId);
            statsIntervalId = null;
        }
    };
    startStatsPolling();
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopStatsPolling();
        } else {
            startStatsPolling();
            getSystemStats().then(updateSystemStats); // Immediately refresh on return
        }
    });

    DOM.toolsCloseBtn.addEventListener('click', showWelcomeScreen);

    // Sortable comes from a CDN; if it failed to load the app must still boot
    // (drag & drop degrades gracefully instead of aborting the whole init).
    if (typeof Sortable !== 'undefined') {
        new Sortable(DOM.instancesTable, {
            animation: 150,
            handle: '.drag-handle',
            draggable: 'tbody.instance-group',
            ghostClass: 'sortable-ghost',
            dragClass: 'sortable-drag',
            onEnd: function (evt) {
                const groups = DOM.instancesTable.querySelectorAll('tbody.instance-group');
                const newOrder = Array.from(groups)
                    .map(group => group.dataset.groupId)
                    .filter(id => id && id !== 'new');
                localStorage.setItem(INSTANCE_ORDER_KEY, JSON.stringify(newOrder));
            },
        });
    } else {
        console.warn("[Init] Sortable.js unavailable (CDN unreachable) — drag & drop disabled.");
    }

    setupMainEventListeners();
    setupModalEventHandlers();

    const SPLIT_STORAGE_KEY = 'aikoreSplitSizes';
    try {
        const storedSizes = localStorage.getItem(SPLIT_STORAGE_KEY);
        if (storedSizes) {
            const parsedSizes = JSON.parse(storedSizes);
            if (parsedSizes.vertical && parsedSizes.horizontal) {
                state.split.savedSizes = parsedSizes;
            }
        }
    } catch (e) {
        console.error("Failed to load or parse split sizes from localStorage.", e);
    }

    // Split.js comes from a CDN: degrade gracefully (the flexbox CSS layout
    // in base.css .split-container remains usable without it) if unavailable.
    if (typeof Split !== 'undefined' && typeof Split === 'function') {
        Split(['#instance-pane', '#bottom-split'], {
            sizes: state.split.savedSizes.vertical,
            minSize: [200, 150],
            gutterSize: 5,
            direction: 'vertical',
            onDragEnd: function (sizes) {
                state.split.savedSizes.vertical = sizes;
                localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(state.split.savedSizes));
            }
        });

        Split(['#tools-pane', '#monitoring-pane'], {
            sizes: state.split.savedSizes.horizontal,
            minSize: [300, 200],
            gutterSize: 5,
            direction: 'horizontal',
            cursor: 'col-resize',
            onDragEnd: function (sizes) {
                state.split.savedSizes.horizontal = sizes;
                localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(state.split.savedSizes));
            }
        });
    } else {
        console.warn("[Init] Split.js unavailable (CDN) — panes fixed, no resize handle.");
    }

    // --- ZOOM CONTROLS ---
    const ZOOM_STORAGE_KEY = 'aikoreZoomLevels';
    const ZOOM_STEP = 10;
    const ZOOM_MIN = 50;
    const ZOOM_MAX = 200;

    // Load saved zoom levels
    try {
        const storedZoom = localStorage.getItem(ZOOM_STORAGE_KEY);
        if (storedZoom) {
            const parsed = JSON.parse(storedZoom);
            if (parsed.instance !== undefined) state.zoom.instance = parsed.instance;
            if (parsed.monitoring !== undefined) state.zoom.monitoring = parsed.monitoring;
            if (parsed.tools) Object.assign(state.zoom.tools, parsed.tools);
        }
    } catch (e) {
        console.error('Failed to load zoom levels:', e);
    }

    function saveZoomLevels() {
        localStorage.setItem(ZOOM_STORAGE_KEY, JSON.stringify(state.zoom));
    }

    function applyZoom(paneId, zoomLevel) {
        const pane = document.getElementById(paneId);
        if (!pane) return;
        const content = pane.querySelector('.pane-content');
        if (content) {
            content.style.zoom = (zoomLevel / 100);
        }
    }

    function getCurrentToolsZoomKey() {
        // Map the active tool view name to the zoom key
        return state.activeToolView || 'welcome';
    }

    function updateZoomLabels() {
        document.querySelectorAll('.zoom-label').forEach(label => {
            const pane = label.dataset.pane;
            if (pane === 'tools') {
                const key = getCurrentToolsZoomKey();
                label.textContent = (state.zoom.tools[key] ?? 100) + '%';
            } else {
                label.textContent = state.zoom[pane] + '%';
            }
        });
    }

    function changeZoom(paneName, delta) {
        if (paneName === 'tools') {
            const key = getCurrentToolsZoomKey();
            state.zoom.tools[key] = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, (state.zoom.tools[key] ?? 100) + delta));
        } else {
            state.zoom[paneName] = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, state.zoom[paneName] + delta));
        }

        if (paneName === 'tools') {
            // Apply to the tools-pane-content directly
            const toolsContent = document.querySelector('#tools-pane .pane-content');
            const key = getCurrentToolsZoomKey();
            if (toolsContent) toolsContent.style.zoom = ((state.zoom.tools[key] ?? 100) / 100);
        } else {
            applyZoom(paneName === 'instance' ? 'instance-pane' : 'monitoring-pane', state.zoom[paneName]);
        }

        updateZoomLabels();
        saveZoomLevels();

        // Refit all visible terminal instances when zooming tools pane
        if (paneName === 'tools') {
            Object.values(state.terminals).forEach(t => {
                if (t.fitAddon && !DOM.terminalViewContainer.classList.contains('hidden')) {
                    try { t.fitAddon.fit(); } catch (e) { }
                }
            });
        }
    }

    // Apply initial zoom levels
    applyZoom('instance-pane', state.zoom.instance);
    applyZoom('monitoring-pane', state.zoom.monitoring);
    // Tools pane gets its zoom from the active tool view (set in showWelcomeScreen, etc.)
    applyZoom('tools-pane', state.zoom.tools.welcome);
    updateZoomLabels();

    // Attach zoom button listeners
    document.querySelectorAll('.zoom-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const pane = btn.dataset.pane;
            const delta = btn.classList.contains('zoom-in') ? ZOOM_STEP : -ZOOM_STEP;
            changeZoom(pane, delta);
        });
    });

    // Double-click on zoom label resets zoom to 100%
    document.querySelectorAll('.zoom-label').forEach(label => {
        label.addEventListener('dblclick', () => {
            const pane = label.dataset.pane;
            if (pane === 'tools') {
                const key = getCurrentToolsZoomKey();
                state.zoom.tools[key] = 100;
            } else {
                state.zoom[pane] = 100;
            }

            if (pane === 'tools') {
                const toolsContent = document.querySelector('#tools-pane .pane-content');
                const key = getCurrentToolsZoomKey();
                if (toolsContent) toolsContent.style.zoom = ((state.zoom.tools[key] ?? 100) / 100);
            } else {
                applyZoom(pane === 'instance' ? 'instance-pane' : 'monitoring-pane', state.zoom[pane]);
            }

            updateZoomLabels();
            saveZoomLevels();

            // Refit terminal instances when zooming tools pane
            if (pane === 'tools') {
                Object.values(state.terminals).forEach(t => {
                    if (t.fitAddon) { try { t.fitAddon.fit(); } catch (e) { } }
                });
            }
        });
    });

    // Expose zoom switching for tools.js
    window.__aikoreSetToolsZoom = function(viewName) {
        state.activeToolView = viewName;
        const zoomLevel = state.zoom.tools[viewName] || 100;
        const toolsContent = document.querySelector('#tools-pane .pane-content');
        if (toolsContent) toolsContent.style.zoom = (zoomLevel / 100);
        updateZoomLabels();
    };

    state.viewResizeObserver = new ResizeObserver(() => {
        if (DOM.instanceIframe && DOM.instanceIframe.contentWindow) {
            DOM.instanceIframe.contentWindow.dispatchEvent(new Event('resize'));
        }
    });

    const toolsPane = document.getElementById('tools-pane');
    const resizeObserver = new ResizeObserver(() => {
        Object.values(state.terminals).forEach(t => {
            if (t.fitAddon && !DOM.terminalViewContainer.classList.contains('hidden')) {
                try { t.fitAddon.fit(); } catch (e) { }
            }
        });
    });
    resizeObserver.observe(toolsPane);

    // --- CLEANUP ON PAGE UNLOAD ---
    window.addEventListener('beforeunload', () => {
        if (state.pollTimeoutId) clearTimeout(state.pollTimeoutId);
        if (statsIntervalId) clearInterval(statsIntervalId);
        if (state.viewResizeObserver) state.viewResizeObserver.disconnect();
        resizeObserver.disconnect();
    });
}

document.addEventListener('DOMContentLoaded', initializeApp);