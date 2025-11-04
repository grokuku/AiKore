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
            this.state = 'loading'; // loading, transitioning, idle

            this.colors = ['#00ff9d', '#ff00ff', '#00ffff', '#ffff00', '#ff9900', '#ff4d4d', '#4d4dff'];
            
            this.currentEffect = null;
            this.currentColor = this.colors[0];
            this.previousColor = this.colors[0];

            this.time = 0;
            this.transitionStartTime = 0;
            this.transitionDuration = 1200;
            this.idleDuration = 3800;
        }

        async load() {
            try {
                const response = await fetch(this.logoPath);
                if (!response.ok) throw new Error(`Failed to fetch logo: ${response.statusText}`);
                const logoText = await response.text();
                const logoData = logoText.split('\n');
                this.renderer = new Renderer(this.canvas, logoData);
                this.start();
            } catch (error) {
                console.error('Error setting up animation:', error);
            }
        }

        start() {
            window.addEventListener('resize', () => {
                this.renderer.resize();
                this.recreateEffects();
            });
            this.renderer.init();
            this.currentEffect = new WaveEffect(this.renderer);

            setInterval(() => this.startTransition(), this.idleDuration + this.transitionDuration);

            this.animate();
        }

        recreateEffects() {
            this.currentEffect = new WaveEffect(this.renderer);
        }

        startTransition() {
            this.previousColor = this.currentColor;
            this.currentColor = this.colors[Math.floor(Math.random() * this.colors.length)];
            
            this.state = 'transitioning';
            this.transitionStartTime = Date.now();
        }

        animate() {
            if (!this.renderer) {
                requestAnimationFrame(() => this.animate());
                return;
            }

            this.time++;
            let activeColor = this.currentColor;

            if (this.state === 'transitioning') {
                const elapsedTime = Date.now() - this.transitionStartTime;
                const progress = Math.min(elapsedTime / this.transitionDuration, 1.0);
                activeColor = blendColors(this.previousColor, this.currentColor, progress);

                if (progress >= 1.0) {
                    this.state = 'idle';
                }
            }

            const particlesToRender = this.renderer.particles.map(p => {
                const effectState = this.currentEffect.apply(p, this.time);
                return {
                    char: p.char,
                    ...effectState
                };
            });

            this.renderer.draw(particlesToRender, activeColor);
            requestAnimationFrame(() => this.animate());
        }
    }

    const sceneManager = new SceneManager(canvas, logoPath);
    sceneManager.load();
});