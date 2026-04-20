class Renderer {
    constructor(canvas, logoData, options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.logoData = logoData;

        this.fontFamily = options.fontFamily || '"Courier New", Courier, monospace';
        this.charColor = options.charColor || '#e0e0e0';

        this.particles = [];
        this.rows = [];       // Row data for strip-based rendering
        this.logoWidth = 0;
        this.logoHeight = 0;

        // Pre-rendered offscreen canvases
        this._logoCanvas = null;      // Static logo (characters + colored rects)
        this._glowCanvas = null;      // Pre-blurred glow version
        this._rowStrips = [];         // One strip per row (for wave animation)

        // ResizeObserver for reliable iframe resize detection
        this._resizeObserver = null;
    }

    init() {
        const dpr = window.devicePixelRatio || 1;

        const cssW = this.canvas.offsetWidth;
        const cssH = this.canvas.offsetHeight;

        if (cssW === 0 || cssH === 0) return;

        const physW = Math.floor(cssW * dpr);
        const physH = Math.floor(cssH * dpr);

        this.canvas.width = physW;
        this.canvas.height = physH;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';

        // Parse logo data
        const trimmedData = this.logoData.map(line => line.replace(/\s+$/g, ''));
        const nonEmptyLines = trimmedData.filter(line => line.length > 0);
        if (nonEmptyLines.length === 0) return;

        const maxLineLength = Math.max(...nonEmptyLines.map(line => line.length));
        const numLines = nonEmptyLines.length;

        // Calculate scaling
        const baseFontSize = 14;
        this.ctx.font = `${baseFontSize}px ${this.fontFamily}`;
        const baseCharWidth = this.ctx.measureText('W').width;

        const scaleX = cssW / (maxLineLength * baseCharWidth);
        const scaleY = cssH / (numLines * baseFontSize);
        const scale = Math.min(scaleX, scaleY) * 0.9;

        const finalFontSize = baseFontSize * scale;
        this.ctx.font = `${finalFontSize}px ${this.fontFamily}`;

        const charWidth = this.ctx.measureText('W').width;
        this.logoWidth = maxLineLength * charWidth;
        this.logoHeight = numLines * finalFontSize;

        const startX = (cssW - this.logoWidth) / 2;
        const startY = (cssH - this.logoHeight) / 2;

        // Build particle data and row metadata
        this.particles = [];
        this.rows = [];
        let particleIdx = 0;

        nonEmptyLines.forEach((line, yIndex) => {
            const rowY = startY + yIndex * finalFontSize;
            const rowStartIdx = particleIdx;

            for (let xIndex = 0; xIndex < line.length; xIndex++) {
                const char = line[xIndex];
                if (char && char.trim() !== '') {
                    this.particles.push({
                        char,
                        x: startX + xIndex * charWidth,
                        y: rowY,
                        originalY: rowY,
                        originalX: startX + xIndex * charWidth,
                        size: finalFontSize,
                        cellWidth: charWidth
                    });
                    particleIdx++;
                }
            }

            this.rows.push({
                y: rowY,
                originalY: rowY,
                startIdx: rowStartIdx,
                endIdx: particleIdx,
                height: finalFontSize
            });
        });

        // Pre-render static logo to offscreen canvas
        this._preRenderLogo(dpr, cssW, cssH);
    }

    _preRenderLogo(dpr, cssW, cssH) {
        // --- Offscreen canvas: static logo ---
        this._logoCanvas = document.createElement('canvas');
        this._logoCanvas.width = Math.floor(cssW * dpr);
        this._logoCanvas.height = Math.floor(cssH * dpr);
        const lCtx = this._logoCanvas.getContext('2d');
        lCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        lCtx.textAlign = 'center';
        lCtx.textBaseline = 'middle';

        // Draw all rectangles first (batch by color)
        lCtx.globalAlpha = 0.4;
        lCtx.fillStyle = '#ffffff'; // placeholder, will be replaced on first draw()
        for (const p of this.particles) {
            const rectW = p.cellWidth * 0.8;
            const rectH = p.size * 0.8;
            lCtx.fillRect(p.x - rectW / 2, p.y - rectH / 2, rectW, rectH);
        }

        // Draw all characters
        lCtx.globalAlpha = 1.0;
        lCtx.fillStyle = this.charColor;
        lCtx.font = `${this.particles[0]?.size || 14}px ${this.fontFamily}`;
        for (const p of this.particles) {
            lCtx.fillText(p.char, p.x, p.y);
        }

        // --- Pre-render glow (blurred) version ---
        this._glowCanvas = document.createElement('canvas');
        this._glowCanvas.width = this._logoCanvas.width;
        this._glowCanvas.height = this._logoCanvas.height;
        const gCtx = this._glowCanvas.getContext('2d');
        gCtx.filter = 'blur(6px)';
        gCtx.drawImage(this._logoCanvas, 0, 0);

        // --- Pre-render row strips for wave animation ---
        this._rowStrips = [];
        for (const row of this.rows) {
            const stripPhysY = Math.floor(row.originalY * dpr - row.height * 0.5 * dpr);
            const stripPhysH = Math.ceil(row.height * dpr);

            // Clamp to canvas bounds
            const clampedY = Math.max(0, stripPhysY);
            const clampedH = Math.min(this._logoCanvas.height - clampedY, stripPhysH);

            if (clampedH > 0) {
                this._rowStrips.push({
                    sourceY: clampedY,
                    sourceH: clampedH,
                    destBaseY: clampedY / dpr,  // CSS pixel destination
                    height: clampedH / dpr,
                    originalY: row.originalY
                });
            }
        }
    }

    draw(time, color, effect) {
        const dpr = window.devicePixelRatio || 1;
        const cssW = this.canvas.offsetWidth;
        const cssH = this.canvas.offsetHeight;

        this.ctx.setTransform(1, 0, 0, 1, 0, 0);
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        if (!this._logoCanvas || this._rowStrips.length === 0) return;

        // --- Update offscreen canvas fillStyle for the rectangles ---
        // We need to re-render the rectangles with the current color.
        // Instead of re-drawing everything, we use a tinting approach:
        // Draw white rects on the offscreen logo, and use globalCompositeOperation
        // to tint them. BUT that's complex — simpler: re-render rects only.
        // Actually, the cleanest approach for color changes: re-render the logo.

        // Optimization: only re-render logo when color changes
        if (this._currentDrawColor !== color) {
            this._currentDrawColor = color;
            const lCtx = this._logoCanvas.getContext('2d');

            // Clear and redraw with new color
            lCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
            lCtx.clearRect(0, 0, cssW, cssH);
            lCtx.textAlign = 'center';
            lCtx.textBaseline = 'middle';

            // Rectangles with the accent color
            lCtx.globalAlpha = 0.4;
            lCtx.fillStyle = color;
            for (const p of this.particles) {
                const rectW = p.cellWidth * 0.8;
                const rectH = p.size * 0.8;
                lCtx.fillRect(p.x - rectW / 2, p.y - rectH / 2, rectW, rectH);
            }

            // Characters
            lCtx.globalAlpha = 1.0;
            lCtx.fillStyle = this.charColor;
            lCtx.font = `${this.particles[0]?.size || 14}px ${this.fontFamily}`;
            for (const p of this.particles) {
                lCtx.fillText(p.char, p.x, p.y);
            }

            // Re-render glow
            const gCtx = this._glowCanvas.getContext('2d');
            gCtx.clearRect(0, 0, this._glowCanvas.width, this._glowCanvas.height);
            gCtx.filter = 'blur(6px)';
            gCtx.drawImage(this._logoCanvas, 0, 0);
        }

        // --- Draw glow layer (pre-blurred) ---
        this.ctx.save();
        this.ctx.globalAlpha = 0.4;
        this.ctx.globalCompositeOperation = 'screen';
        if (effect) {
            // Apply wave to glow too
            for (const strip of this._rowStrips) {
                const waveOffset = effect.getYOffset(strip.originalY, time, this.logoWidth);
                const destY = (strip.sourceY / dpr) + waveOffset;
                this.ctx.drawImage(
                    this._glowCanvas,
                    0, strip.sourceY, this._glowCanvas.width, strip.sourceH,
                    0, destY, cssW, strip.height
                );
            }
        } else {
            this.ctx.drawImage(this._glowCanvas, 0, 0, cssW, cssH);
        }
        this.ctx.restore();

        // --- Draw main logo with wave strips ---
        this.ctx.save();
        this.ctx.globalAlpha = 1.0;
        this.ctx.globalCompositeOperation = 'source-over';

        if (effect) {
            for (const strip of this._rowStrips) {
                const waveOffset = effect.getYOffset(strip.originalY, time, this.logoWidth);
                const destY = (strip.sourceY / dpr) + waveOffset;
                this.ctx.drawImage(
                    this._logoCanvas,
                    0, strip.sourceY, this._logoCanvas.width, strip.sourceH,
                    0, destY, cssW, strip.height
                );
            }
        } else {
            this.ctx.drawImage(this._logoCanvas, 0, 0, cssW, cssH);
        }
        this.ctx.restore();

        // Reset
        this.ctx.globalAlpha = 1.0;
        this.ctx.globalCompositeOperation = 'source-over';
    }

    resize() {
        this._currentDrawColor = null; // Force logo re-render on next draw
        this.init();
    }

    /**
     * Install a ResizeObserver on the canvas for reliable resize detection
     * inside iframes (window.resize doesn't always fire in iframes).
     */
    observeResize(callback) {
        if (this._resizeObserver) this._resizeObserver.disconnect();
        this._resizeObserver = new ResizeObserver(() => {
            this.resize();
            if (callback) callback();
        });
        this._resizeObserver.observe(this.canvas);
    }

    destroy() {
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
    }
}