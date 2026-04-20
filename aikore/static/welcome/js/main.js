document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('welcome-canvas');
    if (!canvas) {
        console.error('Canvas element not found!');
        return;
    }

    const logoPath = 'logos/aikore-smooth.txt';

    function blendColors(colorA, colorB, amount) {
        const [rA, gA, bA] = colorA.match(/\w\w/g).map((c) => parseInt(c, 16));
        const [rB, gB, bB] = colorB.match(/\w\w/g).map((c) => parseInt(c, 16));
        const r = Math.round(rA + (rB - rA) * amount).toString(16).padStart(2, '0');
        const g = Math.round(gA + (gB - gA) * amount).toString(16).padStart(2, '0');
        const b = Math.round(bA + (bB - bA) * amount).toString(16).padStart(2, '0');
        return '#' + r + g + b;
    }

    class SceneManager {
        constructor(canvas, logoPath) {
            this.canvas = canvas;
            this.logoPath = logoPath;
            this.renderer = null;
            this.effect = null;
            this.state = 'loading';

            this.colors = ['#00ff9d', '#ff00ff', '#00ffff', '#ffff00', '#ff9900', '#ff4d4d', '#4d4dff'];
            
            this.currentColor = this.colors[0];
            this.previousColor = this.colors[0];

            this.startTime = performance.now();
            this.transitionStartTime = 0;
            this.transitionDuration = 1200;
            this.idleDuration = 3800;
            
            this._animFrameId = null;
            this._colorTransitionInterval = null;

            // Listen for resize messages from parent (for iframe context)
            this._onParentResize = () => {
                if (this.renderer) this.renderer.resize();
                this._recreateEffect();
            };
            window.addEventListener('message', (e) => {
                if (e.data?.type === 'aikore-resize') this._onParentResize();
            });
        }

        async load() {
            try {
                const response = await fetch(this.logoPath);
                if (!response.ok) throw new Error(`Failed to fetch logo: ${response.statusText}`);
                const logoText = await response.text();
                const logoData = logoText.split('\n');
                this.renderer = new Renderer(this.canvas, logoData);
                await this.start();
            } catch (error) {
                console.error('Error setting up animation:', error);
            }
        }

        async start() {
            if (!this.renderer) return;

            // Use ResizeObserver for reliable resize detection (works in iframes)
            this.renderer.observeResize(() => this._recreateEffect());

            this.renderer.init();
            this._recreateEffect();

            // Color transition timer
            this._colorTransitionInterval = setInterval(
                () => this.startTransition(),
                this.idleDuration + this.transitionDuration
            );

            this._animate();
        }

        _recreateEffect() {
            this.effect = new WaveEffect(3, 8.0);
        }

        startTransition() {
            this.previousColor = this.currentColor;
            this.currentColor = this.colors[Math.floor(Math.random() * this.colors.length)];
            this.state = 'transitioning';
            this.transitionStartTime = performance.now();
        }

        _animate() {
            const timestamp = performance.now();
            const elapsedTime = (timestamp - this.startTime) / 1000;

            let activeColor = this.currentColor;

            if (this.state === 'transitioning') {
                const transitionElapsed = timestamp - this.transitionStartTime;
                const progress = Math.min(transitionElapsed / this.transitionDuration, 1.0);
                activeColor = blendColors(this.previousColor, this.currentColor, progress);

                if (progress >= 1.0) {
                    this.state = 'idle';
                }
            }

            this.renderer.draw(elapsedTime, activeColor, this.effect);
            this._animFrameId = requestAnimationFrame((t) => this._animate(t));
        }

        destroy() {
            if (this._animFrameId) cancelAnimationFrame(this._animFrameId);
            if (this._colorTransitionInterval) clearInterval(this._colorTransitionInterval);
            if (this.renderer) this.renderer.destroy();
        }
    }

    const sceneManager = new SceneManager(canvas, logoPath);
    sceneManager.load();
});