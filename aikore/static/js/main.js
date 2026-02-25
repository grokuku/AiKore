import { state, DOM } from './state.js';
import { fetchSystemInfo, fetchAndStoreBlueprints, fetchAvailablePorts, getSystemStats, fetchAvailablePythonVersions } from './api.js';
import { renderInstanceRow, updateSystemStats, checkRowForChanges } from './ui.js';
import { setupModalEventHandlers } from './modals.js';
import { setupMainEventListeners } from './eventHandlers.js';
import { showWelcomeScreen, showBuilderView, renderBuilderStatus } from './tools.js';

const INSTANCE_ORDER_KEY = 'aikoreInstanceOrder';

// Recursive polling function to handle variable intervals
async function scheduleNextPoll(interval = 2000) {
    if (state.pollTimeoutId) clearTimeout(state.pollTimeoutId);
    state.pollTimeoutId = setTimeout(async () => {
        await fetchAndRenderInstances();
    }, interval);
}

export async function fetchAndRenderInstances() {
    let nextInterval = 2000; // Default
    
    try {
        // If user is typing (row is dirty), we might still want to update statuses, 
        // but we must be careful not to overwrite input values.
        
        const activeElement = document.activeElement;
        const isInteracting = activeElement && activeElement.closest('#instances-table tr');
        
        const response = await fetch('/api/instances/');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        let instances = await response.json();

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
        const rootInstances =[];
        
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
                            
                            const allButtons = row.querySelectorAll('button.action-btn');
                            const isActive = inst.status !== 'stopped';
                            allButtons.forEach(btn => {
                                const action = btn.dataset.action;
                                if (action === 'start') btn.disabled = isActive;
                                else if (action === 'stop') btn.disabled = !isActive;
                                else if (action === 'delete') btn.disabled = isActive;
                                else if (action === 'view') btn.disabled = (inst.status !== 'started');
                            });
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

async function initializeApp() {
    try {
        // --- NEW: Inject dynamic Python versions discovery ---
        const discoveredPyVersions = await fetchAvailablePythonVersions();
        if (discoveredPyVersions && discoveredPyVersions.length > 0) {
                state.versions.python = discoveredPyVersions;
        }

        const[systemInfo, blueprints, ports] = await Promise.all([
            fetchSystemInfo(),
            fetchAndStoreBlueprints(),
            fetchAvailablePorts()
        ]);

        state.systemInfo = systemInfo;
        state.availableBlueprints = blueprints;
        state.availablePorts = ports.available_ports;

    } catch (error) {
        console.error("Failed to initialize application:", error);
        document.body.innerHTML = `<div style="color: red; text-align: center; padding: 2rem;">
            <h1>Error Initializing Application</h1>
            <p>${error.message}</p>
            <p>Please check the console and try refreshing the page.</p>
        </div>`;
        return;
    }
    
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
        buildBtn.textContent = "Build Module";
        buildBtn.style.marginRight = "10px"; 
        buildBtn.style.backgroundColor = "#6f42c1"; 
        buildBtn.style.borderColor = "#6f42c1";
        
        buildBtn.onclick = () => {
            showBuilderView();
        };

        addBtn.parentNode.insertBefore(buildBtn, addBtn);
    } else {
        console.warn("Could not find 'Add New Instance' button to inject Builder button.");
    }
    
    // Start the polling loop
    await fetchAndRenderInstances();
    
    const initialStats = await getSystemStats();
    updateSystemStats(initialStats);
    
    showWelcomeScreen();
    
    // System stats polling (separate loop)
    setInterval(async () => {
        const stats = await getSystemStats();
        updateSystemStats(stats);
        
        // --- NEW: Polling builder status ---
        renderBuilderStatus();
    }, 2000);

    DOM.toolsCloseBtn.addEventListener('click', showWelcomeScreen);
    
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
    
    Split(['#instance-pane', '#bottom-split'], { 
        sizes: state.split.savedSizes.vertical, 
        minSize: [200, 150], 
        gutterSize: 5, 
        direction: 'vertical', 
        cursor: 'row-resize', 
        onEnd: function (sizes) { 
            state.split.savedSizes.vertical = sizes; 
            localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(state.split.savedSizes)); 
        } 
    });
    
    Split(['#tools-pane', '#monitoring-pane'], { 
        sizes: state.split.savedSizes.horizontal, 
        minSize:[300, 200], 
        gutterSize: 5, 
        direction: 'horizontal', 
        cursor: 'col-resize', 
        onEnd: function (sizes) { 
            state.split.savedSizes.horizontal = sizes; 
            localStorage.setItem(SPLIT_STORAGE_KEY, JSON.stringify(state.split.savedSizes)); 
        } 
    });

    state.viewResizeObserver = new ResizeObserver(() => { 
        if (DOM.instanceIframe && DOM.instanceIframe.contentWindow) { 
            DOM.instanceIframe.contentWindow.dispatchEvent(new Event('resize')); 
        } 
    });

    const toolsPane = document.getElementById('tools-pane');
    const resizeObserver = new ResizeObserver(() => { 
        if (state.fitAddon) { 
            try { state.fitAddon.fit(); } catch (e) { } 
        } 
    });
    resizeObserver.observe(toolsPane);
}

document.addEventListener('DOMContentLoaded', initializeApp);