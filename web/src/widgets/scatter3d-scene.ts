/**
 * The 3-D landscape's WebGL scene: one point cloud, drawn with three.js, outside React.
 *
 * Points are round sprites sized in world units, so they grow as the camera comes closer,
 * and fade with depth so the cloud reads as 3-D while it turns. Blending has no depth test:
 * points are drawn in the order given (the widget puts coloured clusters last), as in the
 * 2-D map. Picking is done on the CPU in screen space, the nearest point within a radius,
 * so the pointer only has to be close. The scene renders only when something changed.
 */
import {
  BufferAttribute,
  BufferGeometry,
  Matrix4,
  PerspectiveCamera,
  Points,
  Scene,
  ShaderMaterial,
  Spherical,
  WebGLRenderer,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  type Cloud,
  FOV,
  fitDistance,
  GHOST,
  nearestOnScreen,
  type Palette,
  RADIUS,
  sizes,
  tints,
} from "./scatter3d-points";

const HOME = new Spherical(1, 1.1, 0.6); // the starting angle: from above and to one side

const VERTEX = /* glsl */ `
  attribute vec4 tint;
  attribute float size;
  uniform float uScale;
  uniform vec2 uDepth;
  varying vec4 vTint;
  void main() {
    vec4 view = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * view;
    float depth = max(-view.z, 0.001);
    gl_PointSize = clamp(size * uScale / depth, 2.0, 48.0);
    float far = clamp((depth - uDepth.x) / max(uDepth.y - uDepth.x, 0.001), 0.0, 1.0);
    vTint = vec4(tint.rgb, tint.a * mix(1.0, 0.4, far));
  }
`;

const FRAGMENT = /* glsl */ `
  varying vec4 vTint;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    gl_FragColor = vec4(vTint.rgb, vTint.a * smoothstep(0.5, 0.36, d));
  }
`;

const RING = /* glsl */ `
  uniform vec3 uColor;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5 || d < 0.3) discard;
    gl_FragColor = vec4(uColor, smoothstep(0.5, 0.44, d) * smoothstep(0.3, 0.36, d));
  }
`;

const RING_VERTEX = /* glsl */ `
  uniform float uSize;
  void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = uSize;
  }
`;

export class LandscapeScene {
  readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  private readonly camera = new PerspectiveCamera(FOV, 1, 0.01, 100);
  private readonly controls: OrbitControls;
  private readonly geometry = new BufferGeometry();
  private readonly material: ShaderMaterial;
  private readonly ring: Points<BufferGeometry, ShaderMaterial>;
  private readonly projection = new Matrix4();
  private readonly uniforms = {
    uScale: { value: 1 }, // device pixels per world unit at distance 1
    uDepth: { value: [1, 3] }, // the cloud's near and far side from the camera
  };
  private readonly ringUniforms = { uSize: { value: 18 }, uColor: { value: [0, 0, 0] } };
  private cloud: Cloud | null = null;
  private palette: Palette | null = null;
  private highlight: number | null = null;
  private width = 1;
  private height = 1;
  private dirty = true;
  private running = false;
  private last = 0;
  private framed = false;
  private sizes: Float32Array = new Float32Array();
  private markedSize = 0.02;

  /** Called after each frame drawn, so what's under the pointer can be picked again. */
  onFrame: () => void = () => {};
  /** Called when the user starts turning the view (auto-rotation stops then). */
  onInteract: () => void = () => {};
  /** Called on a plain scroll over the view, which scrolls the page instead of zooming. */
  onScroll: () => void = () => {};

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, 2));

    this.material = new ShaderMaterial({
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      uniforms: this.uniforms,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    });
    this.scene.add(new Points(this.geometry, this.material));

    const ringGeometry = new BufferGeometry();
    ringGeometry.setAttribute("position", new BufferAttribute(new Float32Array(3), 3));
    this.ring = new Points(
      ringGeometry,
      new ShaderMaterial({
        vertexShader: RING_VERTEX,
        fragmentShader: RING,
        uniforms: this.ringUniforms,
        transparent: true,
        depthTest: false,
        depthWrite: false,
      }),
    );
    this.ring.visible = false;
    this.ring.renderOrder = 1;
    this.scene.add(this.ring);

    // A plain scroll scrolls the page past the view; a pinch (which browsers send as a wheel
    // with ctrlKey) or ⌘/Ctrl + scroll zooms. Registered first, so the controls never see it.
    canvas.addEventListener("wheel", (event) => {
      if (event.ctrlKey || event.metaKey) return;
      event.stopImmediatePropagation();
      this.onScroll();
    });
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.rotateSpeed = 0.7;
    this.controls.zoomSpeed = 0.8;
    this.controls.autoRotateSpeed = 0.8;
    this.controls.minDistance = 0.3;
    this.controls.maxDistance = 12;
    this.controls.addEventListener("start", () => {
      if (this.controls.autoRotate) {
        this.controls.autoRotate = false;
        this.onInteract();
      }
    });
    this.controls.addEventListener("change", () => {
      this.dirty = true;
    });
    this.renderer.domElement.addEventListener("webglcontextrestored", () => {
      this.dirty = true;
    });
  }

  setCloud(cloud: Cloud): void {
    this.cloud = cloud;
    this.geometry.setAttribute("position", new BufferAttribute(cloud.positions, 3));
    this.geometry.computeBoundingSphere(); // three.js culls by it
    this.sizes = sizes(cloud);
    this.geometry.setAttribute("size", new BufferAttribute(this.sizes, 1));
    this.updateTints();
    if (!this.framed) this.resetView();
    this.dirty = true;
  }

  setPalette(palette: Palette): void {
    this.palette = palette;
    this.ringUniforms.uColor.value = [...palette.foreground];
    this.updateTints();
  }

  setHighlight(cluster: number | null): void {
    this.highlight = cluster;
    this.updateTints();
  }

  /** Ring the point at `index`, or no point. */
  setMarked(index: number | null): void {
    const positions = this.cloud?.positions;
    if (index === null || !positions) {
      this.ring.visible = false;
    } else {
      const attribute = this.ring.geometry.getAttribute("position") as BufferAttribute;
      attribute.setXYZ(
        0,
        positions[index * 3] ?? 0,
        positions[index * 3 + 1] ?? 0,
        positions[index * 3 + 2] ?? 0,
      );
      attribute.needsUpdate = true;
      this.markedSize = this.sizes[index] ?? this.markedSize;
      this.ring.visible = true;
    }
    this.dirty = true;
  }

  get autoRotate(): boolean {
    return this.controls.autoRotate;
  }

  setAutoRotate(on: boolean): void {
    this.controls.autoRotate = on;
    this.dirty = true;
  }

  /** Back to the starting angle, with the whole cloud in view. */
  resetView(): void {
    this.controls.target.set(0, 0, 0);
    const home = HOME.clone();
    home.radius = fitDistance(RADIUS, this.width / this.height);
    this.camera.position.setFromSpherical(home);
    this.camera.lookAt(0, 0, 0);
    this.controls.update();
    this.framed = this.cloud !== null;
    this.dirty = true;
  }

  resize(width: number, height: number): void {
    if (width <= 0 || height <= 0) return;
    this.width = width;
    this.height = height;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    const scale = (height * this.renderer.getPixelRatio()) / (2 * Math.tan((FOV * Math.PI) / 360));
    this.uniforms.uScale.value = scale;
    if (!this.framed) this.resetView();
    this.dirty = true;
  }

  /** Draw frames while visible; stop when the view is scrolled away or hidden. */
  start(): void {
    if (this.running) return;
    this.running = true;
    this.last = performance.now();
    this.dirty = true;
    this.renderer.setAnimationLoop((time) => this.tick(time));
  }

  stop(): void {
    this.running = false;
    this.renderer.setAnimationLoop(null);
  }

  /** The point nearest to (x, y) in CSS pixels of the canvas, within `radius`; never a ghost. */
  pick(x: number, y: number, radius = 14): number | null {
    const cloud = this.cloud;
    if (!cloud) return null;
    this.camera.updateMatrixWorld();
    this.projection.multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse);
    const highlight = this.highlight;
    return nearestOnScreen(
      cloud.positions,
      this.projection.elements,
      this.width,
      this.height,
      x,
      y,
      radius,
      (i) => cloud.slots[i] !== GHOST && (highlight === null || cloud.clusters[i] === highlight),
    );
  }

  dispose(): void {
    this.stop();
    this.controls.dispose();
    this.geometry.dispose();
    this.material.dispose();
    this.ring.geometry.dispose();
    this.ring.material.dispose();
    this.renderer.dispose();
    // Browsers keep only a few WebGL contexts; give this one back now, not at collection.
    this.renderer.forceContextLoss();
  }

  private updateTints(): void {
    if (!this.cloud || !this.palette) return;
    this.geometry.setAttribute(
      "tint",
      new BufferAttribute(tints(this.cloud, this.palette, this.highlight), 4),
    );
    this.dirty = true;
  }

  private tick(time: number): void {
    const delta = Math.min((time - this.last) / 1000, 0.1);
    this.last = time;
    const moved = this.controls.update(delta);
    if (!moved && !this.dirty) return;
    this.dirty = false;
    // Fade from the near side of the cloud to its far side.
    const distance = this.camera.position.distanceTo(this.controls.target);
    this.uniforms.uDepth.value = [Math.max(distance - RADIUS, 0), distance + RADIUS];
    const size = this.markedSize;
    const scale = this.uniforms.uScale.value;
    this.ringUniforms.uSize.value = Math.max(
      16 * this.renderer.getPixelRatio(),
      (size * scale) / Math.max(distance, 0.01) + 10 * this.renderer.getPixelRatio(),
    );
    this.renderer.render(this.scene, this.camera);
    this.onFrame();
  }
}
