import { state, DOM } from './state.js';

export function showToast(message, type = 'success') {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;

    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('show');
    }, 10);

    setTimeout(() => {
        toast.classList.remove('show');
        toast.addEventListener('transitionend', () => toast.remove());
    }, 3000);
}

function createBlueprintSelect(selectedValue = '') {
    const select = document.createElement('select');
    select.dataset.field = 'base_blueprint';
    select.required = true;

    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = 'Select a blueprint';
    defaultOption.disabled = true;
    select.appendChild(defaultOption);
    if (!selectedValue) defaultOption.selected = true;

    if (state.availableBlueprints.stock && state.availableBlueprints.stock.length > 0) {
        const stockGroup = document.createElement('optgroup');
        stockGroup.label = 'Stock';
        state.availableBlueprints.stock.forEach(bp => {
            const option = document.createElement('option');
            option.value = bp;
            option.textContent = bp;
            if (bp === selectedValue) option.selected = true;
            stockGroup.appendChild(option);
        });
        select.appendChild(stockGroup);
    }

    if (state.availableBlueprints.custom && state.availableBlueprints.custom.length > 0) {
        const customGroup = document.createElement('optgroup');
        customGroup.label = 'Custom';
        state.availableBlueprints.custom.forEach(bp => {
            const option = document.createElement('option');
            option.value = bp;
            option.textContent = bp;
            if (bp === selectedValue) option.selected = true;
            customGroup.appendChild(option);
        });
        select.appendChild(customGroup);
    }

    return select;
}

export function checkRowForChanges(row) {
    const updateButton = row.querySelector('button[data-action="update"]');
    if (!updateButton) return;

    let changed = false;

    const nameField = row.querySelector('input[data-field="name"]');
    if (nameField.value !== row.dataset.originalName) changed = true;

    const blueprintField = row.querySelector('select[data-field="base_blueprint"]');
    if (blueprintField && blueprintField.value !== row.dataset.originalBlueprint) changed = true;

    const outputPathField = row.querySelector('input[data-field="output_path"]');
    if ((outputPathField.value || '') !== (row.dataset.originalOutputPath || '')) changed = true;

    const selectedGpuIds = Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked')).map(cb => cb.value).join(',');
    if (selectedGpuIds !== row.dataset.originalGpuIds) changed = true;

    const persistentModeField = row.querySelector('input[data-field="persistent_mode"]');
    if (persistentModeField.checked.toString() !== row.dataset.originalPersistentMode) changed = true;

    const hostnameField = row.querySelector('input[data-field="hostname"]');
    if ((hostnameField.value || '') !== (row.dataset.originalHostname || '')) changed = true;

    const useHostnameField = row.querySelector('input[data-field="use_custom_hostname"]');
    if (useHostnameField.checked.toString() !== row.dataset.originalUseCustomHostname) changed = true;

    updateButton.disabled = !changed;
}

export function buildInstanceUrl(row, forView = false) {
    const isStarted = row.dataset.status === 'started';
    if (!isStarted) return '#';

    const useCustomHostname = row.dataset.useCustomHostname === 'true';
    const customHostname = row.dataset.hostname;
    const isPersistent = row.dataset.persistentMode === 'true';

    if (isPersistent) {
        const port = row.dataset.persistentPort;
        const baseUrl = `${window.location.protocol}//${window.location.hostname}:${port}`;
        return forView ? `${baseUrl}/vnc.html?resize=remote` : baseUrl;
    }

    if (useCustomHostname && customHostname) {
        return customHostname.startsWith('http') ? customHostname : `http://${customHostname}`;
    }

    // If the user wants to "Open" (not "View") a normal instance, give them the direct port link.
    if (!forView) {
        const port = row.dataset.port;
        if (port) {
            return `${window.location.protocol}//${window.location.hostname}:${port}/`;
        }
    }

    // Otherwise (for "View" or if no port), use the reverse-proxied slug.
    const instanceSlug = row.dataset.name.toLowerCase().replace(/[^a-z0-9-]/g, '-');
    return `/instance/${instanceSlug}/`;
}

export function updateInstanceRow(row, instance) {
    const isActive = instance.status !== 'stopped';

    row.dataset.status = instance.status;
    row.dataset.port = instance.port || '';
    row.dataset.persistentPort = instance.persistent_port || '';
    row.dataset.persistentMode = String(instance.persistent_mode);
    row.dataset.name = instance.name;
    row.dataset.hostname = instance.hostname || '';
    row.dataset.useCustomHostname = String(instance.use_custom_hostname);

    const statusSpan = row.querySelector('.status');
    statusSpan.textContent = instance.status;
    statusSpan.className = `status status-${instance.status.toLowerCase()}`;

    const displayPort = instance.persistent_mode ? instance.persistent_port : instance.port;
    row.cells[8].textContent = displayPort || 'N/A';

    row.querySelector('[data-action="start"]').disabled = isActive;
    row.querySelector('[data-action="stop"]').disabled = !isActive;
    row.querySelector('[data-action="delete"]').disabled = isActive;

    const openButton = row.querySelector('[data-action="open"]');
    const viewButton = row.querySelector('[data-action="view"]');
    const openHref = buildInstanceUrl(row, false);

    openButton.href = openHref;
    openButton.classList.toggle('disabled', openHref === '#');
    viewButton.disabled = (instance.status !== 'started');

    checkRowForChanges(row);
}

export function renderInstanceRow(instance, isNew = false, level = 0) {
    const row = document.createElement('tr');
    row.dataset.id = instance.id;
    row.dataset.isNew = String(isNew);
    row.dataset.parentId = instance.parent_instance_id || '';

    if (level > 0) {
        row.classList.add('satellite-instance');
    }

    row.dataset.originalName = instance.name || '';
    row.dataset.originalBlueprint = instance.base_blueprint || '';
    row.dataset.originalGpuIds = instance.gpu_ids || '';
    row.dataset.originalAutostart = String(instance.autostart);
    row.dataset.originalPersistentMode = String(instance.persistent_mode);
    row.dataset.originalHostname = instance.hostname || '';
    row.dataset.originalUseCustomHostname = String(instance.use_custom_hostname);
    row.dataset.originalOutputPath = instance.output_path || '';

    row.dataset.status = instance.status;
    row.dataset.name = instance.name || '';
    row.dataset.port = instance.port || '';
    row.dataset.persistentPort = instance.persistent_port || '';
    row.dataset.persistentMode = String(instance.persistent_mode);
    row.dataset.hostname = instance.hostname || '';
    row.dataset.useCustomHostname = String(instance.use_custom_hostname);

    const handleCell = row.insertCell();
    if (!isNew) {
        handleCell.classList.add('drag-handle');
        handleCell.innerHTML = '&#x2630;';
    }

    const nameCell = row.insertCell();
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.value = instance.name || '';
    nameInput.dataset.field = 'name';
    nameInput.required = true;
    nameInput.disabled = false;
    nameCell.appendChild(nameInput);
    nameCell.style.paddingLeft = `${level * 20 + 5}px`;
    if (level > 0) {
        nameCell.style.setProperty('--level-indent', `${level * 20}px`);
        nameCell.classList.add('indented-cell');
    }


    const blueprintSelect = createBlueprintSelect(instance.base_blueprint);
    blueprintSelect.disabled = (level > 0); // Disable for satellites
    row.insertCell().appendChild(blueprintSelect);

    const outputPathInput = document.createElement('input');
    outputPathInput.type = 'text';
    outputPathInput.value = instance.output_path || '';
    outputPathInput.dataset.field = 'output_path';
    outputPathInput.placeholder = 'Optional: /path/to/outputs';
    outputPathInput.disabled = false;
    row.insertCell().appendChild(outputPathInput);

    const gpuCell = row.insertCell();
    const gpuContainer = document.createElement('div');
    gpuContainer.className = 'gpu-checkbox-container';
    const assignedGpus = (instance.gpu_ids || '').split(',').filter(id => id);
    
    const gpuCount = (state.systemInfo.gpus && Array.isArray(state.systemInfo.gpus)) ? state.systemInfo.gpus.length : (state.systemInfo.gpu_count || 0);
    
    for (let i = 0; i < gpuCount; i++) {
        const label = document.createElement('label');
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.name = `gpu_id_${instance.id || 'new'}_${i}`;
        checkbox.value = i;
        if (assignedGpus.includes(String(i))) checkbox.checked = true;
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(` ${i}`));
        gpuContainer.appendChild(label);
    }
    if (gpuCount === 0) gpuContainer.textContent = 'N/A';
    gpuCell.appendChild(gpuContainer);

    const autostartCheckbox = document.createElement('input');
    autostartCheckbox.type = 'checkbox';
    autostartCheckbox.checked = instance.autostart;
    autostartCheckbox.dataset.field = 'autostart';
    row.insertCell().appendChild(autostartCheckbox);

    const persistentModeCheckbox = document.createElement('input');
    persistentModeCheckbox.type = 'checkbox';
    persistentModeCheckbox.checked = instance.persistent_mode;
    persistentModeCheckbox.dataset.field = 'persistent_mode';
    persistentModeCheckbox.disabled = false;
    row.insertCell().appendChild(persistentModeCheckbox);

    row.insertCell().innerHTML = `<span class="status status-${instance.status.toLowerCase()}">${instance.status}</span>`;

    const hostnameCell = row.insertCell();
    const hostnameContainer = document.createElement('div');
    hostnameContainer.className = 'hostname-container';
    const useHostnameLabel = document.createElement('label');
    useHostnameLabel.className = 'switch-label';
    const useHostnameCheckbox = document.createElement('input');
    useHostnameCheckbox.type = 'checkbox';
    useHostnameCheckbox.checked = instance.use_custom_hostname;
    useHostnameCheckbox.dataset.field = 'use_custom_hostname';
    const switchSpan = document.createElement('span');
    switchSpan.className = 'switch';
    useHostnameLabel.appendChild(useHostnameCheckbox);
    useHostnameLabel.appendChild(switchSpan);
    const hostnameInput = document.createElement('input');
    hostnameInput.type = 'text';
    hostnameInput.value = instance.hostname || '';
    hostnameInput.placeholder = 'e.g., my-app.local';
    hostnameInput.dataset.field = 'hostname';
    hostnameContainer.appendChild(useHostnameLabel);
    hostnameContainer.appendChild(hostnameInput);
    hostnameCell.appendChild(hostnameContainer);

    const portCell = row.insertCell();
    if (isNew) {
        const portSelect = document.createElement('select');
        portSelect.dataset.field = 'port';
        const autoOption = document.createElement('option');
        autoOption.value = '';
        autoOption.textContent = 'Auto';
        portSelect.appendChild(autoOption);
        state.availablePorts.forEach(port => {
            const option = document.createElement('option');
            option.value = port;
            option.textContent = port;
            portSelect.appendChild(option);
        });
        portCell.appendChild(portSelect);
    } else {
        const displayPort = instance.persistent_mode ? instance.persistent_port : instance.port;
        portCell.textContent = displayPort || 'N/A';
    }

    const actionsCell = row.insertCell();
    actionsCell.classList.add('actions-column');
    if (isNew) {
        actionsCell.innerHTML = `
            <button class="action-btn" data-action="save" data-id="new" disabled>Save</button>
            <button class="action-btn" data-action="cancel_new">Cancel</button>
            <span class="action-btn-placeholder"></span><span class="action-btn-placeholder"></span>
            <span class="action-btn-placeholder"></span><span class="action-btn-placeholder"></span>
            <span class="action-btn-placeholder"></span><span class="action-btn-placeholder"></span>`;
    } else {
        const openHref = buildInstanceUrl(row, false);
        const isStarted = instance.status === 'started';
        const isStopped = instance.status === 'stopped';
        actionsCell.innerHTML = `
            <button class="action-btn" data-action="start" data-id="${instance.id}" ${!isStopped ? 'disabled' : ''}>Start</button>
            <button class="action-btn" data-action="stop" data-id="${instance.id}" ${isStopped ? 'disabled' : ''}>Stop</button>
            <button class="action-btn" data-action="logs" data-id="${instance.id}">Logs</button>
            <button class="action-btn" data-action="tools_menu" data-id="${instance.id}">Tools</button>
            <button class="action-btn" data-action="update" data-id="${instance.id}" disabled>Update</button>
            <button class="action-btn" data-action="delete" data-id="${instance.id}" ${!isStopped ? 'disabled' : ''}>Delete</button>
            <button class="action-btn" data-action="view" data-id="${instance.id}" ${!isStarted ? 'disabled' : ''}>View</button>
            <a href="${openHref}" class="action-btn ${openHref === '#' ? 'disabled' : ''}" data-action="open" data-id="${instance.id}" target="_blank">Open</a>`;
    }

    const allFields = row.querySelectorAll('input, select');
    if (isNew) {
        const saveButton = row.querySelector('button[data-action="save"]');
        allFields.forEach(field => field.addEventListener('input', () => {
            const name = row.querySelector('input[data-field="name"]').value;
            const bp = row.querySelector('select[data-field="base_blueprint"]').value;
            saveButton.disabled = !name || !bp;
        }));

        let isOutputPathDirty = false;
        outputPathInput.addEventListener('input', () => { isOutputPathDirty = true; });
        nameInput.addEventListener('input', () => { if (!isOutputPathDirty) { outputPathInput.value = nameInput.value; } });
        
    } else {
        allFields.forEach(field => {
            if (field.dataset.field !== 'autostart') {
                field.addEventListener('input', () => checkRowForChanges(row));
            }
        });
    }
    return row;
}

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

export async function updateSystemStats(stats) {
    if (!stats) return;
    DOM.cpuProgress.style.width = `${stats.cpu_percent}%`;
    DOM.cpuPercentText.textContent = `${stats.cpu_percent.toFixed(1)}%`;
    DOM.ramProgress.style.width = `${stats.ram.percent}%`;
    DOM.ramUsageText.textContent = `${formatBytes(stats.ram.used)} / ${formatBytes(stats.ram.total)}`;
    DOM.gpuStatsContainer.innerHTML = '';
    if (stats.gpus && stats.gpus.length > 0) {
        stats.gpus.forEach(gpu => {
            const gpuEl = DOM.gpuStatTemplate.content.cloneNode(true);
            gpuEl.querySelector('.gpu-name').textContent = `GPU ${gpu.id}: ${gpu.name}`;
            gpuEl.querySelector('.vram-progress').style.width = `${gpu.vram.percent}%`;
            gpuEl.querySelector('.vram-usage-text').textContent = `${formatBytes(gpu.vram.used)} / ${formatBytes(gpu.vram.total)}`;
            gpuEl.querySelector('.util-progress').style.width = `${gpu.utilization_percent}%`;
            gpuEl.querySelector('.util-percent-text').textContent = `${gpu.utilization_percent}%`;
            DOM.gpuStatsContainer.appendChild(gpuEl);
        });
    } else {
        DOM.gpuStatsContainer.innerHTML = '<p style="text-align:center;color:#aaa;">No NVIDIA GPUs detected.</p>';
    }
}
