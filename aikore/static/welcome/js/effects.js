class WaveEffect {
    constructor(amplitude = 3, speed = 8.0) {
        this.amplitude = amplitude;
        this.speed = speed;
    }

    /**
     * Returns the Y offset for a given row Y position.
     * Uses dynamic frequency based on logo width for consistent visual appearance.
     */
    getYOffset(y, time, logoWidth) {
        const dynamicFreq = logoWidth > 0 ? (2 * Math.PI * 3) / logoWidth : 0.02;
        return this.amplitude * 0.2 * Math.sin(dynamicFreq * y + this.speed * time);
    }
}