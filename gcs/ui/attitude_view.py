from PyQt6.QtWebEngineWidgets import QWebEngineView

ATTITUDE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        body { margin: 0; padding: 0; overflow: hidden; background: #070d18; }
        #viewer { width: 100%; height: 100vh; position: relative; }
        .hud-overlay {
            position: absolute;
            top: 8px;
            right: 8px;
            z-index: 10;
            display: flex;
            gap: 6px;
            font-family: monospace;
            font-size: 11px;
            font-weight: bold;
            pointer-events: none;
        }
        .hud-pill {
            background: rgba(15, 23, 42, 0.85);
            border: 1px solid rgba(56, 189, 248, 0.3);
            color: #f8fafc;
            padding: 3px 8px;
            border-radius: 4px;
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
    <div id="viewer">
        <div class="hud-overlay">
            <div class="hud-pill" id="hud-roll">ROLL: +0.0&deg;</div>
            <div class="hud-pill" id="hud-pitch">PITCH: +0.0&deg;</div>
            <div class="hud-pill" id="hud-yaw" style="color:#38bdf8;">YAW: 045&deg;</div>
        </div>
    </div>
    <script>
        let scene, camera, renderer, drone;
        let rotorMeshes = [];

        function init() {
            const container = document.getElementById('viewer');
            const w = container.clientWidth || 300, h = container.clientHeight || 250;

            scene = new THREE.Scene();

            camera = new THREE.PerspectiveCamera(50, h ? w / h : 1, 0.1, 1000);
            camera.position.set(0, 3.5, 6);
            camera.lookAt(0, 0, 0);

            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setSize(w, h);
            renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            container.appendChild(renderer.domElement);

            scene.add(new THREE.AmbientLight(0xffffff, 0.7));
            const dir = new THREE.DirectionalLight(0xffffff, 0.9);
            dir.position.set(5, 10, 7);
            scene.add(dir);

            const fill = new THREE.DirectionalLight(0x38bdf8, 0.4);
            fill.position.set(-5, -5, -5);
            scene.add(fill);

            // reference grid (horizon)
            const grid = new THREE.GridHelper(20, 20, 0x0b57d0, 0x334155);
            grid.position.y = -1.5;
            scene.add(grid);

            // drone model
            drone = new THREE.Group();

            // center body
            const body = new THREE.Mesh(
                new THREE.BoxGeometry(1, 0.3, 1),
                new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.3, metalness: 0.8 })
            );
            drone.add(body);

            // arms + rotors in X-config. Front rotors cyan, rear green.
            const arms = [
                { x:  1.3, z:  1.3, front: true  },
                { x: -1.3, z:  1.3, front: true  },
                { x:  1.3, z: -1.3, front: false },
                { x: -1.3, z: -1.3, front: false }
            ];

            arms.forEach(a => {
                // arm (thin box from center to motor)
                const arm = new THREE.Mesh(
                    new THREE.BoxGeometry(0.15, 0.1, 0.15),
                    new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.5 })
                );
                arm.scale.z = Math.hypot(a.x, a.z) * 5;
                arm.position.set(a.x / 2, 0, a.z / 2);
                arm.lookAt(0, 0, 0);
                drone.add(arm);

                // rotor disc
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
                rotorMeshes.push(rotor);
            });

            scene.add(drone);
            animate();
        }

        function animate() {
            requestAnimationFrame(animate);
            rotorMeshes.forEach((r, idx) => {
                r.rotation.y += (idx % 2 === 0 ? 0.2 : -0.2);
            });
            renderer.render(scene, camera);
        }

        // called from Python with live attitude (radians)
        function updateAttitude(roll, pitch, yaw) {
            if (!drone) return;
            drone.rotation.order = 'YXZ';
            drone.rotation.y = -yaw;    // heading
            drone.rotation.x = pitch;   // nose up/down
            drone.rotation.z = -roll;   // bank

            const rDeg = (roll * 180 / Math.PI).toFixed(1);
            const pDeg = (pitch * 180 / Math.PI).toFixed(1);
            const yDeg = Math.round(((yaw * 180 / Math.PI) % 360 + 360) % 360).toString().padStart(3, '0');

            const elR = document.getElementById('hud-roll');
            if (elR) elR.innerHTML = 'ROLL: ' + (roll >= 0 ? '+' : '') + rDeg + '&deg;';
            const elP = document.getElementById('hud-pitch');
            if (elP) elP.innerHTML = 'PITCH: ' + (pitch >= 0 ? '+' : '') + pDeg + '&deg;';
            const elY = document.getElementById('hud-yaw');
            if (elY) elY.innerHTML = 'YAW: ' + yDeg + '&deg;';
        }

        window.addEventListener('resize', () => {
            const c = document.getElementById('viewer');
            if (camera && renderer && c.clientHeight) {
                camera.aspect = c.clientWidth / c.clientHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(c.clientWidth, c.clientHeight);
            }
        });

        window.addEventListener('load', () => {
            setTimeout(init, 50);
        });
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
