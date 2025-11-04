
class WaveEffect {
    constructor(renderer) {
        this.renderer = renderer;
        this.amplitude = (this.renderer.particles[0]?.size || 14) * 0.2;
        this.frequency = this.renderer.logoWidth > 0 ? (2 * Math.PI * 3) / this.renderer.logoWidth : 0.1;
        this.speed = 0.1;
    }

    apply(particle, time) {
        const yOffset = this.amplitude * Math.sin(this.frequency * particle.originalX + this.speed * time);
        return {
            x: particle.x,
            y: particle.originalY + yOffset,
            rotation: 0,
            size: particle.size,
            pixelAlpha: 0.4,
            charAlpha: 1.0,
        };
    }
}
