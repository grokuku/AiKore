/* ═══════════════════════════════════════════════════════════════════════════
 * AiKore — themeSelector.js : sélecteur de thème (lot S).
 * ─────────────────────────────────────────────────────────────────────────────
 * Contrôle du .pane-header-controls (panneau Instances) :
 *   • bouton déclencheur : icône du mode courant (sun/moon) + libellé du thème ;
 *   • menu déroulant listant les 12 thèmes (listThemes) en deux sections
 *     « Dark » / « Light », thème actif marqué (check), fermeture au clic
 *     extérieur et à Échap.
 *
 * POURQUOI CE MOTIF (vs createBlueprintSelect de ui.js)
 *   Le dropdown blueprint vit dans des lignes de tableau re-rendues : il est
 *   déplacé dans <body> à chaque ouverture et utilise un backdrop plein écran
 *   pour le clic extérieur. Le déclencheur de thème est, lui, un contrôle
 *   STATIQUE du header : le menu est donc créé une fois et reste dans <body>
 *   (position:fixed — .pane a overflow:hidden), et le clic extérieur est
 *   détecté par un écouteur pointerdown en phase de capture. C'est strictement
 *   plus simple et ça évite que le backdrop n'avale le clic de bascule du
 *   déclencheur.
 *
 * ÉTAT : la source de vérité reste themes.js (getCurrentTheme). L'événement
 * `aikore-theme-changed` (émis par applyTheme, y compris pour un changement
 * venu d'ailleurs) rafraîchit icône, libellé et marqueur de sélection.
 * ═════════════════════════════════════════════════════════════════════════ */

import { listThemes, applyTheme, getCurrentTheme } from './themes.js';
import { HolafIcons } from '../vendor/holaf-icons.js';

const THEME_EVENT = 'aikore-theme-changed';
const MODE_ICON = { dark: 'moon', light: 'sun' };
const MODE_LABEL = { dark: 'Dark', light: 'Light' };
const MODE_ORDER = ['dark', 'light'];

let trigger = null;
let labelEl = null;
let iconEl = null;
let arrowEl = null;
let menu = null;
let options = [];
let isOpen = false;

/** Thème courant (getCurrentTheme), avec repli sur data-theme/data-mode avant init. */
function resolveCurrentTheme() {
    const current = getCurrentTheme();
    if (current && current.name) return current;

    const root = document.documentElement;
    const name = root.getAttribute('data-theme') || 'aikore-dark';
    const mode = root.getAttribute('data-mode') === 'light' ? 'light' : 'dark';
    const known = listThemes().find((theme) => theme.name === name);
    return known || { name: name, label: name, mode: mode, family: '' };
}

/** Reflète le thème courant sur le déclencheur et les entrées du menu. */
function sync() {
    if (!trigger || !menu) return;
    const current = resolveCurrentTheme();

    iconEl.innerHTML = HolafIcons.render(MODE_ICON[current.mode], { size: 14 });
    labelEl.textContent = current.label;
    trigger.title = 'Theme: ' + current.label + ' (' + current.mode + ') — click to choose a theme';
    trigger.setAttribute('aria-label', 'Choose theme. Current: ' + current.label);

    options.forEach((option) => {
        option.setAttribute('aria-selected', option.dataset.theme === current.name ? 'true' : 'false');
    });
}

/** Construit le menu (une fois) : sections Dark/Light, 12 entrées. */
function buildMenu() {
    menu = document.createElement('div');
    menu.id = 'theme-select-menu';
    menu.className = 'theme-select-dropdown';
    menu.setAttribute('role', 'listbox');
    menu.setAttribute('aria-label', 'Theme');

    MODE_ORDER.forEach((mode) => {
        const themes = listThemes().filter((theme) => theme.mode === mode);
        if (themes.length === 0) return;

        const group = document.createElement('div');
        group.className = 'theme-select-group';
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', MODE_LABEL[mode]);

        const groupLabel = document.createElement('div');
        groupLabel.className = 'theme-select-group-label';
        groupLabel.textContent = MODE_LABEL[mode];
        group.appendChild(groupLabel);

        themes.forEach((theme) => {
            const option = document.createElement('button');
            option.type = 'button';
            option.className = 'theme-select-option';
            option.dataset.theme = theme.name;
            option.setAttribute('role', 'option');
            option.setAttribute('aria-selected', 'false');
            option.tabIndex = -1;

            const icon = document.createElement('span');
            icon.className = 'theme-select-option-icon';
            icon.setAttribute('aria-hidden', 'true');
            icon.innerHTML = HolafIcons.render(MODE_ICON[theme.mode], { size: 14 });
            option.appendChild(icon);

            const label = document.createElement('span');
            label.className = 'theme-select-option-label';
            label.textContent = theme.label;
            option.appendChild(label);

            const check = document.createElement('span');
            check.className = 'theme-select-option-check';
            check.setAttribute('aria-hidden', 'true');
            check.innerHTML = HolafIcons.render('check', { size: 14 });
            option.appendChild(check);

            option.addEventListener('click', () => selectTheme(theme.name));
            option.addEventListener('keydown', onOptionKeydown);
            group.appendChild(option);
        });

        menu.appendChild(group);
    });

    document.body.appendChild(menu);
    options = Array.from(menu.querySelectorAll('.theme-select-option'));
}

/** Positionne le menu sous (ou au-dessus) du déclencheur, aligné à droite. */
function positionMenu() {
    if (!isOpen || !trigger) return;
    const rect = trigger.getBoundingClientRect();
    const vh = window.innerHeight;
    const spaceBelow = vh - rect.bottom;
    const spaceAbove = rect.top;

    menu.style.maxHeight = Math.min(360, Math.max(160, Math.max(spaceBelow, spaceAbove) - 12)) + 'px';

    const menuWidth = menu.offsetWidth || 200;
    const left = Math.max(8, Math.min(rect.right - menuWidth, window.innerWidth - 8 - menuWidth));
    menu.style.left = left + 'px';

    if (spaceBelow >= 160 || spaceBelow >= spaceAbove) {
        menu.style.top = (rect.bottom + 4) + 'px';
        menu.style.bottom = 'auto';
    } else {
        menu.style.top = 'auto';
        menu.style.bottom = (vh - rect.top + 4) + 'px';
    }
}

/**
 * Ouvre le menu (sans voler le focus si focusIndex est absent — ouverture
 * souris ; les flèches passent focusIndex).
 */
function openMenu(focusIndex) {
    if (isOpen || !menu) return;
    isOpen = true;
    menu.classList.add('open');
    trigger.setAttribute('aria-expanded', 'true');
    positionMenu();

    if (typeof focusIndex === 'number' && options.length > 0) {
        const index = ((focusIndex % options.length) + options.length) % options.length;
        options[index].focus();
    }
}

/** Ferme le menu ; returnFocus ramène le focus sur le déclencheur (clavier). */
function closeMenu(returnFocus) {
    if (!isOpen) return;
    isOpen = false;
    menu.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
    if (returnFocus) trigger.focus();
}

/** Applique le thème puis ferme le menu (applyTheme persiste + émet l'événement). */
function selectTheme(name) {
    applyTheme(name);
    closeMenu(true);
}

/** Index de l'entrée actuellement marquée (aria-selected), ou -1. */
function selectedIndex() {
    return options.findIndex((option) => option.getAttribute('aria-selected') === 'true');
}

function onTriggerKeydown(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const selected = selectedIndex();
        const fallback = event.key === 'ArrowDown' ? 0 : options.length - 1;
        const target = selected >= 0 ? selected : fallback;
        if (isOpen) options[target].focus();
        else openMenu(target);
    } else if (event.key === 'Escape' && isOpen) {
        event.preventDefault();
        closeMenu(false);
    }
}

function onOptionKeydown(event) {
    const index = options.indexOf(event.currentTarget);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        options[(index + delta + options.length) % options.length].focus();
    } else if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        options[event.key === 'Home' ? 0 : options.length - 1].focus();
    } else if (event.key === 'Escape') {
        event.preventDefault();
        closeMenu(true);
    } else if (event.key === 'Tab') {
        closeMenu(false);
    }
    // Entrée/Espace : comportement natif du <button> → click → selectTheme().
}

/**
 * Initialise le sélecteur (idempotent). À appeler après initTheme() : le
 * premier sync() lit getCurrentTheme(), donc le libellé reflète le thème
 * restauré dès le boot.
 */
export function initThemeSelector() {
    if (trigger) return;

    trigger = document.getElementById('theme-select-trigger');
    labelEl = document.getElementById('theme-select-label');
    iconEl = document.getElementById('theme-select-icon');
    if (!trigger || !labelEl || !iconEl) {
        console.warn('[AiKore themes] squelette du sélecteur introuvable — sélecteur désactivé.');
        return;
    }
    arrowEl = trigger.querySelector('.theme-select-arrow');
    if (arrowEl) arrowEl.innerHTML = HolafIcons.render('chevron-down', { size: 12 });

    buildMenu();

    trigger.addEventListener('click', () => {
        if (isOpen) closeMenu(false);
        else openMenu();
    });
    trigger.addEventListener('keydown', onTriggerKeydown);

    // Clic extérieur : pointerdown en capture (couvre souris + tactile) ; les
    // clics dans le menu ou sur le déclencheur ne ferment pas ici.
    document.addEventListener('pointerdown', (event) => {
        if (!isOpen) return;
        if (trigger.contains(event.target) || menu.contains(event.target)) return;
        closeMenu(false);
    }, true);

    window.addEventListener('resize', () => {
        if (isOpen) positionMenu();
    });

    // Thème changé ailleurs (autre composant, console, futur menu) : refléter.
    document.addEventListener(THEME_EVENT, sync);

    sync();
}
