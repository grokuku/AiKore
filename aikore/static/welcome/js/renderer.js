class Renderer {
    constructor(canvas, logoData, options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.logoData = logoData;

        this.fontFamily = options.fontFamily || '"Courier New", Courier, monospace';
        this.charColor = options.charColor || '#e0e0e0';
        
        this.haloConfig = {
            enabled: false,
            blur: 6,
            alpha: 0.4,
            threshold: 20
        };

        this.particles = [];
        this.transformedParticles = [];
        
        // ✅ Canvas temporaire créé UNE fois
        this.haloCanvas = document.createElement('canvas');
        this.haloCtx = this.haloCanvas.getContext('2d');
    }

    init() {
        const dpr = window.devicePixelRatio || 1;
        
        // ✅ MÊMES dimensions pour les deux canvas
        const width = Math.floor(this.canvas.offsetWidth * dpr);
        const height = Math.floor(this.canvas.offsetHeight * dpr);
        
        this.canvas.width = width;
        this.canvas.height = height;
        
        // ✅ RESET complet de la transformation avant de la réappliquer
        this.ctx.setTransform(1, 0, 0, 1, 0, 0); // Reset
        this.ctx.scale(dpr, dpr);
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';

        // ✅ Canvas halo: SETTRANSFORM ATOMIQUE (pas scale)
        this.haloCanvas.width = width;
        this.haloCanvas.height = height;
        this.haloCtx.setTransform(dpr, 0, 0, dpr, 0, 0); // ✅ IDENTIQUE au principal
        this.haloCtx.textAlign = 'center';
        this.haloCtx.textBaseline = 'middle';

        // ... code de calcul des particules ...
        const trimmedData = this.logoData.map(line => line.replace(/\s+$/g, ''));
        const nonEmptyLines = trimmedData.filter(line => line.length > 0);
        
        const maxLineLength = Math.max(...nonEmptyLines.map(line => line.length));
        const numLines = nonEmptyLines.length;

        const baseFontSize = 14;
        this.ctx.font = `${baseFontSize}px ${this.fontFamily}`;
        const baseCharWidth = this.ctx.measureText('W').width;

        const scaleX = this.canvas.offsetWidth / (maxLineLength * baseCharWidth);
        const scaleY = this.canvas.offsetHeight / (numLines * baseFontSize);
        const scale = Math.min(scaleX, scaleY) * 0.9;

        const finalFontSize = baseFontSize * scale;
        this.ctx.font = `${finalFontSize}px ${this.fontFamily}`;

        const charWidth = this.ctx.measureText('W').width;
        this.logoWidth = maxLineLength * charWidth;
        this.logoHeight = numLines * finalFontSize;

        const startX = (this.canvas.offsetWidth - this.logoWidth) / 2;
        const startY = (this.canvas.offsetHeight - this.logoHeight) / 2;

        this.particles = [];
        nonEmptyLines.forEach((line, yIndex) => {
            for (let xIndex = 0; xIndex < line.length; xIndex++) {
                const char = line[xIndex];
                if (char && char.trim() !== '') {
                    this.particles.push({
                        char: char,
                        x: startX + xIndex * charWidth,
                        y: startY + yIndex * finalFontSize,
                        originalY: startY + yIndex * finalFontSize,
                        originalX: startX + xIndex * charWidth,
                        size: finalFontSize,
                        cellWidth: charWidth
                    });
                }
            }
        });

        this.transformedParticles = new Array(this.particles.length);
    }

    draw(particlesToRender, color) {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // ✅ Dessiner le halo d'abord
        if (this.haloConfig.enabled && particlesToRender[0]?.size < this.haloConfig.threshold) {
            this._drawGlobalHalo(particlesToRender, color);
        }

        // Dessiner les particules
        for (let i = 0; i < particlesToRender.length; i++) {
            this._drawParticle(particlesToRender[i], color);
        }

        this.ctx.globalAlpha = 1.0;
    }

    // ✅ HALO GLOBAL: Tout est dessiné avec la même transformation
    _drawGlobalHalo(particles, color) {
        // 1. Effacer avec les dimensions PHYSIQUES (px)
        this.haloCtx.clearRect(0, 0, this.haloCanvas.width, this.haloCanvas.height);
        
        // 2. Dessiner les caractères sur le canvas temporaire
        this.haloCtx.globalAlpha = 1.0;
        this.haloCtx.fillStyle = color;
        
        for (let i = 0; i < particles.length; i++) {
            const p = particles[i];
            this.haloCtx.font = `${p.size}px ${this.fontFamily}`;
            // ✅ Coordonnées CSS - la transformation s'occupe du reste
            this.haloCtx.fillText(p.char, p.x, p.y);
        }
        
        // 3. Flouter et copier sur le canvas principal
        this.ctx.save();
        this.ctx.globalAlpha = this.haloConfig.alpha;
        this.ctx.filter = `blur(${this.haloConfig.blur}px)`;
        this.ctx.globalCompositeOperation = 'screen';
        
        // ✅ COORDONNÉES (0,0) - pas de décalage
        this.ctx.drawImage(this.haloCanvas, 0, 0);
        
        this.ctx.restore();
        this.ctx.filter = 'none';
    }

    _drawParticle(p, color) {
        this.ctx.save();
        this.ctx.translate(p.x, p.y);
        this.ctx.rotate(p.rotation);

        // Rectangle de fond
        this.ctx.globalAlpha = p.pixelAlpha;
        this.ctx.fillStyle = color;
        const rectWidth = p.cellWidth * 0.8;
        const rectHeight = p.size * 0.8;
        this.ctx.fillRect(-rectWidth / 2, -rectHeight / 2, rectWidth, rectHeight);

        // Caractère
        this.ctx.globalAlpha = p.charAlpha;
        this.ctx.fillStyle = this.charColor;
        this.ctx.font = `${p.size}px ${this.fontFamily}`;
        this.ctx.fillText(p.char, 0, 0);

        this.ctx.restore();
    }

    resize() {
        this.init();
    }
}