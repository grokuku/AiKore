/* ═══════════════════════════════════════════════════════════════════════════
 * AiKore — themes.js : socle du système de thèmes (lot T1+T2).
 * ─────────────────────────────────────────────────────────────────────────────
 * RESPONSABILITÉS
 *   1. Définir les packs hôte « aikore-dark » / « aikore-light » (famille
 *      « aikore » : palettes validées côté projet, conformément à la doctrine
 *      holaf-lib — les presets neutres vivent dans la lib, le projet fournit
 *      ses palettes).
 *   2. Les enregistrer dans les TROIS registres, car AUCUN miroir automatique
 *      n'existe : HolafTokens.registerPreset (tokens page --holaf-*),
 *      HolafModal.themes.register (--hm-*, 17 clés) et
 *      HolafToast.themes.register (--ht-*, 12 clés).
 *   3. Exposer une API stable au sélecteur et au boot : listThemes(),
 *      applyTheme(), getCurrentTheme(), initTheme().
 *
 * CHARGEMENT DES BRIQUES
 *   • holaf-tokens 0.3.0 est CLASSIC-ONLY (aucun export ESM) → l'instantané
 *     global window.HolafTokens est fourni par la balise <script defer> de
 *     index.html (vendor/holaf-tokens.js), exécutée avant ce module.
 *   • holaf-modal / holaf-toast sont DUAL avec export ESM → imports explicites.
 *
 * PERSISTANCE : localStorage['aikoreTheme'] (clé dédiée aux thèmes, distincte
 * de aikoreInstanceOrder / aikoreSplitSizes / aikoreZoomLevels).
 * ÉVÉNEMENT : « aikore-theme-changed » (detail { theme, mode }) sur document,
 * pour les composants annexes (futur sélecteur, xterm/CodeMirror…).
 * ═════════════════════════════════════════════════════════════════════════ */

import { HolafModal } from '../vendor/holaf-modal.js';
import { HolafToast } from '../vendor/holaf-toast.js';

const STORAGE_KEY = 'aikoreTheme';
const DEFAULT_THEME = 'aikore-dark';
const THEME_EVENT = 'aikore-theme-changed';

/* ─── Packs hôte aikore (valeurs validées — NE PAS ajuster sans validation) ─
 * tokens : clés NON préfixées attendues par HolafTokens.registerPreset.
 *          ok / warn / text-faint sont explicites ; les dérivées (ok-text,
 *          accent-soft, surface-hover…) sont calculées par la brique.
 * modal / toast : clés préfixées attendues par les registres des briques.   */
const AIKORE_THEMES = {
    'aikore-dark': {
        label: 'AiKore Dark',
        mode: 'dark',
        tokens: {
            surface: '#1A1A2E',
            'surface-elev': '#2A2A4A',
            'surface-raised': '#2C2C54',
            border: '#3B3B6B',
            text: '#E0E0E0',
            'text-muted': '#B8B8CC',
            'text-faint': '#9696AE',
            accent: '#4DA6FF',
            'accent-hover': '#6DB6FF',
            'accent-text': '#0D1B2A',
            danger: '#DC3545',
            'danger-hover': '#C82333',
            'danger-text': '#FFFFFF',
            ok: '#28A745',
            warn: '#FFC107',
            radius: '8px',
            shadow: '0 5px 15px rgba(0,0,0,0.4)',
            'font-size': '14px',
        },
        modal: {
            '--hm-bg': '#1A1A2E',
            '--hm-bg-secondary': '#2A2A4A',
            '--hm-bg-input': '#2C2C54',
            '--hm-text': '#E0E0E0',
            '--hm-text-secondary': '#B8B8CC',
            '--hm-border': '#3B3B6B',
            '--hm-accent': '#4DA6FF',
            '--hm-accent-hover': '#6DB6FF',
            '--hm-accent-text': '#0D1B2A',
            '--hm-danger': '#DC3545',
            '--hm-danger-hover': '#C82333',
            '--hm-danger-text': '#FFFFFF',
            '--hm-radius': '12px',
            '--hm-overlay-bg': 'rgba(6,6,16,0.62)',
            '--hm-font-size': '14px',
            '--hm-shadow': '0 18px 50px rgba(0,0,0,0.55)',
            '--hm-busy-bg': 'rgba(26,26,46,0.85)',
        },
        toast: {
            '--ht-bg': '#1A1A2E',
            '--ht-bg-success': '#1C2F31',
            '--ht-bg-warning': '#3C3328',
            '--ht-bg-error': '#371E31',
            '--ht-fg': '#E0E0E0',
            '--ht-border': '#3B3B6B',
            '--ht-accent-info': '#4DA6FF',
            '--ht-accent-success': '#28A745',
            '--ht-accent-warning': '#FFC107',
            '--ht-accent-error': '#FF6B6B',
            '--ht-shadow': '0 6px 24px rgba(0,0,0,0.45)',
            '--ht-radius': '10px',
        },
    },
    'aikore-light': {
        label: 'AiKore Light',
        mode: 'light',
        tokens: {
            surface: '#F2F3FA',
            'surface-elev': '#FFFFFF',
            'surface-raised': '#F8F9FD',
            border: '#C9CDE2',
            text: '#1A1A2E',
            'text-muted': '#5A5A74',
            'text-faint': '#6A6A82',
            accent: '#0066D6',
            'accent-hover': '#0057B8',
            'accent-text': '#FFFFFF',
            danger: '#C82333',
            'danger-hover': '#B21F2D',
            'danger-text': '#FFFFFF',
            ok: '#1E7E34',
            warn: '#B45309',
            radius: '8px',
            shadow: '0 5px 15px rgba(26,26,46,0.12)',
            'font-size': '14px',
        },
        modal: {
            '--hm-bg': '#F2F3FA',
            '--hm-bg-secondary': '#FFFFFF',
            '--hm-bg-input': '#F8F9FD',
            '--hm-text': '#1A1A2E',
            '--hm-text-secondary': '#5A5A74',
            '--hm-border': '#C9CDE2',
            '--hm-accent': '#0066D6',
            '--hm-accent-hover': '#0057B8',
            '--hm-accent-text': '#FFFFFF',
            '--hm-danger': '#C82333',
            '--hm-danger-hover': '#B21F2D',
            '--hm-danger-text': '#FFFFFF',
            '--hm-radius': '12px',
            '--hm-overlay-bg': 'rgba(26,26,46,0.35)',
            '--hm-font-size': '14px',
            '--hm-shadow': '0 18px 50px rgba(26,26,46,0.18)',
            '--hm-busy-bg': 'rgba(255,255,255,0.82)',
        },
        toast: {
            '--ht-bg': '#F2F3FA',
            '--ht-bg-success': '#D2E1DC',
            '--ht-bg-warning': '#E9DBD6',
            '--ht-bg-error': '#ECD4DC',
            '--ht-fg': '#1A1A2E',
            '--ht-border': '#C9CDE2',
            '--ht-accent-info': '#0066D6',
            '--ht-accent-success': '#1E7E34',
            '--ht-accent-warning': '#B45309',
            '--ht-accent-error': '#C82333',
            '--ht-shadow': '0 6px 24px rgba(26,26,46,0.18)',
            '--ht-radius': '10px',
        },
    },
};

/* ─── Catalogue des 12 thèmes proposables ──────────────────────────────────
 * Les 2 packs aikore + les 10 <famille>-<mode> de holaf-tokens.
 * Les 4 alias historiques (dark/light/midnight/slate) sont VOLONTAIREMENT
 * exclus : l'alias toast `dark` est un preset gelé non aligné sur indigo-dark,
 * et les noms nus prêtent à confusion dans un sélecteur.                    */
const HOLAF_FAMILIES = ['indigo', 'midnight', 'slate', 'emerald', 'amber'];
const MODES = ['dark', 'light'];
const FAMILY_LABELS = {
    aikore: 'AiKore',
    indigo: 'Indigo',
    midnight: 'Midnight',
    slate: 'Slate',
    emerald: 'Emerald',
    amber: 'Amber',
};

const THEME_INDEX = new Map();

(function buildCatalogue() {
    THEME_INDEX.set('aikore-dark', { name: 'aikore-dark', label: 'AiKore Dark', mode: 'dark', family: 'aikore' });
    THEME_INDEX.set('aikore-light', { name: 'aikore-light', label: 'AiKore Light', mode: 'light', family: 'aikore' });
    HOLAF_FAMILIES.forEach((family) => {
        MODES.forEach((mode) => {
            const name = family + '-' + mode;
            THEME_INDEX.set(name, {
                name: name,
                label: FAMILY_LABELS[family] + (mode === 'dark' ? ' Dark' : ' Light'),
                mode: mode,
                family: family,
            });
        });
    });
})();

/* ─── Enregistrement des packs dans les 3 registres ────────────────────────
 * Idempotent et « retry-safe » : HolafTokens peut ne pas être encore chargé à
 * la première évaluation (balise defer) — initTheme() / applyTheme() rappellent
 * cette fonction et complètent l'enregistrement dès qu'il est disponible.   */
const registeredInTokens = new Set();
const registeredInModal = new Set();
const registeredInToast = new Set();

function tokensApi() {
    return (typeof window !== 'undefined' && window.HolafTokens) ? window.HolafTokens : null;
}

function registerAikorePacks() {
    const api = tokensApi();
    Object.keys(AIKORE_THEMES).forEach((name) => {
        const pack = AIKORE_THEMES[name];
        if (api && !registeredInTokens.has(name)) {
            try {
                api.registerPreset(name, pack.tokens);
                registeredInTokens.add(name);
            } catch (error) {
                console.warn('[AiKore themes] registerPreset a échoué pour "' + name + '" :', error.message);
            }
        }
        if (!registeredInModal.has(name)) {
            HolafModal.themes.register(name, pack.modal);
            registeredInModal.add(name);
        }
        if (!registeredInToast.has(name)) {
            HolafToast.themes.register(name, pack.toast);
            registeredInToast.add(name);
        }
    });
}

// Première tentative dès l'évaluation du module (les briques modal/toast sont
// déjà importées ; les tokens sont enregistrés si le script defer les a posés).
registerAikorePacks();

/* ─── API publique ─────────────────────────────────────────────────────── */

// Nom du dernier thème appliqué avec succès (null avant initTheme/applyTheme).
let currentTheme = null;

/**
 * Liste les thèmes proposables (12) avec libellé lisible et mode.
 * @returns {Array<{name: string, label: string, mode: 'light'|'dark', family: string}>}
 */
export function listThemes() {
    return Array.from(THEME_INDEX.values()).map((t) => ({ ...t }));
}

/**
 * Applique un thème à TOUTE l'app : tokens de page, modales, toasts +
 * attributs data-theme/data-mode sur <html> + persistance localStorage.
 * Un nom inconnu ne lève PAS : avertissement + repli sur aikore-dark.
 * @param {string} name
 * @returns {{name: string, mode: 'light'|'dark'}} thème effectivement appliqué
 */
export function applyTheme(name) {
    registerAikorePacks();

    const requested = typeof name === 'string' ? name.trim() : '';
    let effective = requested;
    if (!THEME_INDEX.has(effective)) {
        console.warn('[AiKore themes] thème inconnu "' + String(name) + '" — repli sur ' + DEFAULT_THEME + '.');
        effective = DEFAULT_THEME;
    }

    const api = tokensApi();
    if (api) {
        try {
            api.setTheme(effective);
        } catch (error) {
            // Ceinture de sécurité : un preset manquant (enregistrement refusé)
            // ne doit jamais casser le boot.
            console.warn('[AiKore themes] setTheme a échoué pour "' + effective + '" :', error.message);
            if (effective !== DEFAULT_THEME) {
                effective = DEFAULT_THEME;
                try { api.setTheme(effective); } catch (e2) { /* fallbacks CSS */ }
            }
        }
    } else {
        console.warn('[AiKore themes] window.HolafTokens indisponible — les fallbacks CSS restent actifs.');
    }

    // Les briques ont leurs propres registres : on les aligne explicitement.
    HolafModal.setTheme(effective);
    HolafToast.setTheme(effective);

    // IMPORTANT : currentTheme est mis à jour AVANT l'événement — tout
    // écouteur de « aikore-theme-changed » qui appelle getCurrentTheme() doit
    // voir le NOUVEAU thème (sélecteur, xterm/CodeMirror), pas le précédent.
    currentTheme = effective;

    const mode = THEME_INDEX.get(effective).mode;
    if (typeof document !== 'undefined') {
        const root = document.documentElement;
        root.setAttribute('data-theme', effective);
        root.setAttribute('data-mode', mode);
        document.dispatchEvent(new CustomEvent(THEME_EVENT, {
            detail: { theme: effective, mode: mode },
        }));
    }

    try {
        if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, effective);
    } catch (error) {
        // Stockage indisponible (mode privé, quota) : le thème reste appliqué
        // pour la session, seule la persistance est perdue.
    }

    return { name: effective, mode: mode };
}

/**
 * Thème actuellement appliqué (dernier applyTheme réussi), ou null avant init.
 * @returns {{name: string, label: string, mode: 'light'|'dark', family: string}|null}
 */
export function getCurrentTheme() {
    if (!currentTheme || !THEME_INDEX.has(currentTheme)) return null;
    return { ...THEME_INDEX.get(currentTheme) };
}

/**
 * Boot du thème : enregistre les packs, lit localStorage['aikoreTheme'] et
 * applique le thème sauvegardé — sinon aikore-dark (défaut visuel historique).
 * @returns {{name: string, mode: 'light'|'dark'}}
 */
export function initTheme() {
    registerAikorePacks();

    let saved = null;
    try {
        if (typeof localStorage !== 'undefined') saved = localStorage.getItem(STORAGE_KEY);
    } catch (error) {
        saved = null;
    }

    const initial = (saved && THEME_INDEX.has(saved)) ? saved : DEFAULT_THEME;
    return applyTheme(initial);
}
