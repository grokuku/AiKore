class WaveEffect {
    // Le constructeur ne dépend plus du renderer initialisé
    constructor(amplitude = 3, frequency = 0.02, speed = 0.05) {
        this.amplitude = amplitude;
        this.frequency = frequency;
        this.speed = speed;
    }

    // Prend maintenant les dimensions en paramètres dynamiques
    apply(particle, time, logoWidth) {
        // Calcul dynamique de la fréquence basé sur la largeur actuelle
        const dynamicFreq = logoWidth > 0 ? (2 * Math.PI * 3) / logoWidth : this.frequency;
        const yOffset = this.amplitude * particle.size * 0.2 * 
                       Math.sin(dynamicFreq * particle.originalX + this.speed * time);
        
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