import { state, DOM } from './state.js';
import { fetchSystemInfo, fetchAndStoreBlueprints, fetchAvailablePorts, getSystemStats } from './api.js';
import { renderInstanceRow, updateSystemStats } from './ui.js';
import { setupModalEventHandlers } from './modals.js';
import { setupMainEventListeners } from './eventHandlers.js';
import { showWelcomeScreen } from './tools.js';

const INSTANCE_ORDER_KEY = 'aikoreInstanceOrder';

export async function fetchAndRenderInstances() {
    try {
        if (document.activeElement && document.activeElement.closest('#instances-tbody tr')) {
            return;
        }

        const newInstanceRow = DOM.instancesTbody.querySelector('tr[data-is-new="true"]');

        const response = await fetch('/api/instances/');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        let instances = await response.json();

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

        DOM.instancesTbody.innerHTML = '';
        
        function renderNode(node, level) {
            const row = renderInstanceRow(node, false, level);
            DOM.instancesTbody.appendChild(row);
            if (node.children.length > 0) {
                node.children.forEach(child => renderNode(child, level + 1));
            }
        }

        rootInstances.forEach(node => renderNode(node, 0));

        if (newInstanceRow) {
            DOM.instancesTbody.appendChild(newInstanceRow);
        }

        if (DOM.instancesTbody.childElementCount === 0) {
            DOM.instancesTbody.innerHTML = `<tr class="no-instances-row"><td colspan="11" style="text-align: center;">No instances created yet.</td></tr>`;
        }
    } catch (error) {
        console.error("Failed to fetch instances:", error);
        if (state.instancesPollInterval) clearInterval(state.instancesPollInterval);
        DOM.instancesTbody.innerHTML = `<tr><td colspan="11" style="text-align:center;">Error loading data. Check console.</td></tr>`;
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
    
    await fetchAndRenderInstances();
    
    const initialStats = await getSystemStats();
    updateSystemStats(initialStats);
    
    showWelcomeScreen();
    
    if (state.instancesPollInterval) clearInterval(state.instancesPollInterval);
    state.instancesPollInterval = setInterval(fetchAndRenderInstances, 2000);
    setInterval(async () => {
        const stats = await getSystemStats();
        updateSystemStats(stats);
    }, 2000);

    DOM.toolsCloseBtn.addEventListener('click', showWelcomeScreen);
    
    new Sortable(DOM.instancesTbody, {
        animation: 150, handle: '.drag-handle', ghostClass: 'sortable-ghost', dragClass: 'sortable-drag',
        onEnd: function (evt) {
            const rows = DOM.instancesTbody.querySelectorAll('tr[data-id]');
            const newOrder = Array.from(rows).map(row => row.dataset.id).filter(id => id && id !== 'new');
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
