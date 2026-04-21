// AiKore Welcome Animation
// Renders the ASCII logo on a canvas with a wave effect and cycling accent colors.
// Always scales to fit the viewport — no zoom controls needed.

document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('welcome-canvas');
    if (!canvas) return;

    const LOGO_PATH = 'logos/aikore-smooth.txt';
    const FONT = '"Courier New", Courier, monospace';
    const CHAR_COLOR = '#e0e0e0';
    const ACCENT_COLORS = ['#00ff9d', '#ff00ff', '#00ffff', '#ffff00', '#ff9900', '#ff4d4d', '#4d4dff'];
    const WAVE_AMPLITUDE = 3;
    const WAVE_SPEED = 8.0;
    const COLOR_IDLE_MS = 3800;
    const COLOR_TRANSITION_MS = 1200;

    // --- State ---
    let particles = [];   // { char, x, y, cellW, size }
    let rows = [];        // { y, startIdx, endIdx, height }
    let logoOffscreen = null;
    let cssW = 0, cssH = 0, dpr = 1;
    let fontSize = 14;

    let currentColorIdx = 0;
    let prevColor = ACCENT_COLORS[0];
    let nextColor = ACCENT_COLORS[0];
    let transitioning = false;
    let transitionStart = 0;

    let animId = null;
    let colorTimer = null;

    // --- Helpers ---
    function hexToRgb(hex) {
        const m = hex.match(/\w\w/g);
        return m ? m.map(c => parseInt(c, 16)) : [0, 0, 0];
    }

    function blendHex(a, b, t) {
        const [rA, gA, bA] = hexToRgb(a);
        const [rB, gB, bB] = hexToRgb(b);
        const r = Math.round(rA + (rB - rA) * t).toString(16).padStart(2, '0');
        const g = Math.round(gA + (gB - gA) * t).toString(16).padStart(2, '0');
        const bl = Math.round(bA + (bB - bA) * t).toString(16).padStart(2, '0');
        return '#' + r + g + bl;
    }

    // --- Init ---
    async function init() {
        const resp = await fetch(LOGO_PATH);
        if (!resp.ok) return;
        const text = await resp.text();
        const lines = text.split('\n').map(l => l.trimEnd()).filter(l => l.length > 0);
        if (lines.length === 0) return;

        resizeCanvas(lines);
        startColorCycle();
        animate(performance.now());
    }

    function resizeCanvas(lines) {
        dpr = window.devicePixelRatio || 1;
        cssW = canvas.offsetWidth;
        cssH = canvas.offsetHeight;
        if (cssW === 0 || cssH === 0) return;

        canvas.width = Math.floor(cssW * dpr);
        canvas.height = Math.floor(cssH * dpr);

        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        // Compute auto-fit font size
        const baseFontSize = 14;
        ctx.font = `${baseFontSize}px ${FONT}`;
        const baseCharW = ctx.measureText('W').width;

        const maxLineLen = Math.max(...lines.map(l => l.length));
        const scaleX = cssW / (maxLineLen * baseCharW);
        const scaleY = cssH / (lines.length * baseFontSize);
        const scale = Math.min(scaleX, scaleY) * 0.85;

        fontSize = baseFontSize * scale;
        ctx.font = `${fontSize}px ${FONT}`;
        const charW = ctx.measureText('W').width;

        const logoW = maxLineLen * charW;
        const logoH = lines.length * fontSize;
        const startX = (cssW - logoW) / 2;
        const startY = (cssH - logoH) / 2;

        // Build particles and rows
        particles = [];
        rows = [];
        let pIdx = 0;

        for (let y = 0; y < lines.length; y++) {
            const line = lines[y];
            const rowY = startY + y * fontSize;
            const rowStart = pIdx;

            for (let x = 0; x < line.length; x++) {
                if (line[x].trim() !== '') {
                    particles.push({
                        char: line[x],
                        x: startX + x * charW,
                        y: rowY,
                        cellW: charW,
                        size: fontSize
                    });
                    pIdx++;
                }
            }
            rows.push({ y: rowY, startIdx: rowStart, endIdx: pIdx, height: fontSize });
        }

        // Rebuild offscreen canvas
        rebuildOffscreen(ACCENT_COLORS[currentColorIdx]);
    }

    function rebuildOffscreen(accentColor) {
        logoOffscreen = document.createElement('canvas');
        logoOffscreen.width = Math.floor(cssW * dpr);
        logoOffscreen.height = Math.floor(cssH * dpr);
        const c = logoOffscreen.getContext('2d');
        c.setTransform(dpr, 0, 0, dpr, 0, 0);
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.font = `${fontSize}px ${FONT}`;

        // Accent-colored background blocks behind chars (subtle fill)
        c.globalAlpha = 0.35;
        c.fillStyle = accentColor;
        for (const p of particles) {
            const rw = p.cellW * 0.8;
            const rh = p.size * 0.8;
            c.fillRect(p.x - rw / 2, p.y - rh / 2, rw, rh);
        }

        // White characters on top
        c.globalAlpha = 1.0;
        c.fillStyle = CHAR_COLOR;
        for (const p of particles) {
            c.fillText(p.char, p.x, p.y);
        }
    }

    // --- Color cycling ---
    function startColorCycle() {
        nextColorCycle();
        colorTimer = setInterval(nextColorCycle, COLOR_IDLE_MS + COLOR_TRANSITION_MS);
    }

    function nextColorCycle() {
        prevColor = nextColor;
        currentColorIdx = (currentColorIdx + 1) % ACCENT_COLORS.length;
        nextColor = ACCENT_COLORS[currentColorIdx];
        transitioning = true;
        transitionStart = performance.now();
    }

    let lastAccentColor = null;

    // --- Animation loop ---
    function animate(timestamp) {
        const elapsed = (timestamp - (animate.startT || timestamp)) / 1000;
        animate.startT = animate.startT || timestamp;

        // Compute active accent color
        let accentColor;
        if (transitioning) {
            const progress = Math.min((timestamp - transitionStart) / COLOR_TRANSITION_MS, 1.0);
            accentColor = blendHex(prevColor, nextColor, progress);
            if (progress >= 1.0) {
                transitioning = false;
                accentColor = nextColor;
            }
        } else {
            accentColor = nextColor;
        }

        // Only rebuild offscreen when accent color actually changes
        if (accentColor !== lastAccentColor) {
            lastAccentColor = accentColor;
            rebuildOffscreen(accentColor);
        }

        // Draw
        draw(elapsed);

        animId = requestAnimationFrame(animate);
    }

    function draw(time) {
        const ctx = canvas.getContext('2d');
        // Clear
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        if (!logoOffscreen || rows.length === 0) return;

        // Draw with wave effect: per-row clip + vertical offset
        for (const row of rows) {
            const waveY = WAVE_AMPLITUDE * 0.2 * Math.sin(
                (cssW > 0 ? (2 * Math.PI * 3) / cssW : 0.02) * row.y + WAVE_SPEED * time
            );
            const clipTop = row.y - row.height / 2 + waveY;

            ctx.save();
            ctx.beginPath();
            ctx.rect(0, clipTop, cssW, row.height);
            ctx.clip();
            ctx.drawImage(logoOffscreen, 0, waveY, cssW, cssH);
            ctx.restore();
        }
    }

    // --- Resize handling ---
    let resizeTimeout = null;

    function handleResize() {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(async () => {
            cancelAnimationFrame(animId);
            clearInterval(colorTimer);
            animate.startT = null;
            lastAccentColor = null;

            // Re-fetch and re-init
            const resp = await fetch(LOGO_PATH);
            if (!resp.ok) return;
            const text = await resp.text();
            const lines = text.split('\n').map(l => l.trimEnd()).filter(l => l.length > 0);
            if (lines.length === 0) return;

            resizeCanvas(lines);
            startColorCycle();
            animate(performance.now());
        }, 150);
    }

    // ResizeObserver for reliable detection (works inside iframes)
    new ResizeObserver(handleResize).observe(canvas);

    // Also listen for parent resize messages (iframe context)
    window.addEventListener('message', (e) => {
        if (e.data?.type === 'aikore-resize') handleResize();
    });

    // Start
    init();
});