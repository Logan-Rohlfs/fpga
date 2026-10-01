<script lang="ts">
  // 3D trajectory: three.js is loaded with a dynamic import so it stays out of the entry chunk. Renders on demand only
  // (data version, controls change, resize, visibility). Positions come from lib/cards/traj.ts; this file is glue.
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import type * as ThreeNS from 'three';
  import { altitudeColor, groundTiles, trackPoints, type GroundSpan } from '../lib/cards/traj';
  import { scheduler } from '../lib/frame';
  import { dataVersion, flightSchema, flightStores, hello } from '../lib/link';

  let { id, config }: { id: string; config: Record<string, unknown> } = $props();

  interface Site { id: string; name?: string; pad: [number, number] }
  const sites = $derived(($hello?.sites ?? []) as Site[]);
  const site = $derived(sites.find((s) => s.id === config.site) ?? sites[0] ?? null);
  const layer = $derived(String(config.layer ?? 'imagery'));
  const exaggeration = $derived(Number(config.exaggeration ?? 1));
  const source = $derived(String(config.source ?? 'best'));

  let host: HTMLDivElement;
  let mode = $state<'track' | 'column' | null>(null);
  let loadError = $state('');
  let ready = $state(false);

  let draw: () => void = () => {};
  let rebuildGround: () => void = () => {};
  const dirty = () => scheduler.markDirty(id);

  // Redraw when the data, the config or the site changes (the draw function itself is installed after three loads).
  $effect(() => {
    void $dataVersion; void exaggeration; void source; void site; void ready;
    dirty();
  });
  $effect(() => {
    void layer; void site; void ready;
    rebuildGround();
  });

  onMount(() => {
    let disposed = false;
    let cleanup = () => {};

    (async () => {
      let THREE: typeof ThreeNS;
      let OrbitControls: typeof import('three/examples/jsm/controls/OrbitControls.js').OrbitControls;
      try {
        THREE = await import('three');
        ({ OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js'));
      } catch (e) {
        loadError = `3D view unavailable: ${e instanceof Error ? e.message : String(e)}`;
        return;
      }
      if (disposed) return;

      let renderer: ThreeNS.WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      } catch {
        loadError = '3D view unavailable: WebGL could not start';
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      host.appendChild(renderer.domElement);
      renderer.domElement.style.display = 'block';

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(50, 1, 5, 200000);
      camera.position.set(-2500, 1800, 3500);
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.set(0, 400, 0);
      controls.update();

      const grid = new THREE.GridHelper(8000, 16, 0x888888, 0x555555);
      scene.add(grid);
      const padMarker = new THREE.Mesh(new THREE.CylinderGeometry(25, 25, 4, 16), new THREE.MeshBasicMaterial({ color: 0xffffff }));
      scene.add(padMarker);

      // Ground: canvas of z15 tiles, missing ones grey, on a plane under the track.
      const TILE_PX = 256;
      let ground: ThreeNS.Mesh | null = null;
      let groundTex: ThreeNS.CanvasTexture | null = null;
      let groundGen = 0;

      function disposeGround() {
        if (ground) {
          scene.remove(ground);
          ground.geometry.dispose();
          (ground.material as ThreeNS.Material).dispose();
          ground = null;
        }
        groundTex?.dispose();
        groundTex = null;
      }

      rebuildGround = () => {
        const gen = ++groundGen;
        disposeGround();
        if (!site) { dirty(); return; }
        const span: GroundSpan = groundTiles(site.pad);
        const cols = span.x1 - span.x0 + 1;
        const rows = span.y1 - span.y0 + 1;
        const tileM = span.sizeM / cols;
        const canvas = document.createElement('canvas');
        canvas.width = cols * TILE_PX;
        canvas.height = rows * TILE_PX;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        ctx.fillStyle = '#6b6b6b';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        const tex = new THREE.CanvasTexture(canvas);
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = 4;
        const geom = new THREE.PlaneGeometry(cols * tileM, rows * tileM);
        geom.rotateX(-Math.PI / 2);
        const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ map: tex }));
        mesh.position.set(span.originEast + (cols * tileM) / 2, -1, -(span.originNorth - (rows * tileM) / 2));
        scene.add(mesh);
        ground = mesh;
        groundTex = tex;
        for (let ty = span.y0; ty <= span.y1; ty++) {
          for (let tx = span.x0; tx <= span.x1; tx++) {
            const img = new Image();
            img.onload = () => {
              if (gen !== groundGen) return;
              ctx.drawImage(img, (tx - span.x0) * TILE_PX, (ty - span.y0) * TILE_PX, TILE_PX, TILE_PX);
              tex.needsUpdate = true;
              dirty();
            };
            img.src = `/tiles/${layer}/${span.z}/${tx}/${ty}`;
          }
        }
        dirty();
      };

      let line: ThreeNS.Line | null = null;
      let dots: ThreeNS.Points | null = null;
      function disposeTrack() {
        for (const o of [line, dots]) {
          if (!o) continue;
          scene.remove(o);
          o.geometry.dispose();
          (o.material as ThreeNS.Material).dispose();
        }
        line = null;
        dots = null;
      }

      draw = () => {
        const schema = get(flightSchema);
        const store = flightStores[source as 'best' | 'A' | 'B'] ?? flightStores.best;
        disposeTrack();
        if (schema && store.length) {
          const t = trackPoints(store, schema, site?.pad ?? [0, 0], exaggeration);
          mode = t.mode;
          const n = t.points.length / 3;
          if (n) {
            const colors = new Float32Array(n * 3);
            const top = Math.max(t.maxAlt * exaggeration, 1);
            for (let i = 0; i < n; i++) colors.set(altitudeColor(t.points[i * 3 + 1] / top), i * 3);
            const geom = new THREE.BufferGeometry();
            geom.setAttribute('position', new THREE.BufferAttribute(t.points, 3));
            geom.setAttribute('color', new THREE.BufferAttribute(colors, 3));
            line = new THREE.Line(geom, new THREE.LineBasicMaterial({ vertexColors: true }));
            scene.add(line);
            const g2 = geom.clone();
            dots = new THREE.Points(g2, new THREE.PointsMaterial({ vertexColors: true, size: 4, sizeAttenuation: false }));
            scene.add(dots);
          }
        } else {
          mode = null;
        }
        const w = host.clientWidth;
        const h = host.clientHeight;
        if (w > 0 && h > 0) {
          renderer.setSize(w, h, false);
          renderer.domElement.style.width = `${w}px`;
          renderer.domElement.style.height = `${h}px`;
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
        }
        renderer.render(scene, camera);
      };

      const unregister = scheduler.register(id, () => draw());
      const onChange = () => dirty();
      controls.addEventListener('change', onChange);
      const ro = new ResizeObserver(onChange);
      ro.observe(host);
      ready = true;
      dirty();

      cleanup = () => {
        unregister();
        controls.removeEventListener('change', onChange);
        controls.dispose();
        ro.disconnect();
        groundGen++;
        disposeGround();
        disposeTrack();
        grid.geometry.dispose();
        (grid.material as ThreeNS.Material).dispose();
        padMarker.geometry.dispose();
        (padMarker.material as ThreeNS.Material).dispose();
        renderer.dispose();
        renderer.domElement.remove();
        draw = () => {};
        rebuildGround = () => {};
      };
    })();

    return () => {
      disposed = true;
      cleanup();
    };
  });
</script>

<div class="traj">
  <div class="host" bind:this={host}></div>
  {#if loadError}
    <p class="note msg">{loadError}</p>
  {:else if !ready}
    <p class="note msg">Loading 3D view</p>
  {:else if mode === 'column'}
    <p class="note badge">Horizontal position unknown (GPS invalid)</p>
  {:else if mode === null}
    <p class="note badge">No flight data yet</p>
  {/if}
  {#if ready && !site}<p class="note badge low">No site registry entry: ground is not drawn</p>{/if}
</div>

<style>
  .traj { position: relative; height: 100%; min-height: 0; overflow: hidden; }
  .host { position: absolute; inset: 0; }
  .msg { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; padding: 12px; }
  .badge { position: absolute; top: 6px; left: 8px; padding: 2px 6px; border-radius: 4px; background: color-mix(in srgb, var(--bg, #000) 70%, transparent); pointer-events: none; }
  .badge.low { top: auto; bottom: 6px; }
</style>
