from PyQt6.QtWebEngineWidgets import QWebEngineView

ATTITUDE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0;
            padding: 0;
            overflow: hidden;
            background: #080d1a;
            font-family: 'JetBrains Mono', 'Google Sans Code', monospace;
            user-select: none;
        }
        #cad-container {
            width: 100%;
            height: 100vh;
            position: relative;
            background: radial-gradient(circle at 50% 50%, #0f1c30 0%, #060913 100%);
        }
        
        /* CAD Blueprint Grid Overlay */
        .cad-grid-bg {
            position: absolute;
            inset: 0;
            background-image:
                linear-gradient(rgba(56, 189, 248, 0.04) 1px, transparent 1px),
                linear-gradient(90deg, rgba(56, 189, 248, 0.04) 1px, transparent 1px);
            background-size: 24px 24px;
            pointer-events: none;
        }

        /* CAD HUD Overlays */
        .cad-hud-top-left {
            position: absolute;
            top: 10px;
            left: 12px;
            z-index: 10;
            font-size: 10px;
            font-weight: 700;
            color: #38bdf8;
            letter-spacing: 0.05em;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .cad-hud-top-left span.live-dot {
            width: 7px;
            height: 7px;
            background: #10b981;
            border-radius: 50%;
            box-shadow: 0 0 8px #10b981;
            animation: pulse-dot 1.5s infinite;
        }
        @keyframes pulse-dot {
            0% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(1.3); }
            100% { opacity: 1; transform: scale(1); }
        }

        .cad-hud-top-right {
            position: absolute;
            top: 10px;
            right: 12px;
            z-index: 10;
            display: flex;
            gap: 8px;
            font-size: 10px;
            font-weight: 700;
        }
        .cad-metric-pill {
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(56, 189, 248, 0.25);
            padding: 3px 8px;
            border-radius: 4px;
            color: #f8fafc;
        }

        .cad-hud-bottom {
            position: absolute;
            bottom: 8px;
            left: 12px;
            right: 12px;
            z-index: 10;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 9px;
            color: #64748b;
        }
        .btn-reset-view {
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: #94a3b8;
            font-family: inherit;
            font-size: 9px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .btn-reset-view:hover {
            background: #0284c7;
            color: #ffffff;
            border-color: #0284c7;
        }
    </style>
    <script src="http://localhost:PORT_PLACEHOLDER/static/three.min.js"></script>
    <script>
        if (typeof THREE === 'undefined') {
            document.write('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"><\\/script>');
        }
    </script>
</head>
<body>
    <div id="cad-container">
        <div class="cad-grid-bg"></div>

        <div class="cad-hud-top-left">
            <span class="live-dot"></span>
            <span>3D CAD TELEMETRY &bull; LIVE</span>
        </div>

        <div class="cad-hud-top-right">
            <div class="cad-metric-pill" id="hud-roll">ROLL: +0.0&deg;</div>
            <div class="cad-metric-pill" id="hud-pitch">PITCH: +0.0&deg;</div>
            <div class="cad-metric-pill" id="hud-yaw" style="color:#38bdf8;">YAW: 045&deg;</div>
        </div>

        <div class="cad-hud-bottom">
            <span>DRAG: ORBIT | WHEEL: ZOOM</span>
            <button class="btn-reset-view" onclick="resetCamera()">RESET VIEW</button>
        </div>
    </div>

    <script>
        let scene, camera, renderer, droneRoot, rotorDiscs = [];
        let rollVal = 0, pitchVal = 0, yawVal = 0;
        let isArmed = true;

        // Camera Orbit Controls State
        let isDragging = false;
        let prevMouse = { x: 0, y: 0 };
        let camAngleX = 0.4;  // Elevation
        let camAngleY = 0.0;  // Azimuth
        let camDist = 6.2;

        function initCAD() {
            const container = document.getElementById('cad-container');
            const w = container.clientWidth || 320;
            const h = container.clientHeight || 240;

            scene = new THREE.Scene();
            camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 1000);
            updateCameraPos();

            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(w, h);
            renderer.setPixelRatio(window.devicePixelRatio || 1);
            renderer.shadowMap.enabled = true;
            container.appendChild(renderer.domElement);

            // Lighting Setup
            const ambient = new THREE.AmbientLight(0xffffff, 0.65);
            scene.add(ambient);

            const keyLight = new THREE.DirectionalLight(0x38bdf8, 0.9);
            keyLight.position.set(6, 12, 8);
            scene.add(keyLight);

            const fillLight = new THREE.DirectionalLight(0xffffff, 0.5);
            fillLight.position.set(-6, -4, -6);
            scene.add(fillLight);

            // Circular Technical Reference Horizon Grid
            const gridHelper = new THREE.PolarGridHelper(4.5, 16, 8, 32, 0x0284c7, 0x1e293b);
            gridHelper.position.y = -1.2;
            scene.add(gridHelper);

            // Small XYZ axes indicator
            const axes = new THREE.AxesHelper(0.8);
            axes.position.set(-2.8, -1.1, 0);
            scene.add(axes);

            // Build Detailed Quadcopter CAD Model
            droneRoot = new THREE.Group();

            // 1. Center Carbon Fiber Chassis (Top & Bottom Plates)
            const carbonMat = new THREE.MeshStandardMaterial({
                color: 0x18202f,
                metalness: 0.85,
                roughness: 0.3
            });
            const topPlate = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.05, 1.1), carbonMat);
            topPlate.position.y = 0.12;
            droneRoot.add(topPlate);

            const bottomPlate = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.05, 1.2), carbonMat);
            bottomPlate.position.y = -0.12;
            droneRoot.add(bottomPlate);

            // Chassis Standoff Pillars
            const standoffMat = new THREE.MeshStandardMaterial({ color: 0x0284c7, metalness: 0.9, roughness: 0.2 });
            const standoffGeo = new THREE.CylinderGeometry(0.03, 0.03, 0.24, 8);
            [[-0.45, -0.45], [0.45, -0.45], [-0.45, 0.45], [0.45, 0.45]].forEach(pos => {
                const s = new THREE.Mesh(standoffGeo, standoffMat);
                s.position.set(pos[0], 0, pos[1]);
                droneRoot.add(s);
            });

            // 2. Pixhawk 6C Autopilot Cube in Center
            const pixhawkMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.4 });
            const pixhawk = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.14, 0.65), pixhawkMat);
            pixhawk.position.y = 0.2;
            droneRoot.add(pixhawk);

            // Pixhawk Status LED (breathing cyan)
            const ledMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8 });
            const led = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.02, 0.12), ledMat);
            led.position.set(0, 0.28, 0);
            droneRoot.add(led);

            // 3. Elevated GPS Puck on Carbon Mast
            const mastMat = new THREE.MeshStandardMaterial({ color: 0x334155, metalness: 0.6 });
            const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.45, 8), mastMat);
            mast.position.set(0, 0.4, -0.25);
            droneRoot.add(mast);

            const puckMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.3 });
            const puck = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.08, 16), puckMat);
            puck.position.set(0, 0.62, -0.25);
            droneRoot.add(puck);

            // 4. Directional Front Arrow (Aerodynamic Cyan Cone)
            const arrowMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x0284c7, emissiveIntensity: 0.4 });
            const noseArrow = new THREE.Mesh(new THREE.ConeGeometry(0.15, 0.4, 4), arrowMat);
            noseArrow.rotation.x = Math.PI / 2;
            noseArrow.position.set(0, 0.15, 0.75);
            droneRoot.add(noseArrow);

            // 5. Quad Tubular Arms (X-Configuration) & Brushless Motors
            const armMat = new THREE.MeshStandardMaterial({ color: 0x243044, metalness: 0.7, roughness: 0.4 });
            const motorMat = new THREE.MeshStandardMaterial({ color: 0x0b1320, metalness: 0.9, roughness: 0.2 });

            const armConfigs = [
                { x:  1.3, z:  1.3, front: true,  dir: 1 },  // Front Right
                { x: -1.3, z:  1.3, front: true,  dir: -1 }, // Front Left
                { x:  1.3, z: -1.3, front: false, dir: -1 }, // Rear Right
                { x: -1.3, z: -1.3, front: false, dir: 1 }   // Rear Left
            ];

            armConfigs.forEach(cfg => {
                // Tubular Arm
                const armLen = Math.hypot(cfg.x, cfg.z);
                const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, armLen, 12), armMat);
                arm.position.set(cfg.x / 2, 0, cfg.z / 2);
                arm.rotation.z = Math.PI / 2;
                arm.rotation.y = Math.atan2(cfg.z, cfg.x);
                droneRoot.add(arm);

                // Motor Bell
                const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 0.16, 16), motorMat);
                motor.position.set(cfg.x, 0.1, cfg.z);
                droneRoot.add(motor);

                // Motor Highlight Ring
                const ringColor = cfg.front ? 0x0284c7 : 0x10b981;
                const ringMat = new THREE.MeshBasicMaterial({ color: ringColor });
                const ring = new THREE.Mesh(new THREE.CylinderGeometry(0.145, 0.145, 0.03, 16), ringMat);
                ring.position.set(cfg.x, 0.16, cfg.z);
                droneRoot.add(ring);

                // Spinning Propeller Rotor Blades
                const propGroup = new THREE.Group();
                propGroup.position.set(cfg.x, 0.2, cfg.z);

                const bladeColor = cfg.front ? 0x38bdf8 : 0x10b981;
                const propMat = new THREE.MeshStandardMaterial({
                    color: bladeColor,
                    transparent: true,
                    opacity: 0.7,
                    roughness: 0.3
                });

                const b1 = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.015, 0.1), propMat);
                propGroup.add(b1);
                droneRoot.add(propGroup);

                rotorDiscs.push({ group: propGroup, dir: cfg.dir });

                // Landing Skid Leg
                const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.5, 8), carbonMat);
                leg.position.set(cfg.x * 0.7, -0.35, cfg.z * 0.7);
                leg.rotation.z = (cfg.x > 0 ? -1 : 1) * 0.25;
                droneRoot.add(leg);
            });

            scene.add(droneRoot);

            // Mouse Drag Interaction for CAD Orbit
            container.addEventListener('mousedown', e => {
                isDragging = true;
                prevMouse = { x: e.clientX, y: e.clientY };
            });
            window.addEventListener('mouseup', () => { isDragging = false; });
            window.addEventListener('mousemove', e => {
                if (!isDragging) return;
                const dx = e.clientX - prevMouse.x;
                const dy = e.clientY - prevMouse.y;
                camAngleY -= dx * 0.008;
                camAngleX = Math.max(-0.2, Math.min(1.4, camAngleX + dy * 0.008));
                prevMouse = { x: e.clientX, y: e.clientY };
                updateCameraPos();
            });
            container.addEventListener('wheel', e => {
                camDist = Math.max(3.2, Math.min(11.0, camDist + e.deltaY * 0.004));
                updateCameraPos();
            });

            window.addEventListener('resize', onWindowResize);
            animateLoop();
        }

        function updateCameraPos() {
            camera.position.x = camDist * Math.sin(camAngleY) * Math.cos(camAngleX);
            camera.position.y = camDist * Math.sin(camAngleX);
            camera.position.z = camDist * Math.cos(camAngleY) * Math.cos(camAngleX);
            camera.lookAt(0, 0.1, 0);
        }

        function resetCamera() {
            camAngleX = 0.4;
            camAngleY = 0.0;
            camDist = 6.2;
            updateCameraPos();
        }

        function animateLoop() {
            requestAnimationFrame(animateLoop);

            // Spin Propellers if armed
            if (isArmed) {
                rotorDiscs.forEach(r => {
                    r.group.rotation.y += 0.35 * r.dir;
                });
            }

            if (renderer && scene && camera) {
                renderer.render(scene, camera);
            }
        }

        function onWindowResize() {
            const container = document.getElementById('cad-container');
            if (!container || !renderer || !camera) return;
            const w = container.clientWidth || 320;
            const h = container.clientHeight || 240;
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h);
        }

        // Live Telemetry Sync from Python (Radians)
        function updateAttitude(roll, pitch, yaw) {
            rollVal = roll || 0;
            pitchVal = pitch || 0;
            yawVal = yaw || 0;

            if (droneRoot) {
                droneRoot.rotation.order = 'YXZ';
                droneRoot.rotation.y = -yawVal;   // Heading
                droneRoot.rotation.x = pitchVal;  // Pitch (nose up/down)
                droneRoot.rotation.z = -rollVal;  // Roll (bank)
            }

            // Update CAD HUD Readouts in Degrees
            const rDeg = (rollVal * 180 / Math.PI);
            const pDeg = (pitchVal * 180 / Math.PI);
            const yDeg = ((yawVal * 180 / Math.PI) % 360 + 360) % 360;

            const elR = document.getElementById('hud-roll');
            if (elR) elR.textContent = 'ROLL: ' + (rDeg >= 0 ? '+' : '') + rDeg.toFixed(1) + '\u00b0';

            const elP = document.getElementById('hud-pitch');
            if (elP) elP.textContent = 'PITCH: ' + (pDeg >= 0 ? '+' : '') + pDeg.toFixed(1) + '\u00b0';

            const elY = document.getElementById('hud-yaw');
            if (elY) elY.textContent = 'YAW: ' + Math.round(yDeg).toString().padStart(3, '0') + '\u00b0';
        }

        initCAD();
    </script>
</body>
</html>
"""

class AttitudeView(QWebEngineView):
    def __init__(self):
        super().__init__()
        from gcs.ui.tile_server import start_server
        port = start_server()
        local_html = ATTITUDE_HTML.replace("PORT_PLACEHOLDER", str(port))
        self.setHtml(local_html)

    def update_attitude(self, roll, pitch, yaw, alt=0.0, speed=0.0):
        self.page().runJavaScript(
            f"if (typeof updateAttitude === 'function') updateAttitude({roll}, {pitch}, {yaw});"
        )
