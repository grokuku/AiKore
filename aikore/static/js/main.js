import { state, DOM } from './state.js';
import { fetchSystemInfo, fetchAndStoreBlueprints, fetchAvailablePorts, getSystemStats } from './api.js';
import { renderInstanceRow, updateSystemStats, checkRowForChanges } from './ui.js';
import { setupModalEventHandlers } from './modals.js';
import { setupMainEventListeners } from './eventHandlers.js';
import { showWelcomeScreen } from './tools.js';

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
        // However, renderInstanceRow logic usually recreates rows unless we diff them.
        // Current logic clears innerHTML. This is destructive to input focus!
        // FIX: If there are dirty rows or active focus, we should update ONLY statuses if possible,
        // or rely on the fact that standard HTML inputs lose focus on innerHTML swap.
        // To keep it simple and robust given the existing architecture:
        // We check if user is interacting.
        
        const activeElement = document.activeElement;
        const isInteracting = activeElement && activeElement.closest('#instances-tbody tr');
        
        // If user is typing, skip full re-render to avoid focus loss, 
        // BUT we still want to fetch statuses if possible.
        // For now, let's pause render if interacting, but still fetch to check for 'starting' status?
        // No, if we don't render, we don't know if we need fast polling.
        // Let's proceed with fetch.
        
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

        // Check if we have dirty rows before wiping tbody
        // If we wipe tbody, we lose changes!
        // Ideally we should diff. 
        // Since we don't have a Virtual DOM, we will use a simple heuristic:
        // If there are ANY dirty rows, we DO NOT re-render the table structure.
        // We only update status columns and buttons for existing rows.
        const dirtyRows = document.querySelectorAll('tr.row-dirty');
        if (dirtyRows.length > 0) {
             // Partial Update Mode
             instances.forEach(inst => {
                 const row = DOM.instancesTbody.querySelector(`tr[data-id="${inst.id}"]`);
                 if (row) {
                     // Only update status/buttons logic, do not touch inputs
                     // We need a specialized update function or just update the status text directly
                     // reusing renderInstanceRow is too aggressive.
                     // Let's use a lightweight update
                     const statusSpan = row.querySelector('.status');
                     if (statusSpan && row.dataset.status !== inst.status) {
                         statusSpan.textContent = inst.status;
                         statusSpan.className = `status status-${inst.status.toLowerCase()}`;
                         row.dataset.status = inst.status;
                         
                         // Re-evaluate buttons
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
            // Full Re-render Mode
            DOM.instancesTbody.innerHTML = '';
            
            const renderNode = (node, level) => {
                const row = renderInstanceRow(node, false, level);
                DOM.instancesTbody.appendChild(row);
                if (node.children.length > 0) {
                    node.children.forEach(child => renderNode(child, level + 1));
                }
            };

            rootInstances.forEach(node => renderNode(node, 0));

            const newInstanceRow = document.querySelector('tr[data-is-new="true"]'); // It might have been wiped?
            // Actually, if we wipe innerHTML, 'newInstanceRow' reference is lost if it was inside.
            // But renderInstanceRow creates elements. 
            // If user was creating a new instance, it wasn't saved, so it's not in API.
            // We might lose the "New Instance" row on refresh if we don't preserve it.
            // Ideally, "New Instance" row prevents re-render via the 'isInteracting' check if focused,
            // but if not focused, it might vanish.
            // For now, acceptable trade-off or user must type to keep focus.
        }

        if (DOM.instancesTbody.childElementCount === 0) {
            DOM.instancesTbody.innerHTML = `<tr class="no-instances-row"><td colspan="11" style="text-align: center;">No instances created yet.</td></tr>`;
        }
    } catch (error) {
        console.error("Failed to fetch instances:", error);
        // DOM.instancesTbody.innerHTML = `<tr><td colspan="11" style="text-align:center;">Error loading data. Check console.</td></tr>`;
    } finally {
        scheduleNextPoll(nextInterval);
    }
}

async function initializeApp() {
    try {
        const [systemInfo, blueprints, ports] = await Promise.all([
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
    
    // Start the polling loop
    await fetchAndRenderInstances();
    
    const initialStats = await getSystemStats();
    updateSystemStats(initialStats);
    
    showWelcomeScreen();
    
    // System stats polling (separate loop)
    setInterval(async () => {
        const stats = await getSystemStats();
        updateSystemStats(stats);
    }, 2000);

    DOM.toolsCloseBtn.addEventListener('click', showWelcomeScreen);
    
    new Sortable(DOM.instancesTbody, {
        animation: 150, 
        handle: '.drag-handle', 
        ghostClass: 'sortable-ghost', 
        dragClass: 'sortable-drag',
        onEnd: function (evt) {
            // Save order of ROOT instances only?
            // Or save all?
            // Since the renderer rebuilds the tree based on parent_id, 
            // changing the order of satellites in the DOM is purely visual until refresh.
            // We only care about the order of Parent rows.
            const rows = DOM.instancesTbody.querySelectorAll('tr[data-id]');
            // Filter only root instances for the order preference
            const newOrder = Array.from(rows)
                .filter(row => !row.dataset.parentId) // Only roots
                .map(row => row.dataset.id)
                .filter(id => id && id !== 'new');
            localStorage.setItem(INSTANCE_ORDER_KEY, JSON.stringify(newOrder));
            
            // Trigger a re-render to snap children back to parents if user dragged them weirdly
            // setTimeout(() => fetchAndRenderInstances(), 500); 
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
        minSize: [300, 200], 
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