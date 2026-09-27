from PyQt6.QtWebEngineWidgets import QWebEngineView

ATTITUDE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; padding: 0; overflow: hidden; background: #0f172a; font-family: monospace; }
        #container { position: relative; width: 100%; height: 100vh; }
        
        #viewer-3d { width: 100%; height: 100%; position: absolute; top: 0; left: 0; }
        #viewer-pfd { width: 100%; height: 100%; position: absolute; top: 0; left: 0; display: none; }
        
        /* Mode Switcher Buttons */
        #mode-switcher {
            position: absolute;
            top: 8px;
            right: 8px;
            z-index: 100;
            display: flex;
            background: rgba(15, 23, 42, 0.85);
            border-radius: 6px;
            padding: 3px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(4px);
        }
        .view-btn {
            background: transparent;
            color: #94a3b8;
            border: none;
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 10px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s;
        }
        .view-btn.active {
            background: #0b57d0;
            color: #ffffff;
        }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="container">
        <div id="viewer-3d"></div>
        <canvas id="viewer-pfd"></canvas>
        
        <div id="mode-switcher">
            <button id="btn-3d" class="view-btn active" onclick="setViewMode('3d')">3D MODEL</button>
            <button id="btn-pfd" class="view-btn" onclick="setViewMode('pfd')">PFD HUD</button>
        </div>
    </div>

    <script>
        let currentMode = '3d';
        let rollVal = 0, pitchVal = 0, yawVal = 0, altVal = 0, speedVal = 0;

        // ================== THREE.JS 3D MODEL ==================
        let scene, camera, renderer, drone;

        function init3D() {
            if (typeof THREE === 'undefined') {
                console.warn('Three.js CDN not available (offline). Switching to PFD HUD.');
                setViewMode('pfd');
                return;
            }
            const container = document.getElementById('viewer-3d');
            const w = container.clientWidth || 300, h = container.clientHeight || 200;

            scene = new THREE.Scene();
            camera = new THREE.PerspectiveCamera(50, h ? w / h : 1, 0.1, 1000);
            camera.position.set(0, 3.5, 6);
            camera.lookAt(0, 0, 0);

            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(w, h);
            container.appendChild(renderer.domElement);

            scene.add(new THREE.AmbientLight(0xffffff, 0.7));
            const dir = new THREE.DirectionalLight(0xffffff, 0.8);
            dir.position.set(5, 10, 7);
            scene.add(dir);

            const grid = new THREE.GridHelper(20, 20, 0x0b57d0, 0x334155);
            grid.position.y = -1.5;
            scene.add(grid);

            drone = new THREE.Group();
            const body = new THREE.Mesh(
                new THREE.BoxGeometry(1, 0.3, 1),
                new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.3, metalness: 0.8 })
            );
            drone.add(body);

            const arms = [
                { x:  1.3, z:  1.3, front: true  },
                { x: -1.3, z:  1.3, front: true  },
                { x:  1.3, z: -1.3, front: false },
                { x: -1.3, z: -1.3, front: false }
            ];

            arms.forEach(a => {
                const arm = new THREE.Mesh(
                    new THREE.BoxGeometry(0.15, 0.1, 0.15),
                    new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.5 })
                );
                arm.scale.z = Math.hypot(a.x, a.z) * 5;
                arm.position.set(a.x / 2, 0, a.z / 2);
                arm.lookAt(0, 0, 0);
                drone.add(arm);

                const rotorColor = a.front ? 0x0b57d0 : 0x0f9d58;
                const rotor = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.5, 0.5, 0.05, 24),
                    new THREE.MeshStandardMaterial({
                        color: rotorColor,
                        emissive: rotorColor,
                        emissiveIntensity: 0.5,
                        transparent: true, opacity: 0.85
                    })
                );
                rotor.position.set(a.x, 0.15, a.z);
                drone.add(rotor);
            });

            scene.add(drone);
            animate3D();
        }

        function animate3D() {
            requestAnimationFrame(animate3D);
            if (currentMode === '3d' && renderer && scene && camera) {
                renderer.render(scene, camera);
            }
        }

        // ================== PFD / ARTIFICIAL HORIZON ==================
        const pfdCanvas = document.getElementById('viewer-pfd');
        const ctx = pfdCanvas.getContext('2d');

        function resizeCanvas() {
            const container = document.getElementById('container');
            const w = container.clientWidth || 300;
            const h = container.clientHeight || 200;
            pfdCanvas.width = w * window.devicePixelRatio;
            pfdCanvas.height = h * window.devicePixelRatio;
            pfdCanvas.style.width = w + 'px';
            pfdCanvas.style.height = h + 'px';
            ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
            drawPFD();
        }

        function drawPFD() {
            if (currentMode !== 'pfd') return;
            const w = pfdCanvas.clientWidth;
            const h = pfdCanvas.clientHeight;
            if (!w || !h) return;

            const cx = w / 2;
            const cy = h / 2;
            const pitchPixelsPerDegree = h / 45; // 45 degrees vertical view span

            ctx.clearRect(0, 0, w, h);

            // --- 1. Artificial Horizon (Rotated & Translated) ---
            ctx.save();
            ctx.beginPath();
            ctx.rect(0, 0, w, h);
            ctx.clip();

            ctx.translate(cx, cy);
            ctx.rotate(-rollVal);
            const pitchOffset = (pitchVal * 180 / Math.PI) * pitchPixelsPerDegree;
            ctx.translate(0, pitchOffset);

            // Sky
            ctx.fillStyle = '#0284c7'; // Vibrant sky blue
            ctx.fillRect(-w * 2, -h * 4, w * 4, h * 4);

            // Ground
            ctx.fillStyle = '#78350f'; // Warm earth brown
            ctx.fillRect(-w * 2, 0, w * 4, h * 4);

            // Horizon line
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            ctx.moveTo(-w * 2, 0);
            ctx.lineTo(w * 2, 0);
            ctx.stroke();

            // Pitch Ladder
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
            ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            for (let deg = -40; deg <= 40; deg += 10) {
                if (deg === 0) continue;
                const y = -deg * pitchPixelsPerDegree;
                const barWidth = (deg % 20 === 0) ? 50 : 30;

                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(-barWidth, y);
                ctx.lineTo(barWidth, y);
                ctx.stroke();

                ctx.fillText(Math.abs(deg).toString(), -barWidth - 14, y);
                ctx.fillText(Math.abs(deg).toString(), barWidth + 14, y);
            }
            ctx.restore();

            // --- 2. Fixed Aircraft Reticle (Center Symbol) ---
            ctx.strokeStyle = '#fbbf24'; // Aviation Amber
            ctx.fillStyle = '#fbbf24';
            ctx.lineWidth = 3.5;
            ctx.beginPath();
            // Left wing
            ctx.moveTo(cx - 50, cy);
            ctx.lineTo(cx - 15, cy);
            ctx.lineTo(cx - 15, cy + 8);
            // Right wing
            ctx.moveTo(cx + 50, cy);
            ctx.lineTo(cx + 15, cy);
            ctx.lineTo(cx + 15, cy + 8);
            // Center pip
            ctx.arc(cx, cy, 3, 0, Math.PI * 2);
            ctx.stroke();

            // --- 3. Roll Indicator Arc (Top) ---
            ctx.save();
            ctx.translate(cx, cy);
            const rollRadius = Math.min(cx, cy) * 0.85;
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(0, 0, rollRadius, -Math.PI * 0.75, -Math.PI * 0.25);
            ctx.stroke();

            // Roll ticks
            [-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60].forEach(deg => {
                const rad = deg * Math.PI / 180 - Math.PI / 2;
                const len = (deg % 30 === 0) ? 10 : 5;
                const x1 = Math.cos(rad) * rollRadius;
                const y1 = Math.sin(rad) * rollRadius;
                const x2 = Math.cos(rad) * (rollRadius - len);
                const y2 = Math.sin(rad) * (rollRadius - len);
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.stroke();
            });

            // Bank pointer triangle
            ctx.rotate(-rollVal);
            ctx.fillStyle = '#fbbf24';
            ctx.beginPath();
            ctx.moveTo(0, -rollRadius);
            ctx.lineTo(-6, -rollRadius + 10);
            ctx.lineTo(6, -rollRadius + 10);
            ctx.closePath();
            ctx.fill();
            ctx.restore();

            // --- 4. Compass / Heading Tape (Top Strip) ---
            ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
            ctx.fillRect(0, 0, w, 24);
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
            ctx.strokeRect(0, 0, w, 24);

            const headingDeg = ((yawVal * 180 / Math.PI) % 360 + 360) % 360;
            const pxPerDegHeading = 3;
            ctx.fillStyle = '#38bdf8';
            ctx.font = '10px monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            for (let deg = 0; deg < 360; deg += 10) {
                let diff = deg - headingDeg;
                if (diff < -180) diff += 360;
                if (diff > 180) diff -= 360;
                const x = cx + diff * pxPerDegHeading;
                if (x >= 0 && x <= w) {
                    let label = deg.toString().padStart(3, '0');
                    if (deg === 0) label = 'N';
                    else if (deg === 90) label = 'E';
                    else if (deg === 180) label = 'S';
                    else if (deg === 270) label = 'W';
                    ctx.fillText(label, x, 12);
                }
            }
            // Heading center caret
            ctx.fillStyle = '#fbbf24';
            ctx.beginPath();
            ctx.moveTo(cx - 5, 22);
            ctx.lineTo(cx + 5, 22);
            ctx.lineTo(cx, 16);
            ctx.closePath();
            ctx.fill();

            // --- 5. Airspeed Tape (Left) & Altitude Tape (Right) ---
            // Left Speed Tape
            ctx.fillStyle = 'rgba(15, 23, 42, 0.8)';
            ctx.fillRect(0, 24, 45, h - 48);
            ctx.fillStyle = '#38bdf8';
            ctx.font = 'bold 11px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(speedVal.toFixed(1), 22, cy);
            ctx.font = '9px monospace';
            ctx.fillStyle = '#94a3b8';
            ctx.fillText('m/s', 22, cy + 14);

            // Right Altitude Tape
            ctx.fillStyle = 'rgba(15, 23, 42, 0.8)';
            ctx.fillRect(w - 50, 24, 50, h - 48);
            ctx.fillStyle = '#38bdf8';
            ctx.font = 'bold 11px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(altVal.toFixed(1), w - 25, cy);
            ctx.font = '9px monospace';
            ctx.fillStyle = '#94a3b8';
            ctx.fillText('ALT m', w - 25, cy + 14);
        }

        // ================== VIEW SWITCHING ==================
        function setViewMode(mode) {
            currentMode = mode;
            const btn3d = document.getElementById('btn-3d');
            const btnPfd = document.getElementById('btn-pfd');
            const view3d = document.getElementById('viewer-3d');
            const viewPfd = document.getElementById('viewer-pfd');

            if (mode === '3d') {
                btn3d.classList.add('active');
                btnPfd.classList.remove('active');
                view3d.style.display = 'block';
                viewPfd.style.display = 'none';
            } else {
                btnPfd.classList.add('active');
                btn3d.classList.remove('active');
                view3d.style.display = 'none';
                viewPfd.style.display = 'block';
                resizeCanvas();
            }
        }

        function updateAttitude(roll, pitch, yaw, alt, speed) {
            rollVal = roll || 0;
            pitchVal = pitch || 0;
            yawVal = yaw || 0;
            if (alt !== undefined) altVal = alt;
            if (speed !== undefined) speedVal = speed;

            // Update 3D drone
            if (drone) {
                drone.rotation.order = 'YXZ';
                drone.rotation.y = -yawVal;
                drone.rotation.x = pitchVal;
                drone.rotation.z = -rollVal;
            }

            // Update PFD Canvas if visible
            if (currentMode === 'pfd') {
                drawPFD();
            }
        }

        window.addEventListener('resize', () => {
            const c = document.getElementById('viewer-3d');
            if (camera && renderer && c.clientHeight) {
                camera.aspect = c.clientWidth / c.clientHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(c.clientWidth, c.clientHeight);
            }
            if (currentMode === 'pfd') {
                resizeCanvas();
            }
        });

        init3D();
        resizeCanvas();
    </script>
</body>
</html>
"""

class AttitudeView(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setHtml(ATTITUDE_HTML)

    def update_attitude(self, roll, pitch, yaw, alt=0.0, speed=0.0):
        self.page().runJavaScript(
            f"if (typeof updateAttitude === 'function') updateAttitude({roll}, {pitch}, {yaw}, {alt:.1f}, {speed:.1f});"
        )
