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

    function lerp(a, b, amount) {
        return a + (b - a) * amount;
    }

    class SceneManager {
        constructor(canvas, logoPath) {
            this.canvas = canvas;
            this.logoPath = logoPath;
            this.renderer = null;
            this.state = 'loading'; // loading, transitioning, idle

            this.colors = ['#00ff9d', '#ff00ff', '#00ffff', '#ffff00', '#ff9900', '#ff4d4d', '#4d4dff'];
            this.effects = [WaveEffect, ZoomRotateEffect];
            
            this.previousEffect = null;
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
            this.previousEffect = this.currentEffect;

            setInterval(() => this.startTransition(), this.idleDuration + this.transitionDuration);

            this.animate();
        }

        recreateEffects() {
            this.currentEffect = new (this.currentEffect.constructor)(this.renderer);
            this.previousEffect = new (this.previousEffect.constructor)(this.renderer);
        }

        startTransition() {
            this.previousEffect = this.currentEffect;
            this.previousColor = this.currentColor;

            let NextEffectClass;
            do {
                NextEffectClass = this.effects[Math.floor(Math.random() * this.effects.length)];
            } while (NextEffectClass === this.currentEffect.constructor);

            this.currentEffect = new NextEffectClass(this.renderer);
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
            let progress = 1.0;
            let activeColor = this.currentColor;

            if (this.state === 'transitioning') {
                const elapsedTime = Date.now() - this.transitionStartTime;
                progress = Math.min(elapsedTime / this.transitionDuration, 1.0);
                activeColor = blendColors(this.previousColor, this.currentColor, progress);

                if (progress >= 1.0) {
                    this.state = 'idle';
                }
            }

            const particlesToRender = this.renderer.particles.map(p => {
                const prevState = this.previousEffect.apply(p, this.time);
                const currentState = this.currentEffect.apply(p, this.time);

                // Interpolate all properties
                return {
                    char: p.char,
                    x: lerp(prevState.x, currentState.x, progress),
                    y: lerp(prevState.y, currentState.y, progress),
                    rotation: lerp(prevState.rotation, currentState.rotation, progress),
                    size: lerp(prevState.size, currentState.size, progress),
                    pixelAlpha: lerp(prevState.pixelAlpha, currentState.pixelAlpha, progress),
                    charAlpha: lerp(prevState.charAlpha, currentState.charAlpha, progress),
                };
            });

            this.renderer.draw(particlesToRender, activeColor);
            requestAnimationFrame(() => this.animate());
        }
    }

    const sceneManager = new SceneManager(canvas, logoPath);
    sceneManager.load();
});
