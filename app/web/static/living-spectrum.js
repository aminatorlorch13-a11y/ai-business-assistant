import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js';

const canvas = document.getElementById('amination-scene');
const stage = document.querySelector('.ls-stage');

if (canvas && stage) {
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const mobile = window.matchMedia('(max-width: 700px)').matches;
    const lowPower = navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4;
    const quality = lowPower ? 0.7 : mobile ? 0.85 : 1;

    // The orb consists entirely of luminous particles.
    const particleCount = mobile ? 1400 : 2600;
    const orbRadius = 1.12;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
    camera.position.set(0, 0.12, 7.2);

    let renderer;

    try {
        renderer = new THREE.WebGLRenderer({
            canvas,
            alpha: true,
            antialias: quality > 0.7,
            powerPreference: 'high-performance'
        });
    } catch (error) {
        console.warn('Living Spectrum could not start WebGL:', error);
    }

    if (renderer) {
        renderer.setPixelRatio(
            Math.min(window.devicePixelRatio || 1, 1.6) * quality
        );

        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.2;

        const fallback = document.getElementById('ls-scene-fallback');
        if (fallback) fallback.hidden = true;

        const stateColors = {
            assembling: new THREE.Color(0xa77aff),
            idle: new THREE.Color(0x55e6ff),
            listening: new THREE.Color(0x55e6ff),
            processing: new THREE.Color(0xa77aff),
            speaking: new THREE.Color(0xe6c45a),
            responding: new THREE.Color(0x648bff)
        };

        let state = 'assembling';
        let lastFrame = 0;
        let destroyed = false;
        let assemblyComplete = false;
        let audioLevel = 0;
        let targetAudioLevel = 0;

        window.addEventListener('amination:audio-level', event => {
            const level = event.detail?.level;

            if (typeof level !== 'number' || !Number.isFinite(level)) {
                return;
            }

            targetAudioLevel = THREE.MathUtils.clamp(level, 0, 1);
        });

        const stateLabel = document.getElementById('ls-state-label');
        const stateDot = document.querySelector('.ls-state-dot');

        function setState(next) {
            if (!stateColors[next]) return;

            state = next;

            if (next !== 'speaking') {
                targetAudioLevel = 0;
            }

            if (stateLabel) {
                stateLabel.textContent = next.toUpperCase();
            }

            if (stateDot) {
                const hex = `#${stateColors[next].getHexString()}`;
                stateDot.style.background = hex;
                stateDot.style.boxShadow = `0 0 12px ${hex}`;
            }
        }

        window.addEventListener('amination:state', event => {
            const next = event.detail?.state;

            if (next && next !== 'assembling') {
                setState(next);
            }
        });

        // Generate an evenly distributed spherical particle surface.
        const startPositions = new Float32Array(particleCount * 3);
        const positions = new Float32Array(particleCount * 3);
        const targetPositions = new Float32Array(particleCount * 3);
        const colors = new Float32Array(particleCount * 3);

        const delays = new Float32Array(particleCount);
        const durations = new Float32Array(particleCount);

        const palette = [
            new THREE.Color(0x55e6ff),
            new THREE.Color(0x8b83ff),
            new THREE.Color(0x58baff),
            new THREE.Color(0xe6c45a)
        ];

        let longestJourney = 0;

        for (let i = 0; i < particleCount; i++) {
            const p = i * 3;

            const vertical = 1 - (2 * i) / (particleCount - 1);
            const horizontalRadius = Math.sqrt(
                Math.max(0, 1 - vertical * vertical)
            );

            const angle = i * goldenAngle;

            const x = Math.cos(angle) * horizontalRadius;
            const z = Math.sin(angle) * horizontalRadius;
            const subtleVariation = 1 + (Math.random() - 0.5) * 0.018;

            targetPositions[p] = x * orbRadius * subtleVariation;
            targetPositions[p + 1] =
                vertical * orbRadius * subtleVariation + 0.08;
            targetPositions[p + 2] = z * orbRadius * subtleVariation;

            // Particles begin scattered along the floor.
            startPositions[p] = (Math.random() - 0.5) * 4.6;
            startPositions[p + 1] = -2.15 + Math.random() * 0.14;
            startPositions[p + 2] = (Math.random() - 0.5) * 2.4;

            positions[p] = startPositions[p];
            positions[p + 1] = startPositions[p + 1];
            positions[p + 2] = startPositions[p + 2];

            const color = palette[
                Math.floor(Math.random() * palette.length)
            ];

            colors[p] = color.r;
            colors[p + 1] = color.g;
            colors[p + 2] = color.b;

            delays[i] = reducedMotion ? 0 : Math.random() * 3.0;
            durations[i] = reducedMotion ? 0 : 5.5 + Math.random() * 2.0;

            longestJourney = Math.max(
                longestJourney,
                delays[i] + durations[i]
            );
        }

        const geometry = new THREE.BufferGeometry();

        geometry.setAttribute(
            'position',
            new THREE.BufferAttribute(positions, 3)
        );

        geometry.setAttribute(
            'color',
            new THREE.BufferAttribute(colors, 3)
        );

        // A soft outer particle layer creates the luminous appearance.
        const glowMaterial = new THREE.PointsMaterial({
            size: mobile ? 0.12 : 0.105,
            vertexColors: true,
            transparent: true,
            opacity: 0.16,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
            sizeAttenuation: true
        });

        const particleMaterial = new THREE.PointsMaterial({
            size: mobile ? 0.052 : 0.041,
            vertexColors: true,
            transparent: true,
            opacity: 0.9,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
            sizeAttenuation: true
        });

        // Both layers share the same particle geometry.
        const orbGroup = new THREE.Group();

        const glowParticles = new THREE.Points(
            geometry,
            glowMaterial
        );

        const coreParticles = new THREE.Points(
            geometry,
            particleMaterial
        );

        orbGroup.add(glowParticles);
        orbGroup.add(coreParticles);
        scene.add(orbGroup);

        const assemblyStarted = performance.now();
        const assemblyDuration = reducedMotion
            ? 0
            : longestJourney * 1000;

        function resize() {
            if (destroyed) return;

            const width = Math.max(1, stage.clientWidth);
            const height = Math.max(1, stage.clientHeight);

            camera.aspect = width / height;
            camera.position.z = width < 500 ? 8.1 : 7.2;
            camera.updateProjectionMatrix();

            renderer.setSize(width, height, false);
        }

        const observer = new ResizeObserver(resize);
        observer.observe(stage);
        resize();

        function animate(now) {
            if (destroyed) return;

            requestAnimationFrame(animate);

            if (document.hidden) return;

            if (now - lastFrame < (mobile ? 32 : 16)) return;

            const delta = lastFrame
                ? Math.min(now - lastFrame, 50)
                : 16;

            lastFrame = now;

            const elapsed = now - assemblyStarted;

            // Dramatically assemble particles from the ground.
            if (!assemblyComplete) {
                for (let i = 0; i < particleCount; i++) {
                    const p = i * 3;

                    const localTime = elapsed - delays[i] * 1000;

                    const progress = reducedMotion
                        ? 1
                        : THREE.MathUtils.clamp(
                            localTime / (durations[i] * 1000),
                            0,
                            1
                        );

                    const eased =
                        progress * progress * (3 - 2 * progress);

                    // Calculate from the original starting position.
                    // This keeps the assembly animation predictable.
                    const spiral = (1 - eased) * 0.18;
                    const spiralAngle = i * 0.17 + eased * 5.5;

                    positions[p] =
                        startPositions[p] +
                        (targetPositions[p] - startPositions[p]) * eased +
                        Math.cos(spiralAngle) * spiral;

                    positions[p + 1] =
                        startPositions[p + 1] +
                        (targetPositions[p + 1] - startPositions[p + 1]) * eased +
                        Math.sin(progress * Math.PI) * 0.32;

                    positions[p + 2] =
                        startPositions[p + 2] +
                        (targetPositions[p + 2] - startPositions[p + 2]) * eased +
                        Math.sin(spiralAngle) * spiral;
                }

                geometry.attributes.position.needsUpdate = true;

                if (elapsed >= assemblyDuration) {
                    positions.set(targetPositions);
                    geometry.attributes.position.needsUpdate = true;

                    assemblyComplete = true;
                    setState('idle');
                }
            } else if (!reducedMotion) {
                // The completed orb rotates slowly and continuously.
                orbGroup.rotation.y += delta * 0.00012;

                // A restrained movement gives it a living presence.
                orbGroup.rotation.x =
                    Math.sin(now * 0.0002) * 0.035;
            }

            // Assistant states influence the orb's colour and glow.
            const color = stateColors[state] || stateColors.idle;

            particleMaterial.color.copy(color);
            glowMaterial.color.copy(color);

            // Smooth measured audio intensity to avoid visual jitter.
            const smoothing = targetAudioLevel > audioLevel ? 0.35 : 0.12;
            audioLevel += (targetAudioLevel - audioLevel) * smoothing;

            if (state === 'speaking') {
                // Speaking brightness comes from the actual audio analyser.
                particleMaterial.opacity = 0.84 + audioLevel * 0.16;
                glowMaterial.opacity = 0.13 + audioLevel * 0.32;

                if (!reducedMotion) {
                    glowParticles.scale.setScalar(1 + audioLevel * 0.035);
                } else {
                    glowParticles.scale.setScalar(1);
                }
            } else {
                // Preserve the restrained idle breathing effect.
                glowParticles.scale.setScalar(1);

                if (!reducedMotion) {
                    const pulse = Math.sin(now * 0.0012);
                    particleMaterial.opacity = 0.84 + pulse * 0.055;
                    glowMaterial.opacity =
                        0.13 + Math.max(0, pulse) * 0.09;
                } else {
                    particleMaterial.opacity = 0.9;
                    glowMaterial.opacity = 0.16;
                }
            }

            renderer.render(scene, camera);
        }

        setState('assembling');
        requestAnimationFrame(animate);

        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) lastFrame = 0;
        });

        window.addEventListener('pagehide', () => {
            destroyed = true;

            observer.disconnect();

            geometry.dispose();
            particleMaterial.dispose();
            glowMaterial.dispose();
            renderer.dispose();
        }, { once: true });
    }
}
