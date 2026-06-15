from PyQt6.QtWebEngineWidgets import QWebEngineView

ATTITUDE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <style>
        body { margin: 0; padding: 0; overflow: hidden; background: #ffffff; }
        #viewer { width: 100%; height: 100vh; }
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
    <div id="viewer"></div>
    <script>
        let scene, camera, renderer, drone;

        function init() {
            const container = document.getElementById('viewer');
            const w = container.clientWidth, h = container.clientHeight;

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

            // reference grid (horizon)
            const grid = new THREE.GridHelper(12, 12, 0x0b57d0, 0xcbd5e1);
            grid.position.y = -1.5;
            scene.add(grid);

            // drone model
            drone = new THREE.Group();

            // center body
            const body = new THREE.Mesh(
                new THREE.BoxGeometry(1, 0.3, 1),
                new THREE.MeshStandardMaterial({ color: 0x1f2937 })
            );
            drone.add(body);

            // arms + rotors in X-config. Front rotors cyan, rear gray.
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
                    new THREE.MeshStandardMaterial({ color: 0x94a3b8 })
                );
                arm.scale.z = Math.hypot(a.x, a.z) * 5;
                arm.position.set(a.x / 2, 0, a.z / 2);
                arm.lookAt(0, 0, 0);
                drone.add(arm);

                // rotor disc
                const rotor = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.5, 0.5, 0.05, 24),
                    new THREE.MeshStandardMaterial({
                        color: a.front ? 0x0b57d0 : 0x64748b,
                        transparent: true, opacity: 0.85
                    })
                );
                rotor.position.set(a.x, 0.15, a.z);
                drone.add(rotor);
            });

            scene.add(drone);
            animate();
        }

        function animate() {
            requestAnimationFrame(animate);
            renderer.render(scene, camera);
        }

        // called from Python with live attitude (radians)
        function updateAttitude(roll, pitch, yaw) {
            if (!drone) return;
            drone.rotation.order = 'YXZ';
            drone.rotation.y = -yaw;    // heading
            drone.rotation.x = pitch;   // nose up/down
            drone.rotation.z = -roll;   // bank
        }

        window.addEventListener('resize', () => {
            const c = document.getElementById('viewer');
            camera.aspect = c.clientHeight ? c.clientWidth / c.clientHeight : 1;
            camera.updateProjectionMatrix();
            renderer.setSize(c.clientWidth, c.clientHeight);
        });

        init();
    </script>
</body>
</html>
"""

class AttitudeView(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setHtml(ATTITUDE_HTML)

    def update_attitude(self, roll, pitch, yaw):
        self.page().runJavaScript(  # type: ignore
            f"if (typeof updateAttitude === 'function') updateAttitude({roll}, {pitch}, {yaw});"
        )