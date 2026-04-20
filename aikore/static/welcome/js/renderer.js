class Renderer {
    constructor(canvas, logoData, options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.logoData = logoData;

        this.fontFamily = options.fontFamily || '"Courier New", Courier, monospace';
        this.charColor = options.charColor || '#e0e0e0';

        this.particles = [];
        this.rows = [];
        this.logoWidth = 0;
        this.logoHeight = 0;

        // Pre-rendered offscreen canvas
        this._logoCanvas = null;

        // ResizeObserver for reliable iframe resize detection
        this._resizeObserver = null;

        // Cached dimensions (set in init, used in draw)
        this._cssW = 0;
        this._cssH = 0;
        this._dpr = 1;
    }

    init() {
        const dpr = window.devicePixelRatio || 1;

        const cssW = this.canvas.offsetWidth;
        const cssH = this.canvas.offsetHeight;

        if (cssW === 0 || cssH === 0) return;

        this._cssW = cssW;
        this._cssH = cssH;
        this._dpr = dpr;

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

        this._preRenderLogo(dpr, cssW, cssH);
    }

    _preRenderLogo(dpr, cssW, cssH) {
        this._logoCanvas = document.createElement('canvas');
        this._logoCanvas.width = Math.floor(cssW * dpr);
        this._logoCanvas.height = Math.floor(cssH * dpr);
        const lCtx = this._logoCanvas.getContext('2d');
        lCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        lCtx.textAlign = 'center';
        lCtx.textBaseline = 'middle';

        // Rectangles (placeholder white, replaced on first draw with accent color)
        lCtx.globalAlpha = 0.4;
        lCtx.fillStyle = '#ffffff';
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


    }

    draw(time, color, effect) {
        const dpr = this._dpr;
        const cssW = this._cssW;
        const cssH = this._cssH;

        // Clear in physical pixels, then re-apply DPR transform
        this.ctx.setTransform(1, 0, 0, 1, 0, 0);
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        if (!this._logoCanvas || this.rows.length === 0) return;

        // Re-render offscreen logo when color changes
        if (this._currentDrawColor !== color) {
            this._currentDrawColor = color;
            const lCtx = this._logoCanvas.getContext('2d');

            lCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
            lCtx.clearRect(0, 0, cssW, cssH);
            lCtx.textAlign = 'center';
            lCtx.textBaseline = 'middle';

            lCtx.globalAlpha = 0.4;
            lCtx.fillStyle = color;
            for (const p of this.particles) {
                const rectW = p.cellWidth * 0.8;
                const rectH = p.size * 0.8;
                lCtx.fillRect(p.x - rectW / 2, p.y - rectH / 2, rectW, rectH);
            }

            lCtx.globalAlpha = 1.0;
            lCtx.fillStyle = this.charColor;
            lCtx.font = `${this.particles[0]?.size || 14}px ${this.fontFamily}`;
            for (const p of this.particles) {
                lCtx.fillText(p.char, p.x, p.y);
            }


        }

        if (!effect) {
            // --- Static: draw entire image at once ---
            this.ctx.drawImage(this._logoCanvas, 0, 0, cssW, cssH);
        } else {
            // --- Wave: clip per row, draw entire image with vertical offset ---
            // The key: use 5-arg drawImage (entire source → dest rect),
            // NOT 9-arg drawImage (which uses source-rect in PHYSICAL pixels
            // and would only copy 1/DPR of the image on HiDPI screens).
            // The clip rect restricts what's visible for each row.
            for (const row of this.rows) {
                const waveOffset = effect.getYOffset(row.originalY, time, this.logoWidth);
                const clipY = row.y - row.height / 2 + waveOffset;
                this.ctx.save();
                this.ctx.beginPath();
                this.ctx.rect(0, clipY, cssW, row.height);
                this.ctx.clip();
                this.ctx.drawImage(this._logoCanvas, 0, waveOffset, cssW, cssH);
                this.ctx.restore();
            }
        }

        // Reset
        this.ctx.globalAlpha = 1.0;
        this.ctx.globalCompositeOperation = 'source-over';
    }

    resize() {
        this._currentDrawColor = null;
        this.init();
    }

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