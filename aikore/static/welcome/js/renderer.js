class Renderer {
    constructor(canvas, logoData, options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.logoData = logoData;

        this.fontFamily = options.fontFamily || '"Courier New", Courier, monospace';
        this.charColor = options.charColor || '#e0e0e0';
        
        this.particles = [];
        // init() is now called externally by the scene manager
    }

    init() {
        // Set canvas dimensions
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = this.canvas.offsetWidth * dpr;
        this.canvas.height = this.canvas.offsetHeight * dpr;
        this.ctx.scale(dpr, dpr);

        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';

        const maxLineLength = Math.max(...this.logoData.map(line => line.length));
        const numLines = this.logoData.length;

        const baseFontSize = 14;
        this.ctx.font = `${baseFontSize}px ${this.fontFamily}`;
        const baseCharWidth = this.ctx.measureText('W').width;
        const baseCharHeight = baseFontSize;

        const logoBaseWidth = maxLineLength * baseCharWidth;
        const logoBaseHeight = numLines * baseCharHeight;

        const scaleX = this.canvas.offsetWidth / logoBaseWidth;
        const scaleY = this.canvas.offsetHeight / logoBaseHeight;
        const scale = Math.min(scaleX, scaleY) * 0.9;

        const finalFontSize = baseFontSize * scale;
        this.ctx.font = `${finalFontSize}px ${this.fontFamily}`;

        const charWidth = this.ctx.measureText('W').width;
        const charHeight = finalFontSize;

        const logoWidth = maxLineLength * charWidth;
        this.logoWidth = logoWidth;
        const logoHeight = numLines * charHeight;

        const startX = (this.canvas.offsetWidth - logoWidth) / 2;
        const startY = (this.canvas.offsetHeight - logoHeight) / 2;

        this.particles = [];
        this.logoData.forEach((line, yIndex) => {
            for (let xIndex = 0; xIndex < line.length; xIndex++) {
                const char = line[xIndex];
                if (char && char.trim() !== '') {
                    this.particles.push({
                        char: char,
                        x: startX + xIndex * charWidth,
                        y: startY + yIndex * charHeight,
                        originalY: startY + yIndex * charHeight, // For idle effect
                        originalX: startX + xIndex * charWidth, // For idle effect
                        size: finalFontSize
                    });
                }
            }
        });
    }

    draw(particlesToRender, color) {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        particlesToRender.forEach(p => {
            this.ctx.save();
            this.ctx.translate(p.x, p.y);
            this.ctx.rotate(p.rotation);

            // Draw pixel background
            this.ctx.globalAlpha = p.pixelAlpha;
            this.ctx.fillStyle = color;
            this.ctx.fillRect(-p.size * 0.4, -p.size * 0.4, p.size * 0.8, p.size * 0.8);

            // Draw character
            this.ctx.globalAlpha = p.charAlpha;
            this.ctx.fillStyle = this.charColor;
            this.ctx.font = `${p.size}px ${this.fontFamily}`;
            this.ctx.fillText(p.char, 0, 0);
            
            this.ctx.restore();
        });

        this.ctx.globalAlpha = 1.0;
    }

    resize() {
        this.init();
    }
}
