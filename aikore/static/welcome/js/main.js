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

            // FIX: Utilisation d'un timestamp réel au lieu d'un compteur
            this.startTime = performance.now();
            this.transitionStartTime = 0;
            this.transitionDuration = 1200;
            this.idleDuration = 3800;
            
            // Buffer pour éviter les allocations à chaque frame
            this.particlesBuffer = [];
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
            // Attendre l'initialisation du renderer
            if (!this.renderer) return;
            
            window.addEventListener('resize', () => {
                this.renderer.resize();
                this.recreateEffects();
            });
            
            this.renderer.init();
            
            // FIX: Création de l'effet avec des valeurs par défaut, recalculé dynamiquement
            this.recreateEffects();

            setInterval(() => this.startTransition(), this.idleDuration + this.transitionDuration);

            this.animate();
        }

        recreateEffects() {
            // L'effet est maintenant créé avec des paramètres qui seront ajustés dynamiquement
            this.currentEffect = new WaveEffect(3, 0.02, 8.0);
        }

        startTransition() {
            this.previousColor = this.currentColor;
            this.currentColor = this.colors[Math.floor(Math.random() * this.colors.length)];
            
            this.state = 'transitioning';
            this.transitionStartTime = performance.now();
        }

        animate() {
            if (!this.renderer) {
                requestAnimationFrame((timestamp) => this.animate(timestamp));
                return;
            }

            // FIX: Utilisation du timestamp réel pour une animation indépendante du framerate
            const timestamp = performance.now();
            const elapsedTime = (timestamp - this.startTime) / 1000; // en secondes

            let activeColor = this.currentColor;

            if (this.state === 'transitioning') {
                const transitionElapsed = timestamp - this.transitionStartTime;
                const progress = Math.min(transitionElapsed / this.transitionDuration, 1.0);
                activeColor = blendColors(this.previousColor, this.currentColor, progress);

                if (progress >= 1.0) {
                    this.state = 'idle';
                }
            }

            // OPTIMISATION: Réutilisation du buffer pour éviter les allocations
            if (this.particlesBuffer.length !== this.renderer.particles.length) {
                this.particlesBuffer = new Array(this.renderer.particles.length);
            }

            // Application de l'effet sans créer de nouveau tableau
            for (let i = 0; i < this.renderer.particles.length; i++) {
                const p = this.renderer.particles[i];
                const effectState = this.currentEffect.apply(p, elapsedTime, this.renderer.logoWidth);
                
                // IMMUABLE: Crée un nouvel objet sans modifier l'original
                this.particlesBuffer[i] = {
                    char: p.char,
                    ...effectState,
                    cellWidth: p.cellWidth // Assure que cellWidth est passé
                };
            }

            this.renderer.draw(this.particlesBuffer, activeColor);
            requestAnimationFrame((t) => this.animate(t));
        }
    }

    const sceneManager = new SceneManager(canvas, logoPath);
    sceneManager.load();
});