import { state, DOM } from './state.js';
import { fetchTorchVersions } from './api.js'; // --- NEW IMPORT ---
import { HolafToast } from '../vendor/holaf-toast.js';
import { HolafIcons } from '../vendor/holaf-icons.js';

export function showToast(message, type = 'success') {
    // Use HolafToast brique for professional notifications
    HolafToast.show({
        message,
        type: type === 'error' ? 'error' : (type === 'warning' ? 'warning' : (type === 'info' ? 'info' : 'success')),
        duration: 10000 // 10 seconds
    });
}

/**
 * Rewrites a button label, optionally prefixed with a HolafIcons icon.
 * Use instead of `btn.textContent = ...` on buttons whose icon is injected at
 * boot (main.js static pass): a plain textContent assignment strips the SVG.
 */
export function setButtonLabel(btn, label, iconName = null) {
    if (!btn) return;
    const prefix = iconName ? `${HolafIcons.render(iconName, { size: 14 })} ` : '';
    btn.innerHTML = prefix + label;
}

function createBlueprintSelect(selectedValue = '') {
    // --- Custom dropdown that shows blueprint name + category (right-aligned, darker) ---
    // Uses fixed positioning on body to escape overflow clipping and survive re-renders.
    const wrapper = document.createElement('div');
    wrapper.className = 'blueprint-select';
    wrapper.dataset.field = 'base_blueprint';
    wrapper.dataset.value = selectedValue;

    // Header / trigger button
    const header = document.createElement('div');
    header.className = 'bp-select-header';
    header.tabIndex = 0;
    wrapper.appendChild(header);

    const nameSpan = document.createElement('span');
    nameSpan.className = 'bp-selected-name';
    nameSpan.textContent = selectedValue || 'Select a blueprint';
    header.appendChild(nameSpan);

    const arrow = document.createElement('span');
    arrow.className = 'bp-select-arrow';
    arrow.innerHTML = HolafIcons.render('chevron-down', { size: 12 });
    header.appendChild(arrow);

    // Dropdown panel (will be moved to document.body when open)
    const dropdown = document.createElement('div');
    dropdown.className = 'bp-select-dropdown';

    // Backdrop overlay (closes dropdown on outside click)
    const backdrop = document.createElement('div');
    backdrop.className = 'bp-select-backdrop';

    function addOptions(groupLabel, bpList) {
        if (!bpList || bpList.length === 0) return;
        const groupEl = document.createElement('div');
        groupEl.className = 'bp-option-group';
        const label = document.createElement('div');
        label.className = 'bp-group-label';
        label.textContent = groupLabel;
        groupEl.appendChild(label);
        bpList.forEach(bp => {
            const isObj = typeof bp === 'object' && bp !== null;
            const filename = isObj ? bp.filename : bp;
            const category = isObj ? (bp.category || '') : '';

            const opt = document.createElement('div');
            opt.className = 'bp-option';
            opt.dataset.value = filename;
            if (filename === selectedValue) opt.classList.add('selected');

            const optName = document.createElement('span');
            optName.className = 'bp-option-name';
            optName.textContent = filename;
            opt.appendChild(optName);

            if (category) {
                const optCat = document.createElement('span');
                optCat.className = 'bp-option-category';
                optCat.textContent = category;
                opt.appendChild(optCat);
            }

            opt.addEventListener('mousedown', (e) => {
                e.preventDefault(); // Prevent blur on header
                e.stopPropagation();
            });
            opt.addEventListener('click', () => {
                setValue(filename);
                closeDropdown();
                wrapper.dispatchEvent(new Event('change', { bubbles: true }));
                wrapper.dispatchEvent(new Event('input', { bubbles: true }));
            });
            opt.addEventListener('mouseenter', () => opt.classList.add('hover'));
            opt.addEventListener('mouseleave', () => opt.classList.remove('hover'));

            groupEl.appendChild(opt);
        });
        dropdown.appendChild(groupEl);
    }

    addOptions('Stock', state.availableBlueprints.stock);
    addOptions('Custom', state.availableBlueprints.custom);

    function setValue(val) {
        wrapper.dataset.value = val;
        nameSpan.textContent = val || 'Select a blueprint';
        // Highlight selected option
        dropdown.querySelectorAll('.bp-option').forEach(o => {
            o.classList.toggle('selected', o.dataset.value === val);
        });
    }

    function positionDropdown() {
        const rect = header.getBoundingClientRect();
        const vh = window.innerHeight;
        const spaceBelow = vh - rect.bottom;
        const spaceAbove = rect.top;

        const minH = 120;
        const maxH = Math.min(400, vh * 0.4);
        let dropdownH;

        if (spaceBelow >= minH) {
            // Open below
            dropdown.style.top = rect.bottom + 'px';
            dropdownH = Math.min(maxH, spaceBelow - 8);
            dropdown.style.maxHeight = dropdownH + 'px';
        } else if (spaceAbove >= minH) {
            // Open above
            dropdown.style.bottom = (vh - rect.top + 2) + 'px';
            dropdown.style.top = 'auto';
            dropdownH = Math.min(maxH, spaceAbove - 8);
            dropdown.style.maxHeight = dropdownH + 'px';
        } else {
            // Not enough space either way — open below anyway with minimal height
            dropdown.style.top = rect.bottom + 'px';
            dropdown.style.maxHeight = Math.max(minH, spaceBelow - 8) + 'px';
        }
        dropdown.style.left = rect.left + 'px';
        dropdown.style.width = rect.width + 'px';
    }

    function openDropdown() {
        if (wrapper.classList.contains('disabled')) return;
        // Move dropdown + backdrop to body for fixed positioning
        // (avoids overflow clipping and survives table re-renders)
        if (dropdown.parentNode !== document.body) document.body.appendChild(dropdown);
        if (backdrop.parentNode !== document.body) document.body.appendChild(backdrop);
        dropdown.style.display = 'block';
        backdrop.style.display = 'block';
        wrapper.classList.add('open');
        positionDropdown();
    }

    function closeDropdown() {
        dropdown.style.display = 'none';
        backdrop.style.display = 'none';
        wrapper.classList.remove('open');
        // Cleanup: remove from body if present
        if (dropdown.parentNode === document.body) document.body.removeChild(dropdown);
        if (backdrop.parentNode === document.body) document.body.removeChild(backdrop);
    }

    header.addEventListener('mousedown', (e) => {
        e.preventDefault();
        if (wrapper.classList.contains('disabled')) return;
        if (wrapper.classList.contains('open')) {
            closeDropdown();
        } else {
            openDropdown();
        }
    });
    header.addEventListener('focus', () => {
        wrapper.dispatchEvent(new Event('focus', { bubbles: true }));
    });
    header.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeDropdown();
    });

    // Backdrop click closes dropdown
    backdrop.addEventListener('mousedown', (e) => {
        e.preventDefault();
        closeDropdown();
    });

    // Reposition on window resize while open
    window.addEventListener('resize', () => {
        if (wrapper.classList.contains('open')) positionDropdown();
    });
    // Close dropdown if the header scrolls out of view
    // (since fixed-positioned dropdown won't follow the scroll)
    const scrollCloseHandler = () => {
        if (wrapper.classList.contains('open')) {
            const rect = header.getBoundingClientRect();
            if (rect.bottom < 0 || rect.top > window.innerHeight) {
                closeDropdown();
            }
        }
    };
    // Attach to scrollable parents (the instance pane has overflow: auto)
    const attachScrollListeners = () => {
        let el = header.parentElement;
        while (el) {
            if (el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight) {
                el.addEventListener('scroll', scrollCloseHandler, { passive: true });
            }
            el = el.parentElement;
            if (el === document.body) break;
        }
    };
    // We'll attach after the element is in the DOM (use requestAnimationFrame)
    requestAnimationFrame(attachScrollListeners);

    // Expose value/disabled properties like a native select
    Object.defineProperty(wrapper, 'value', {
        get: () => wrapper.dataset.value || '',
        set: (v) => setValue(v),
        configurable: true
    });
    Object.defineProperty(wrapper, 'disabled', {
        get: () => wrapper.classList.contains('disabled'),
        set: (v) => {
            if (v) {
                wrapper.classList.add('disabled');
                header.tabIndex = -1;
                closeDropdown(); // Close if open
            } else {
                wrapper.classList.remove('disabled');
                header.tabIndex = 0;
            }
        },
        configurable: true
    });

    // Cleanup: close overlay if wrapper is removed from DOM (e.g. during table re-render)
    let _checkTimer = null;
    const _origClose = closeDropdown;
    closeDropdown = function() {
        if (_checkTimer) { clearInterval(_checkTimer); _checkTimer = null; }
        _origClose();
    };
    const _origOpen = openDropdown;
    openDropdown = function() {
        _origOpen();
        // Periodically check if wrapper is still in the DOM
        _checkTimer = setInterval(() => {
            if (!document.body.contains(wrapper)) closeDropdown();
        }, 400);
    };

    return wrapper;
}

// --- HELPER: Normalize Data for Comparison ---
function normalizeGpuIds(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .split(',')
        .map(s => s.trim()) // Remove spaces "0, 1" -> "0,1"
        .filter(s => s !== '')
        .sort() // Ensure order doesn't matter
        .join(',');
}

function normalizeStr(str) {
    return (str === null || str === undefined) ? '' : String(str);
}

// --- GPU list helpers -------------------------------------------------------
// The GPU list driving the instance GPU checkboxes lives in state.systemInfo
// (/api/system/info). During the progressive boot that payload may not have
// arrived when the instance table is first rendered, so we also fall back to
// the cached /api/system/stats payload (the source of the monitoring panel,
// which already proved the GPUs are present). Returns an array (possibly empty).
function getGpuList() {
    const sysGpus = state.systemInfo && Array.isArray(state.systemInfo.gpus)
        ? state.systemInfo.gpus
        : null;
    if (sysGpus && sysGpus.length > 0) return sysGpus;

    const statGpus = state.systemStats && Array.isArray(state.systemStats.gpus)
        ? state.systemStats.gpus
        : null;
    if (statGpus && statGpus.length > 0) return statGpus;

    // /api/system/info answered with a GPU count but no array detail — fabricate
    // the expected count so checkboxes render.
    if (state.systemInfo && state.systemInfo.gpu_count) {
        return new Array(state.systemInfo.gpu_count).fill({});
    }

    return [];
}

function getGpuCount() {
    return getGpuList().length;
}

// Safely compute the gpu_ids the user effectively has on a row. Guards against
// wiping an existing assignment when the GPU list hasn't loaded yet (so the
// checkboxes simply don't exist to be checked): in that case the original,
// DB-persisted assignment is preserved instead of being replaced by "".
export function resolveGpuIds(row) {
    const selected = Array.from(row.querySelectorAll('input[name^="gpu_id_"]:checked'))
        .map(cb => cb.value)
        .join(','); // Already sorted by DOM order (0, 1, 2)
    if (selected !== '') return selected;

    const original = (row.dataset.originalGpuIds || '').split(',').filter(Boolean).join(',');
    const listLoaded = getGpuCount() > 0;
    if (original && !listLoaded) {
        // GPU list not revealed yet — the empty selection is not a real user
        // decision (no checkboxes could be rendered), so keep the assignment.
        return original;
    }
    return selected; // '' is only honored once the GPU list is actually present
}

// Rebuild every instance row's GPU checkboxes from the latest GPU list, while
// preserving whatever the user has currently ticked. Safe to run at any time
// (cheap, no-op when nothing changed).
export function refreshAllGpuCells() {
    const gpuCount = getGpuCount();
    if (gpuCount === state.lastGpuCount && state.gpuDataLoaded) return;

    const rows = document.querySelectorAll('#instances-table tr');
    rows.forEach(row => {
        const cell = row.querySelector('.gpu-checkbox-container');
        if (!cell) return;

        const instanceId = row.dataset.id;
        // Preserve current ticked GPUs across a rebuild.
        const selected = Array.from(cell.querySelectorAll('input[name^="gpu_id_"]:checked'))
            .map(cb => Number(cb.value));
        // Also restore the DB-persisted assignment in case nothing is ticked yet.
        const assignedGpus = normalizeGpuIds(row.dataset.originalGpuIds || '').split(',').filter(Boolean);

        const minCount = assignedGpus.reduce((m, id) => Math.max(m, parseInt(id, 10) + 1), 0);
        const count = Math.max(gpuCount, minCount);

        cell.innerHTML = '';
        for (let i = 0; i < count; i++) {
            const label = document.createElement('label');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.name = `gpu_id_${instanceId || 'new'}_${i}`;
            checkbox.value = i;
            checkbox.checked = selected.includes(i) || assignedGpus.includes(String(i));
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(` ${i}`));
            cell.appendChild(label);
        }
        if (count === 0) cell.textContent = 'N/A';

        checkRowForChanges(row);
    });

    state.lastGpuCount = gpuCount;
    state.gpuDataLoaded = true;
}


export function checkRowForChanges(row) {
    let changed = false;

    // Defensive checks with Strict Normalization
    const nameField = row.querySelector('input[data-field="name"]');
    if (nameField && nameField.value !== row.dataset.originalName) changed = true;

    const blueprintField = row.querySelector('[data-field="base_blueprint"]');
    // Only check if NOT disabled (Satellites are disabled)
    if (blueprintField && !blueprintField.disabled && blueprintField.value !== row.dataset.originalBlueprint) changed = true;

    const outputPathField = row.querySelector('input[data-field="output_path"]');
    if (outputPathField && !outputPathField.disabled && normalizeStr(outputPathField.value) !== row.dataset.originalOutputPath) changed = true;

    // GPU Logic: Get checked boxes, normalize them, compare with normalized original
    const currentGpuIds = resolveGpuIds(row);
    
    if (normalizeGpuIds(currentGpuIds) !== row.dataset.originalGpuIds) changed = true;

    const persistentModeField = row.querySelector('input[data-field="persistent_mode"]');
    if (persistentModeField && persistentModeField.checked.toString() !== row.dataset.originalPersistentMode) changed = true;

    const hostnameField = row.querySelector('input[data-field="hostname"]');
    if (hostnameField && normalizeStr(hostnameField.value) !== row.dataset.originalHostname) changed = true;

    const useHostnameField = row.querySelector('input[data-field="use_custom_hostname"]');
    if (useHostnameField && useHostnameField.checked.toString() !== row.dataset.originalUseCustomHostname) changed = true;

    const portField = row.querySelector('select[data-field="port"]');
    // Compare string values to handle "19000" (str) vs 19000 (int)
    if (portField && normalizeStr(portField.value) !== row.dataset.originalPort) changed = true;

    const autostartField = row.querySelector('input[data-field="autostart"]');
    if (autostartField && autostartField.checked.toString() !== row.dataset.originalAutostart) changed = true;

    // --- NEW: Env Fields ---
    const pyField = row.querySelector('select[data-field="python_version"]');
    if (pyField && !pyField.disabled && normalizeStr(pyField.value) !== row.dataset.originalPythonVersion) changed = true;

    const cudaField = row.querySelector('select[data-field="cuda_version"]');
    if (cudaField && !cudaField.disabled && normalizeStr(cudaField.value) !== row.dataset.originalCudaVersion) changed = true;

    const torchField = row.querySelector('select[data-field="torch_version"]');
    if (torchField && !torchField.disabled && normalizeStr(torchField.value) !== row.dataset.originalTorchVersion) changed = true;

    // Toggle dirty class
    if (changed) {
        row.classList.add('row-dirty');
    } else {
        row.classList.remove('row-dirty');
    }

    // Update Global Save Button visibility
    updateGlobalSaveButton();
}

function updateGlobalSaveButton() {
    const dirtyRows = document.querySelectorAll('tr.row-dirty');
    const saveBtn = document.getElementById('global-save-btn');
    const dirtyCountSpan = document.getElementById('dirty-count');

    if (saveBtn) {
        if (dirtyRows.length > 0) {
            saveBtn.style.display = 'inline-block';
            dirtyCountSpan.textContent = dirtyRows.length;
        } else {
            saveBtn.style.display = 'none';
        }
    }
}

export function buildInstanceUrl(row, forView = false) {
    const isStarted = row.dataset.status === 'started';
    if (!isStarted) return '#';

    const useCustomHostname = row.dataset.useCustomHostname === 'true';
    const customHostname = row.dataset.hostname;
    const isPersistent = row.dataset.persistentMode === 'true';

    const persistentPort = row.dataset.persistentPort;

    if (isPersistent) {
        // Persistent mode: direct access to VNC/Kasm interface on persistent_port
        const baseUrl = `${window.location.protocol}//${window.location.hostname}:${persistentPort}`;
        return forView ? `${baseUrl}/vnc.html?resize=remote` : baseUrl;
    }

    if (useCustomHostname && customHostname) {
        // Custom hostname: user-provided URL (e.g., for reverse proxy setups)
        return customHostname.startsWith('http') ? customHostname : `http://${customHostname}`;
    }

    // Normal mode: always use the nginx proxy path
    const instanceSlug = row.dataset.name.toLowerCase().replace(/[^a-z0-9-]/g, '-');
    return `/instance/${instanceSlug}/`;
}

export function updateInstanceRow(row, instance) {
    const isActive = instance.status !== 'stopped';
    const isInstalling = instance.status === 'installing';

    row.dataset.status = instance.status;
    row.dataset.port = instance.port || '';
    row.dataset.persistentPort = instance.persistent_port || '';
    row.dataset.persistentMode = String(instance.persistent_mode);
    row.dataset.name = instance.name;
    row.dataset.hostname = instance.hostname || '';
    row.dataset.useCustomHostname = String(instance.use_custom_hostname);

    const currentPublicPort = instance.persistent_mode ? instance.persistent_port : instance.port;
    
    // Sync originals ONLY if row is NOT dirty (prevents overwriting user typing)
    if (!row.classList.contains('row-dirty')) {
         row.dataset.originalPort = normalizeStr(currentPublicPort);
         // No need to sync others here, they are static or handled by render
    }

    const statusSpan = row.querySelector('.status');
    if (statusSpan) {
        statusSpan.textContent = instance.status;
        statusSpan.className = `status status-${instance.status.toLowerCase()}`;
    }

    // Update Port Select logic...
    const portSelect = row.querySelector('select[data-field="port"]');
    if (portSelect) {
        // Ensure "Auto" option exists
        let autoOption = portSelect.querySelector('option[value=""]');
        if (!autoOption) {
            autoOption = document.createElement('option');
            autoOption.value = '';
            autoOption.textContent = 'Auto';
            portSelect.insertBefore(autoOption, portSelect.firstChild);
        }

        if (currentPublicPort) {
            let optionFound = false;
            for (let i = 0; i < portSelect.options.length; i++) {
                if (portSelect.options[i].value == currentPublicPort) {
                    if (!row.classList.contains('row-dirty')) {
                        portSelect.options[i].selected = true;
                    }
                    optionFound = true;
                    break;
                }
            }
            if (!optionFound) {
                const option = document.createElement('option');
                option.value = currentPublicPort;
                option.textContent = currentPublicPort;
                if (!row.classList.contains('row-dirty')) {
                    option.selected = true;
                }
                portSelect.insertBefore(option, portSelect.firstChild);
            }
        } else if (!row.classList.contains('row-dirty')) {
            portSelect.value = '';
        }
    }

    const allButtons = row.querySelectorAll('button.action-btn, a.action-btn');
    allButtons.forEach(btn => {
        if (isInstalling) {
            btn.disabled = true;
            btn.classList.add('disabled');
        } else {
            btn.classList.remove('disabled');
            const action = btn.dataset.action;
            if (action === 'start') btn.disabled = isActive;
            else if (action === 'stop') btn.disabled = !isActive;
            else if (action === 'delete') btn.disabled = isActive;
            else if (action === 'view') btn.disabled = (instance.status !== 'started');
        }
    });

    const openButton = row.querySelector('[data-action="open"]');
    if (openButton) {
        const openHref = buildInstanceUrl(row, false);
        openButton.href = openHref;
        if (isInstalling) {
            openButton.classList.add('disabled');
        } else {
            openButton.classList.toggle('disabled', openHref === '#');
        }
    }

    if (!isInstalling) {
        checkRowForChanges(row);
    }
}

export function renderInstanceRow(instance, isNew = false, level = 0) {
    const row = document.createElement('tr');
    row.dataset.id = instance.id;
    row.dataset.isNew = String(isNew);
    row.dataset.parentId = instance.parent_instance_id || '';

    const isSatellite = level > 0;

    if (isSatellite) {
        row.classList.add('satellite-instance');
    }

    const currentPublicPort = instance.persistent_mode ? instance.persistent_port : instance.port;

    // Initial datasets (source of truth for changes)
    // USE NORMALIZATION HERE TO PREVENT IMMEDIATE DIRTY STATE
    row.dataset.originalName = instance.name || '';
    row.dataset.originalBlueprint = instance.base_blueprint || '';
    row.dataset.originalGpuIds = normalizeGpuIds(instance.gpu_ids);
    row.dataset.originalAutostart = String(instance.autostart);
    row.dataset.originalPersistentMode = String(instance.persistent_mode);
    row.dataset.originalHostname = normalizeStr(instance.hostname);
    row.dataset.originalUseCustomHostname = String(instance.use_custom_hostname);
    row.dataset.originalOutputPath = normalizeStr(instance.output_path);
    row.dataset.originalPort = normalizeStr(currentPublicPort);
    
    // --- NEW: Original Env Values ---
    row.dataset.originalPythonVersion = normalizeStr(instance.python_version);
    row.dataset.originalCudaVersion = normalizeStr(instance.cuda_version);
    row.dataset.originalTorchVersion = normalizeStr(instance.torch_version);

    // Current data helpers for UI logic
    row.dataset.status = instance.status;
    row.dataset.name = instance.name || '';
    row.dataset.port = instance.port || '';
    row.dataset.persistentPort = instance.persistent_port || '';
    row.dataset.persistentMode = String(instance.persistent_mode);
    row.dataset.hostname = instance.hostname || '';
    row.dataset.useCustomHostname = String(instance.use_custom_hostname);

    const handleCell = row.insertCell();
    if (!isNew && !isSatellite) {
        handleCell.classList.add('drag-handle');
        handleCell.innerHTML = HolafIcons.render('layout', { size: 16 });
    } else {
        handleCell.style.textAlign = 'center';
        handleCell.innerHTML = '';
    }

    // Name Cell with Tree Visuals
    const nameCell = row.insertCell();
    const nameWrapper = document.createElement('div');
    nameWrapper.className = 'name-cell-wrapper';
    
    // Indentation + Connector
    nameWrapper.style.paddingLeft = `${level * 25}px`;
    if (level > 0) {
        const connector = document.createElement('span');
        connector.className = 'tree-connector';
        nameWrapper.appendChild(connector);
    }

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.value = instance.name || '';
    nameInput.dataset.field = 'name';
    nameInput.required = true;
    nameWrapper.appendChild(nameInput);
    nameCell.appendChild(nameWrapper);

    const blueprintSelect = createBlueprintSelect(instance.base_blueprint);
    if (isSatellite) {
        blueprintSelect.disabled = true;
        blueprintSelect.title = "Inherited from Parent Instance";
    }
    row.insertCell().appendChild(blueprintSelect);
    
    // --- NEW: Environment Cell (Python, CUDA, Torch) ---
    const envCell = row.insertCell();
    const envWrapper = document.createElement('div');
    envWrapper.className = 'env-cell-wrapper';
    
    const createEnvSelect = (field, options, currentValue, placeholder) => {
        const sel = document.createElement('select');
        sel.dataset.field = field;
        sel.title = placeholder;
        sel.className = 'compact-env-select';
        
        const defOpt = document.createElement('option');
        defOpt.value = '';
        defOpt.textContent = placeholder;
        sel.appendChild(defOpt);
        
        // Normalize options: each option can be a string or an object {cu, version}
        // Strings are used as-is; objects are converted to {value, label} pairs.
        const normalized = options.map(opt => {
            if (typeof opt === 'object' && opt !== null) {
                // CUDA versions: {cu: "cu130", version: "13.0"}
                return { value: opt.version, label: `CUDA ${opt.version}`, cu: opt.cu };
            }
            return { value: opt, label: String(opt) };
        });
        
        normalized.forEach(opt => {
            const o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            if (opt.cu) o.dataset.cu = opt.cu; // store cu-string for torch lookup
            sel.appendChild(o);
        });
        
        // FIX: If currentValue is set but not in the options list, add it as a custom option
        // This prevents false dirty state when the DB value doesn't match any populated option
        const allValues = normalized.map(opt => opt.value);
        if (currentValue && !allValues.includes(currentValue)) {
            const customOpt = document.createElement('option');
            customOpt.value = currentValue;
            customOpt.textContent = currentValue;
            sel.appendChild(customOpt);
        }
        
        if (currentValue) sel.value = currentValue;
        if (isSatellite) sel.disabled = true;
        return sel;
    };

    const pySelect = createEnvSelect('python_version', state.versions.python, instance.python_version, 'Py Auto');
    const cudaSelect = createEnvSelect('cuda_version', state.versions.cuda, instance.cuda_version, 'CUDA Auto');
    const torchSelect = createEnvSelect('torch_version', [], instance.torch_version, 'Torch Auto');

    // Logic to dynamically populate Torch options based on selected CUDA
    const updateTorchOptions = async (cudaVal, initialTorchVal) => {
        // Keep only the placeholder
        while (torchSelect.options.length > 1) torchSelect.remove(1);
        
        // Always try to fetch something, default to 12.8 if auto
        const fetchCudaVal = cudaVal || '12.8'; 
        
        torchSelect.options[0].textContent = "Loading...";
        
        let versions = state.versions.torchCache[fetchCudaVal];
        if (!versions) {
            versions = await fetchTorchVersions(fetchCudaVal);
            state.versions.torchCache[fetchCudaVal] = versions;
        }
        
        versions.forEach(opt => {
            const o = document.createElement('option');
            o.value = opt;
            o.textContent = opt;
            torchSelect.appendChild(o);
        });
        
        if (initialTorchVal && versions.includes(initialTorchVal)) {
            torchSelect.value = initialTorchVal;
        } else if (initialTorchVal) {
            // Pre-existing or custom version not in the default scraped list
            const o = document.createElement('option');
            o.value = initialTorchVal;
            o.textContent = initialTorchVal;
            torchSelect.appendChild(o);
            torchSelect.value = initialTorchVal;
        }
        torchSelect.options[0].textContent = 'Torch Auto';

        // FIX: Re-check for changes after async torch load completes.
        // Without this, the row stays falsely dirty because checkRowForChanges
        // ran before the torch options were populated.
        if (!isNew) {
            checkRowForChanges(row);
        }
    };

    cudaSelect.addEventListener('change', () => {
        const selectedOption = cudaSelect.options[cudaSelect.selectedIndex];
        const cuVal = selectedOption?.dataset?.cu || cudaSelect.value;
        updateTorchOptions(cuVal, null);
    });

    // --- FIX: Always initialize the torch options, even if cuda_version is empty ---
    // Use the cu-string from dataset if available, falling back to the version string
    const initialCu = cudaSelect.options[cudaSelect.selectedIndex]?.dataset?.cu || instance.cuda_version;
    updateTorchOptions(initialCu || '12.8', instance.torch_version);

    envWrapper.appendChild(pySelect);
    envWrapper.appendChild(cudaSelect);
    envWrapper.appendChild(torchSelect);
    envCell.appendChild(envWrapper);
    // ---------------------------------------------------

    const outputPathInput = document.createElement('input');
    outputPathInput.type = 'text';
    outputPathInput.value = instance.output_path || '';
    outputPathInput.dataset.field = 'output_path';
    outputPathInput.placeholder = 'Optional';
    if (isSatellite) {
        outputPathInput.disabled = true;
        outputPathInput.title = "Inherited from Parent Instance";
    }
    row.insertCell().appendChild(outputPathInput);

    // GPU Cell
    const gpuCell = row.insertCell();
    const gpuContainer = document.createElement('div');
    gpuContainer.className = 'gpu-checkbox-container';
    const assignedGpus = normalizeGpuIds(instance.gpu_ids).split(',').filter(id => id);
    // The GPU list may not be loaded yet during the progressive boot (the table
    // renders before /api/system/info answers). Always account for the GPUs the
    // instance is already assigned to so the field is never silently wiped empty.
    const gpuListCount = getGpuCount();
    const minCount = assignedGpus.reduce((m, id) => Math.max(m, parseInt(id, 10) + 1), 0);
    const gpuCount = Math.max(gpuListCount, minCount);

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

    // Autostart
    const autostartCheckbox = document.createElement('input');
    autostartCheckbox.type = 'checkbox';
    autostartCheckbox.checked = instance.autostart;
    autostartCheckbox.dataset.field = 'autostart';
    row.insertCell().appendChild(autostartCheckbox);

    // Persistent Mode
    const persistentModeCheckbox = document.createElement('input');
    persistentModeCheckbox.type = 'checkbox';
    persistentModeCheckbox.checked = instance.persistent_mode;
    persistentModeCheckbox.dataset.field = 'persistent_mode';
    row.insertCell().appendChild(persistentModeCheckbox);

    const statusCell = row.insertCell();
    const statusSpan = document.createElement('span');
    statusSpan.className = `status status-${instance.status.toLowerCase()}`;
    statusSpan.textContent = instance.status;
    statusCell.appendChild(statusSpan);

    // Hostname
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

    // Port
    const portCell = row.insertCell();
    const portSelect = document.createElement('select');
    portSelect.dataset.field = 'port';
    // Always add an "Auto" option so that instances with no explicit port match correctly
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
    // Set selected value
    if (currentPublicPort) {
        let optionFound = false;
        for (let i = 0; i < portSelect.options.length; i++) {
            if (portSelect.options[i].value == currentPublicPort) {
                portSelect.options[i].selected = true;
                optionFound = true;
                break;
            }
        }
        if (!optionFound) {
            const option = document.createElement('option');
            option.value = currentPublicPort;
            option.textContent = currentPublicPort;
            option.selected = true;
            portSelect.insertBefore(option, portSelect.firstChild);
        }
    } else {
        autoOption.selected = true;
    }
    portCell.appendChild(portSelect);

    // Actions
    const actionsCell = row.insertCell();
    actionsCell.classList.add('actions-column');
    if (isNew) {
        actionsCell.innerHTML = `
            <button class="action-btn" data-action="save" data-id="new" disabled>${HolafIcons.render('check', { size: 14 })} Create</button>
            <button class="action-btn" data-action="cancel_new">${HolafIcons.render('x', { size: 14 })} Cancel</button>
            <span class="action-btn-placeholder"></span>`;
    } else {
        const openHref = buildInstanceUrl(row, false);
        const isStarted = instance.status === 'started';
        const isStopped = instance.status === 'stopped';
        
        actionsCell.innerHTML = `
            <button class="action-btn" data-action="start" data-id="${instance.id}" ${!isStopped ? 'disabled' : ''}>${HolafIcons.render('play', {size: 14})} Start</button>
            <button class="action-btn" data-action="stop" data-id="${instance.id}" ${isStopped ? 'disabled' : ''}>${HolafIcons.render('stop', {size: 14})} Stop</button>
            <button class="action-btn" data-action="logs" data-id="${instance.id}">${HolafIcons.render('terminal', {size: 14})} Logs</button>
            <button class="action-btn" data-action="tools_menu" data-id="${instance.id}">${HolafIcons.render('gear', {size: 14})} Tools</button>
            <button class="action-btn" data-action="delete" data-id="${instance.id}" ${!isStopped ? 'disabled' : ''}>${HolafIcons.render('trash', {size: 14})} Delete</button>
            <button class="action-btn" data-action="view" data-id="${instance.id}" ${!isStarted ? 'disabled' : ''}>${HolafIcons.render('eye', {size: 14})} View</button>
            <a href="${openHref}" class="action-btn ${openHref === '#' ? 'disabled' : ''}" data-action="open" data-id="${instance.id}" target="_blank">${HolafIcons.render('external-link', { size: 14 })} Open</a>`;
    }

    const allFields = row.querySelectorAll('input, select, .blueprint-select');
    if (isNew) {
        const saveButton = row.querySelector('button[data-action="save"]');
        allFields.forEach(field => field.addEventListener('input', () => {
            const name = row.querySelector('input[data-field="name"]').value;
            const bp = row.querySelector('[data-field="base_blueprint"]').value;
            saveButton.disabled = !name || !bp;
        }));
        let isOutputPathDirty = false;
        outputPathInput.addEventListener('input', () => { isOutputPathDirty = true; });
        nameInput.addEventListener('input', () => { if (!isOutputPathDirty) { outputPathInput.value = nameInput.value; } });
    } else {
        allFields.forEach(field => {
            field.addEventListener('input', () => checkRowForChanges(row));
            field.addEventListener('change', () => checkRowForChanges(row));
        });

        // --- ADDED: Specific logic for Blueprint Changes ---
        const bpSelect = row.querySelector('[data-field="base_blueprint"]');
        if (bpSelect && !bpSelect.disabled) {
            // Track previous value on focus
            bpSelect.addEventListener('focus', function() {
                this.dataset.previousValue = this.value;
            });

            // Intercept change event
            bpSelect.addEventListener('change', function() {
                const confirmed = confirm(
                    "Warning: The startup script will be updated to match the selected blueprint.\n\n" +
                    "Click OK to include this update in the next Save.\n" +
                    "Click Cancel to revert to the previous blueprint."
                );

                if (!confirmed) {
                    // Revert to value before this change
                    this.value = this.dataset.previousValue || row.dataset.originalBlueprint;
                    checkRowForChanges(row);
                } else {
                    // Update tracked value and allow dirty state (handled by generic listener)
                    this.dataset.previousValue = this.value;
                    checkRowForChanges(row);
                }
            });
        }
        // ---------------------------------------------------

        updateInstanceRow(row, instance);
    }
    return row;
}

function formatBytes(bytes, decimals = 2) {
    const value = asNumber(bytes);
    if (value === null) return '—';
    if (value === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(value) / Math.log(k));
    return parseFloat((value / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// ═══════════════════════════════════════════════════════════════════════════
// System Monitoring panel — two display modes (normal | compact)
// ─────────────────────────────────────────────────────────────────────────────
// The panel is rebuilt ONLY when the mode or the device list changes; every
// 2 s tick updates the existing nodes in place (textContent / width / points)
// so the polling never flashes or discards the current DOM. Metrics that are
// null/absent (fan_percent on A100/H100, cpu_temp without hwmon driver, ...)
// hide their cell — no "null", "NaN" or fake 0 is ever rendered.
// ═══════════════════════════════════════════════════════════════════════════

const MONITOR_HISTORY_LEN = 30; // ~1 minute at the 2 s poll rate (normal mode)
// NVML does not expose per-device high/critical thresholds the way hwmon does:
// fall back to documented amber/red defaults for GPU readings (and for CPU
// sensors that report no thresholds, e.g. ACPI zones).
const GPU_TEMP_WARN_DEFAULT = 80;
const GPU_TEMP_DANGER_DEFAULT = 90;

const SVG_NS = 'http://www.w3.org/2000/svg';
// Airflow glyph for the fan chip (drawn here: HolafIcons has no fan icon).
const FAN_ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h9.5a2.5 2.5 0 1 0-2.5-2.5"></path><path d="M3 12h13a2.5 2.5 0 1 1-2.5 2.5"></path><path d="M3 16h7"></path></svg>';

// Filled on the last layout build; null forces a rebuild on the next render.
let monitorView = null;

/** Finite number or null — the backend sends null for unavailable metrics. */
function asNumber(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function createEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

/** Severity of a temperature reading: sensor thresholds, else GPU defaults. */
function tempSeverity(temp, high, critical) {
    const warn = asNumber(high) ?? GPU_TEMP_WARN_DEFAULT;
    const danger = asNumber(critical) ?? GPU_TEMP_DANGER_DEFAULT;
    if (temp >= danger) return 'danger';
    if (temp >= warn) return 'warn';
    return 'ok';
}

/**
 * Apply a temperature reading to a .ak-temp element (hides it when null).
 * Colors come from --ak-temp-ok/--ak-temp-warn/--ak-temp-danger (theme.css).
 */
function applyTemp(node, temp, high, critical) {
    if (!node) return;
    const value = asNumber(temp);
    node.hidden = value === null;
    if (value === null) return;
    node.textContent = `${Math.round(value)}°C`;
    const severity = tempSeverity(value, high, critical);
    node.classList.toggle('ak-temp--warn', severity === 'warn');
    node.classList.toggle('ak-temp--danger', severity === 'danger');
}

function formatFrequency(mhz) {
    return mhz >= 1000 ? `${(mhz / 1000).toFixed(2)} GHz` : `${Math.round(mhz)} MHz`;
}

function formatPower(power, limit, separator = ' / ') {
    if (power !== null && limit !== null) return `${power.toFixed(1)}${separator}${Math.round(limit)} W`;
    if (power !== null) return `${power.toFixed(1)} W`;
    if (limit !== null) return `≤ ${Math.round(limit)} W`;
    return null;
}

/** Meter row (label + track/fill + value); updated in place by applyMeter. */
function buildMeter(label, fillModifier = '') {
    const row = createEl('div', 'ak-meter-row');
    const labelEl = createEl('span', 'ak-meter-label', label);
    const track = createEl('div', 'ak-meter');
    const fill = createEl('div', `ak-meter-fill${fillModifier ? ' ' + fillModifier : ''}`);
    track.appendChild(fill);
    const value = createEl('span', 'ak-meter-value');
    row.append(labelEl, track, value);
    return { row, fill, value };
}

/** Apply a 0..100 percentage + text; the whole row hides when percent is null. */
function applyMeter(meter, percent, text) {
    const value = asNumber(percent);
    meter.row.hidden = value === null;
    if (value === null) return;
    meter.fill.style.width = `${Math.min(100, Math.max(0, value))}%`;
    meter.value.textContent = text;
}

/** Plain chip (value only) — used for charge/frequency in normal mode. */
function buildChip(iconSvg = null) {
    const chip = createEl('span', 'ak-chip');
    if (iconSvg) chip.insertAdjacentHTML('afterbegin', iconSvg);
    const value = createEl('span', 'ak-chip-value');
    chip.appendChild(value);
    return { chip, value };
}

/** Power chip: value (W) + muted limit (W). */
function buildPowerChip() {
    const chip = createEl('span', 'ak-chip');
    chip.insertAdjacentHTML('afterbegin', HolafIcons.render('power', { size: 11 }));
    const value = createEl('span', 'ak-chip-value');
    const limit = createEl('span', 'ak-chip-limit');
    chip.append(value, limit);
    return { chip, value, limit };
}

function buildSparkline() {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'ak-sparkline');
    svg.setAttribute('viewBox', '0 0 100 28');
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('aria-hidden', 'true');
    const line = document.createElementNS(SVG_NS, 'polyline');
    line.setAttribute('class', 'ak-sparkline-line');
    svg.append(line);
    return { svg, line };
}

/**
 * Rolling GPU utilization history (bounded): one point per stats tick.
 * Null readings are skipped instead of recorded as 0 (a fake dip would lie).
 */
function recordGpuHistory(gpuId, utilization) {
    const series = state.monitorHistory.gpus[String(gpuId)] ||
        (state.monitorHistory.gpus[String(gpuId)] = []);
    series.push(Math.min(100, Math.max(0, utilization)));
    if (series.length > MONITOR_HISTORY_LEN) {
        series.splice(0, series.length - MONITOR_HISTORY_LEN);
    }
    return series;
}

function applySparkline(refs, series) {
    const hasData = series.length >= 2;
    refs.svg.hidden = !hasData;
    if (!hasData) return;
    const n = series.length;
    const stepX = 100 / (n - 1);
    const points = series.map((value, i) => {
        const x = (i * stepX).toFixed(2);
        const y = (27 - value * 0.26).toFixed(2); // viewBox height 28, 1 px padding
        return `${x},${y}`;
    });
    refs.line.setAttribute('points', points.join(' '));
}

// --- Normal mode builders ----------------------------------------------------

function buildNormalCpuCard() {
    const card = createEl('div', 'ak-monitor-card');
    card.dataset.monitorDevice = 'cpu';

    const head = createEl('div', 'ak-monitor-head');
    const device = createEl('div', 'ak-monitor-device');
    device.append(
        createEl('span', 'ak-monitor-name', 'CPU'),
        createEl('span', 'ak-monitor-sub', 'Processor'),
    );
    const temp = createEl('span', 'ak-temp');
    head.append(device, temp);

    const chips = createEl('div', 'ak-monitor-chips');
    const chargeChip = buildChip();
    const freqChip = buildChip();
    chips.append(chargeChip.chip, freqChip.chip);

    const meters = createEl('div', 'ak-monitor-meters');
    const ramMeter = buildMeter('RAM', 'ak-meter-fill--info');
    meters.appendChild(ramMeter.row);

    card.append(head, chips, meters);
    return { card, temp, chargeChip, freqChip, ramMeter };
}

function buildNormalGpuCard(gpuId) {
    const card = createEl('div', 'ak-monitor-card');
    card.dataset.monitorDevice = `gpu-${gpuId}`;

    const head = createEl('div', 'ak-monitor-head');
    const device = createEl('div', 'ak-monitor-device');
    const name = createEl('span', 'ak-monitor-name');
    const sub = createEl('span', 'ak-monitor-sub');
    device.append(name, sub);
    const temp = createEl('span', 'ak-temp');
    head.append(device, temp);

    const chips = createEl('div', 'ak-monitor-chips');
    const fanChip = buildChip(FAN_ICON_SVG);
    const powerChip = buildPowerChip();
    chips.append(fanChip.chip, powerChip.chip);

    const meters = createEl('div', 'ak-monitor-meters');
    const vramMeter = buildMeter('VRAM', 'ak-meter-fill--info');
    const chargeMeter = buildMeter('Charge');
    meters.append(vramMeter.row, chargeMeter.row);

    const spark = buildSparkline();

    card.append(head, chips, meters, spark.svg);
    return { card, name, sub, temp, fanChip, powerChip, vramMeter, chargeMeter, spark };
}

// --- Compact mode builders ---------------------------------------------------

function buildCompactRow(deviceKey, label1, label2) {
    const row = createEl('div', 'ak-monitor-row');
    row.dataset.monitorDevice = deviceKey;

    const head = createEl('div', 'ak-monitor-row-head');
    const name = createEl('span', 'ak-monitor-row-name');
    const values = createEl('span', 'ak-compact-values');
    const temp = createEl('span', 'ak-temp ak-temp--compact');
    const sep1 = createEl('span', 'ak-compact-sep', '·');
    const second = createEl('span', 'ak-compact-value');
    const sep2 = createEl('span', 'ak-compact-sep', '·');
    const third = createEl('span', 'ak-compact-value');
    values.append(temp, sep1, second, sep2, third);
    head.append(name, values);

    const meters = createEl('div', 'ak-monitor-meters');
    const meter1 = buildMeter(label1, 'ak-meter-fill--info');
    const meter2 = buildMeter(label2);
    meters.append(meter1.row, meter2.row);

    row.append(head, meters);
    return { row, name, temp, second, third, sep1, sep2, meter1, meter2 };
}

/**
 * Compact line values: [temp, second, third]. `temp` is handled by applyTemp,
 * the two others get their text here; separators only appear between visible
 * items so a missing metric leaves no dangling "·".
 */
function applyCompactValues(refs, secondText, thirdText) {
    const nodes = [refs.second, refs.third];
    const texts = [secondText, thirdText];
    nodes.forEach((node, i) => {
        node.hidden = !texts[i];
        if (texts[i]) node.textContent = texts[i];
    });
    const visible = [];
    if (!refs.temp.hidden) visible.push(0);
    nodes.forEach((node, i) => { if (!node.hidden) visible.push(i + 1); });
    [refs.sep1, refs.sep2].forEach((sep, i) => {
        const anyBefore = visible.some(index => index <= i);
        sep.hidden = !(anyBefore && visible.includes(i + 1));
    });
}

// --- Layout assembly & per-tick updates --------------------------------------

function buildMonitorLayout(stats) {
    const container = DOM.systemStatsContainer;
    if (!container) return null;
    const gpus = Array.isArray(stats.gpus) ? stats.gpus.filter(Boolean) : [];
    const mode = state.monitorMode === 'compact' ? 'compact' : 'normal';
    const key = `${mode}|${gpus.map(gpu => gpu.id).join(',')}`;
    if (monitorView && monitorView.key === key) return monitorView;

    container.innerHTML = '';
    container.dataset.monitorMode = mode;
    const view = { key, mode, cpu: null, gpus: [] };

    if (mode === 'compact') {
        view.cpu = buildCompactRow('cpu', 'RAM', 'Charge');
        container.appendChild(view.cpu.row);
        gpus.forEach(gpu => {
            const refs = buildCompactRow(`gpu-${gpu.id}`, 'VRAM', 'Charge');
            refs.id = gpu.id;
            view.gpus.push(refs);
            container.appendChild(refs.row);
        });
    } else {
        view.cpu = buildNormalCpuCard();
        container.appendChild(view.cpu.card);
        gpus.forEach(gpu => {
            const refs = buildNormalGpuCard(gpu.id);
            refs.id = gpu.id;
            view.gpus.push(refs);
            container.appendChild(refs.card);
        });
    }

    if (gpus.length === 0) {
        container.appendChild(createEl('p', 'ak-monitor-empty', 'No NVIDIA GPUs detected.'));
    }

    monitorView = view;
    return view;
}

function applyNormalCpu(refs, stats) {
    const cpuTemp = stats.cpu_temp || null;
    const cpuPercent = asNumber(stats.cpu_percent);
    const freqMhz = asNumber(stats.cpu_freq_mhz);
    const ram = stats.ram || {};

    applyTemp(refs.temp, cpuTemp && cpuTemp.current, cpuTemp && cpuTemp.high, cpuTemp && cpuTemp.critical);

    refs.chargeChip.chip.hidden = cpuPercent === null;
    if (cpuPercent !== null) refs.chargeChip.value.textContent = `${cpuPercent.toFixed(1)}%`;

    refs.freqChip.chip.hidden = freqMhz === null;
    if (freqMhz !== null) refs.freqChip.value.textContent = formatFrequency(freqMhz);

    const ramUsed = asNumber(ram.used);
    const ramTotal = asNumber(ram.total);
    const ramText = (ramUsed !== null && ramTotal !== null)
        ? `${formatBytes(ramUsed, 1)} / ${formatBytes(ramTotal, 1)}` : '';
    applyMeter(refs.ramMeter, ram.percent, ramText);
}

function applyNormalGpu(refs, gpu) {
    refs.name.textContent = gpu.name || `GPU ${gpu.id}`;
    const vram = gpu.vram || null;
    const vramTotal = vram ? asNumber(vram.total) : null;
    refs.sub.textContent = (vramTotal !== null && vramTotal > 0)
        ? `GPU ${gpu.id} · ${formatBytes(vramTotal, 0)} VRAM`
        : `GPU ${gpu.id}`;

    applyTemp(refs.temp, gpu.temperature_c, null, null);

    const fan = asNumber(gpu.fan_percent);
    refs.fanChip.chip.hidden = fan === null;
    if (fan !== null) refs.fanChip.value.textContent = `${Math.round(fan)}%`;

    const power = asNumber(gpu.power_w);
    const limit = asNumber(gpu.power_limit_w);
    refs.powerChip.chip.hidden = power === null && limit === null;
    if (!refs.powerChip.chip.hidden) {
        refs.powerChip.value.textContent = power !== null ? `${power.toFixed(1)} W` : '';
        refs.powerChip.limit.textContent = limit !== null ? `/ ${Math.round(limit)} W` : '';
    }

    const vramUsed = vram ? asNumber(vram.used) : null;
    const vramText = (vramUsed !== null && vramTotal !== null && vramTotal > 0)
        ? `${formatBytes(vramUsed, 1)} / ${formatBytes(vramTotal, 1)}` : '';
    applyMeter(refs.vramMeter, vram && vram.percent, vramText);

    const utilization = asNumber(gpu.utilization_percent);
    applyMeter(refs.chargeMeter, utilization, utilization !== null ? `${utilization}%` : '');
    applySparkline(refs.spark, utilization !== null
        ? recordGpuHistory(gpu.id, utilization)
        : (state.monitorHistory.gpus[String(gpu.id)] || []));
}

function applyCompactCpu(refs, stats) {
    const cpuTemp = stats.cpu_temp || null;
    const cpuPercent = asNumber(stats.cpu_percent);
    const freqMhz = asNumber(stats.cpu_freq_mhz);
    const ram = stats.ram || {};

    applyTemp(refs.temp, cpuTemp && cpuTemp.current, cpuTemp && cpuTemp.high, cpuTemp && cpuTemp.critical);
    applyCompactValues(refs,
        cpuPercent !== null ? `${cpuPercent.toFixed(1)}%` : null,
        freqMhz !== null ? formatFrequency(freqMhz) : null);

    const ramUsed = asNumber(ram.used);
    const ramTotal = asNumber(ram.total);
    const ramText = (ramUsed !== null && ramTotal !== null)
        ? `${formatBytes(ramUsed, 0)}/${formatBytes(ramTotal, 0)}` : '';
    applyMeter(refs.meter1, ram.percent, ramText);
    applyMeter(refs.meter2, cpuPercent, cpuPercent !== null ? `${cpuPercent.toFixed(0)}%` : '');
}

function applyCompactGpu(refs, gpu) {
    refs.name.textContent = gpu.name || `GPU ${gpu.id}`;
    const fan = asNumber(gpu.fan_percent);
    const power = asNumber(gpu.power_w);
    const limit = asNumber(gpu.power_limit_w);

    applyTemp(refs.temp, gpu.temperature_c, null, null);
    applyCompactValues(refs,
        fan !== null ? `${Math.round(fan)}%` : null,
        formatPower(power, limit, '/'));

    const vram = gpu.vram || null;
    const vramUsed = vram ? asNumber(vram.used) : null;
    const vramTotal = vram ? asNumber(vram.total) : null;
    const vramText = (vramUsed !== null && vramTotal !== null && vramTotal > 0)
        ? `${formatBytes(vramUsed, 0)}/${formatBytes(vramTotal, 0)}` : '';
    applyMeter(refs.meter1, vram && vram.percent, vramText);

    const utilization = asNumber(gpu.utilization_percent);
    applyMeter(refs.meter2, utilization, utilization !== null ? `${utilization}%` : '');
}

/**
 * Apply the latest stats payload to the current layout (in place). The layout
 * itself is (re)built only when the mode or the GPU list changes.
 */
function renderSystemStats(stats) {
    const view = buildMonitorLayout(stats);
    if (!view) return;
    const gpus = Array.isArray(stats.gpus) ? stats.gpus.filter(Boolean) : [];

    if (view.mode === 'compact') applyCompactCpu(view.cpu, stats);
    else applyNormalCpu(view.cpu, stats);

    // Drop history of GPUs that disappeared (bounded memory in all cases).
    const present = new Set(gpus.map(gpu => String(gpu.id)));
    Object.keys(state.monitorHistory.gpus).forEach(id => {
        if (!present.has(id)) delete state.monitorHistory.gpus[id];
    });

    gpus.forEach((gpu, index) => {
        const refs = view.gpus[index];
        if (!refs) return;
        if (view.mode === 'compact') applyCompactGpu(refs, gpu);
        else applyNormalGpu(refs, gpu);
    });
}

/** Switch the monitoring layout ('normal' | 'compact') and re-render at once. */
export function setMonitorMode(mode) {
    const next = mode === 'compact' ? 'compact' : 'normal';
    if (state.monitorMode !== next) {
        state.monitorMode = next;
        monitorView = null; // force a rebuild with the other structure
    }
    if (DOM.systemStatsContainer) DOM.systemStatsContainer.dataset.monitorMode = next;
    if (state.systemStats) renderSystemStats(state.systemStats);
}

export async function updateSystemStats(stats) {
    if (!stats) return;
    state.systemStats = stats;
    // GPU cells degrade to /api/system/stats when /api/system/info is slow.
    // No-op once the cells are already populated (cheap guard in the function).
    refreshAllGpuCells();
    renderSystemStats(stats);
}