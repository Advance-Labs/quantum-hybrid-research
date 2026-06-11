"use client";

import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { Line, PerspectiveCamera, View } from "@react-three/drei";
import { usePrefersReducedMotion } from "./useReducedMotion";

/**
 * Reusable Bloch sphere as a drei `<View>` — must live under `<SharedCanvas>`.
 *
 * Visual vocabulary mirrors `components/bloch/BlochScene.tsx` (wireframe
 * lat/long great circles at white 10–14%, phase-hue equator ring, cyan
 * #7DEDFF arrow with glowing tip dot, mono pole labels), parameterized by a
 * Bloch vector {x, y, z, r} from `engine.reducedBloch`.
 *
 * Arrow length = r: as a qubit entangles, its reduced Bloch vector shrinks
 * toward the center — a Bell pair leaves only the glowing dot at the origin.
 * That degeneration IS the chapter-4 lesson (research doc 04 §5.2, §6.1#3).
 *
 * Direction (slerp) and length (lerp) tween over ~550 ms cubic ease-out;
 * both snap under prefers-reduced-motion, which also disables autorotate.
 * Geometries, materials, and polyline points are module-level constants so
 * 6+ simultaneous instances stay cheap.
 */
export interface BlochViewProps {
  /** Reduced Bloch vector, from engine.reducedBloch: unit ball, r = ‖(x,y,z)‖. */
  bloch: { x: number; y: number; z: number; r: number };
  /** Square view size in px. Default 220. */
  size?: number;
  /** Mono caption rendered under the view, e.g. "qubit 0". */
  label?: string;
  /** Slow y-axis rotation. Default true; forced off under reduced motion. */
  autorotate?: boolean;
  className?: string;
}

type Pt = [number, number, number];

const TAU = Math.PI * 2;
const Y_UP = new THREE.Vector3(0, 1, 0);
const EASE_MS = 550;

/* ------------------------------------------------------------------ */
/* Shared, module-level scene constants (built once for all instances) */
/* ------------------------------------------------------------------ */

function latitude(theta: number, segments = 96): Pt[] {
  const r = Math.sin(theta);
  const y = Math.cos(theta);
  const pts: Pt[] = [];
  for (let i = 0; i <= segments; i++) {
    const a = (i / segments) * TAU;
    pts.push([r * Math.cos(a), y, r * Math.sin(a)]);
  }
  return pts;
}

function meridian(phi: number, segments = 96): Pt[] {
  const pts: Pt[] = [];
  for (let i = 0; i <= segments; i++) {
    const t = (i / segments) * TAU;
    pts.push([
      Math.sin(t) * Math.cos(phi),
      Math.cos(t),
      Math.sin(t) * Math.sin(phi),
    ]);
  }
  return pts;
}

/** Wireframe lat/long great circles — same lattice as BlochScene. */
const WIREFRAME_CIRCLES: Pt[][] = [
  ...[Math.PI / 6, Math.PI / 3, (2 * Math.PI) / 3, (5 * Math.PI) / 6].map(
    (t) => latitude(t),
  ),
  ...[0, 1, 2].map((i) => meridian((i / 3) * Math.PI)),
];

const AXES_LINES: Pt[][] = [
  [
    [-1.18, 0, 0],
    [1.18, 0, 0],
  ],
  [
    [0, -1.18, 0],
    [0, 1.18, 0],
  ],
  [
    [0, 0, -1.18],
    [0, 0, 1.18],
  ],
];

/** Phase-hue equator ring: vertex colors hue-mapped to azimuth. */
const PHASE_RING: { points: Pt[]; colors: Pt[] } = (() => {
  const N = 160;
  const pts: Pt[] = [];
  const cols: Pt[] = [];
  const c = new THREE.Color();
  for (let i = 0; i <= N; i++) {
    const a = (i / N) * TAU;
    pts.push([Math.cos(a), 0, Math.sin(a)]);
    c.setHSL(a / TAU, 0.8, 0.65);
    cols.push([c.r, c.g, c.b]);
  }
  return { points: pts, colors: cols };
})();

/* Arrow geometry/material — shared across all instances and meshes. */
const SHAFT_GEOMETRY = new THREE.CylinderGeometry(0.012, 0.012, 0.78, 12);
const CONE_GEOMETRY = new THREE.ConeGeometry(0.045, 0.15, 16);
const TIP_GEOMETRY = new THREE.SphereGeometry(0.034, 16, 16);

const ARROW_MATERIAL = new THREE.MeshStandardMaterial({
  color: "#7dedff",
  emissive: "#7dedff",
  emissiveIntensity: 0.45,
});
const TIP_MATERIAL = new THREE.MeshStandardMaterial({
  color: "#7dedff",
  emissive: "#7dedff",
  emissiveIntensity: 1.6,
  toneMapped: false,
});

/* ------------------------------------------------------------------ */
/* Scene pieces                                                        */
/* ------------------------------------------------------------------ */

function Lattice() {
  return (
    <>
      {WIREFRAME_CIRCLES.map((pts, i) => (
        <Line
          key={`w${i}`}
          points={pts}
          color="#ffffff"
          lineWidth={1}
          transparent
          opacity={0.12}
        />
      ))}
      {AXES_LINES.map((pts, i) => (
        <Line
          key={`a${i}`}
          points={pts}
          color="#ffffff"
          lineWidth={1}
          transparent
          opacity={0.18}
        />
      ))}
      <Line
        points={PHASE_RING.points}
        vertexColors={PHASE_RING.colors}
        color="#ffffff"
        lineWidth={1.75}
        transparent
        opacity={0.55}
      />
    </>
  );
}

/**
 * Bloch (x, y, z) → three.js direction. Bloch z (|0⟩) maps to three +y
 * (up); Bloch x (|+⟩) to three +x; Bloch y to three +z — same convention
 * as BlochScene's dirFromAngles.
 */
function dirFromBloch(b: { x: number; y: number; z: number }): THREE.Vector3 {
  return new THREE.Vector3(b.x, b.z, b.y);
}

interface ArrowAnim {
  fromQ: THREE.Quaternion;
  toQ: THREE.Quaternion;
  fromL: number;
  toL: number;
  start: number;
  active: boolean;
  curL: number;
  lastDir: THREE.Vector3;
  mounted: boolean;
}

/**
 * Cyan state arrow of length r ∈ [0, 1]. The shaft stretches with r, the
 * cone head shrinks smoothly near the center, and the glowing tip dot is
 * always drawn — at r = 0 (maximal entanglement) only the dot remains.
 */
function StateArrow({
  bloch,
  reducedMotion,
}: {
  bloch: BlochViewProps["bloch"];
  reducedMotion: boolean;
}) {
  const group = useRef<THREE.Group>(null);
  const shaft = useRef<THREE.Mesh>(null);
  const cone = useRef<THREE.Mesh>(null);
  const tip = useRef<THREE.Mesh>(null);

  const anim = useRef<ArrowAnim>({
    fromQ: new THREE.Quaternion(),
    toQ: new THREE.Quaternion(),
    fromL: 1,
    toL: 1,
    start: 0,
    active: false,
    curL: 1,
    lastDir: new THREE.Vector3(0, 1, 0),
    mounted: false,
  });

  const applyLength = (l: number) => {
    const len = Math.max(0, Math.min(1, l));
    anim.current.curL = len;
    const headScale = Math.min(1, len * 1.6);
    if (shaft.current) {
      shaft.current.visible = len > 0.02;
      shaft.current.scale.set(1, Math.max(len, 1e-4), 1);
      shaft.current.position.y = 0.39 * len;
    }
    if (cone.current) {
      cone.current.visible = headScale > 0.02;
      cone.current.scale.setScalar(Math.max(headScale, 1e-4));
      cone.current.position.y = 0.78 * len + 0.07 * headScale;
    }
    if (tip.current) {
      tip.current.position.y = 0.78 * len + 0.15 * headScale + 0.015;
    }
  };

  useEffect(() => {
    const a = anim.current;
    if (!group.current) return;

    const dir = dirFromBloch(bloch);
    if (dir.lengthSq() > 1e-12) {
      a.lastDir.copy(dir.normalize());
    } // else: direction undefined at the center — keep the last heading.
    const targetQ = new THREE.Quaternion().setFromUnitVectors(Y_UP, a.lastDir);
    const targetL = Math.max(0, Math.min(1, bloch.r));

    if (reducedMotion || !a.mounted) {
      // Snap: reduced motion always; first paint so views don't all swing in.
      group.current.quaternion.copy(targetQ);
      applyLength(targetL);
      a.active = false;
      a.mounted = true;
      return;
    }
    a.fromQ.copy(group.current.quaternion);
    a.toQ.copy(targetQ);
    a.fromL = a.curL;
    a.toL = targetL;
    a.start = performance.now();
    a.active = true;
  }, [bloch.x, bloch.y, bloch.z, bloch.r, reducedMotion]); // eslint-disable-line react-hooks/exhaustive-deps

  useFrame(() => {
    const a = anim.current;
    if (!a.active || !group.current) return;
    const k = Math.min(1, (performance.now() - a.start) / EASE_MS);
    const eased = 1 - Math.pow(1 - k, 3); // cubic ease-out
    group.current.quaternion.slerpQuaternions(a.fromQ, a.toQ, eased);
    applyLength(a.fromL + (a.toL - a.fromL) * eased);
    if (k >= 1) a.active = false;
  });

  return (
    <group ref={group}>
      <mesh ref={shaft} geometry={SHAFT_GEOMETRY} material={ARROW_MATERIAL} />
      <mesh ref={cone} geometry={CONE_GEOMETRY} material={ARROW_MATERIAL} />
      <mesh ref={tip} geometry={TIP_GEOMETRY} material={TIP_MATERIAL} />
    </group>
  );
}

function SphereContents({
  bloch,
  autorotate,
  reducedMotion,
}: {
  bloch: BlochViewProps["bloch"];
  autorotate: boolean;
  reducedMotion: boolean;
}) {
  const root = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (autorotate && !reducedMotion && root.current) {
      root.current.rotation.y += delta * 0.05;
    }
  });
  return (
    <group ref={root}>
      <Lattice />
      <StateArrow bloch={bloch} reducedMotion={reducedMotion} />
    </group>
  );
}

/* ------------------------------------------------------------------ */
/* Public component                                                    */
/* ------------------------------------------------------------------ */

const poleLabelClass =
  "pointer-events-none absolute left-1/2 -translate-x-1/2 select-none font-mono text-[11px] text-muted";

export default function BlochView({
  bloch,
  size = 220,
  label,
  autorotate = true,
  className,
}: BlochViewProps) {
  const reducedMotion = usePrefersReducedMotion();
  const dims = useMemo(
    () => ({ width: size, height: size }),
    [size],
  );

  return (
    <figure
      className={`flex flex-col items-center gap-2 ${className ?? ""}`}
      style={{ maxWidth: "100%" }}
    >
      <div className="relative overflow-hidden" style={dims} aria-hidden>
        <View style={dims}>
          <PerspectiveCamera
            makeDefault
            fov={42}
            position={[2.4, 1.5, 2.4]}
            onUpdate={(c) => c.lookAt(0, 0, 0)}
          />
          <ambientLight intensity={0.65} />
          <directionalLight position={[4, 5, 2]} intensity={0.9} />
          <SphereContents
            bloch={bloch}
            autorotate={autorotate}
            reducedMotion={reducedMotion}
          />
        </View>
        {/* Pole labels: the y axis is invariant under autorotate, so plain
            DOM overlays stay correct and cost nothing per frame. */}
        <span className={poleLabelClass} style={{ top: "1%" }}>
          |0⟩
        </span>
        <span className={poleLabelClass} style={{ bottom: "9%" }}>
          |1⟩
        </span>
      </div>
      {label && (
        <figcaption className="font-mono text-[11px] text-muted">
          {label}
        </figcaption>
      )}
    </figure>
  );
}
