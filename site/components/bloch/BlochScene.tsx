"use client";

import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, Line } from "@react-three/drei";

interface BlochSceneProps {
  /** Bloch polar angle, radians, 0 = |0⟩ (north pole). */
  theta: number;
  /** Bloch azimuthal angle, radians, 0 = |+⟩. */
  phi: number;
  /** Snap state changes and disable autorotate. */
  reducedMotion: boolean;
}

type Pt = [number, number, number];

const Y_UP = new THREE.Vector3(0, 1, 0);
const TAU = Math.PI * 2;

/**
 * Bloch (θ, φ) → three.js direction.
 * Bloch z (|0⟩) maps to three +y (up); Bloch x (|+⟩) to three +x;
 * Bloch y to three +z.
 */
function dirFromAngles(theta: number, phi: number): THREE.Vector3 {
  return new THREE.Vector3(
    Math.sin(theta) * Math.cos(phi),
    Math.cos(theta),
    Math.sin(theta) * Math.sin(phi),
  );
}

function quatFromAngles(theta: number, phi: number): THREE.Quaternion {
  return new THREE.Quaternion().setFromUnitVectors(
    Y_UP,
    dirFromAngles(theta, phi).normalize(),
  );
}

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

/** Wireframe sphere: latitude + longitude great-circle lines, faint white. */
function Wireframe() {
  const circles = useMemo(() => {
    const lats = [Math.PI / 6, Math.PI / 3, (2 * Math.PI) / 3, (5 * Math.PI) / 6].map(
      (t) => latitude(t),
    );
    const lons = [0, 1, 2].map((i) => meridian((i / 3) * Math.PI));
    return [...lats, ...lons];
  }, []);
  return (
    <>
      {circles.map((pts, i) => (
        <Line
          key={i}
          points={pts}
          color="#ffffff"
          lineWidth={1}
          transparent
          opacity={0.12}
        />
      ))}
    </>
  );
}

/** The phase-hue motif: equator ring, vertex colors hue-mapped to azimuth. */
function PhaseRing() {
  const { points, colors } = useMemo(() => {
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
  }, []);
  return (
    <Line
      points={points}
      vertexColors={colors}
      color="#ffffff"
      lineWidth={1.75}
      transparent
      opacity={0.55}
    />
  );
}

function Axes() {
  const axes = useMemo<Pt[][]>(
    () => [
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
    ],
    [],
  );
  return (
    <>
      {axes.map((pts, i) => (
        <Line
          key={i}
          points={pts}
          color="#ffffff"
          lineWidth={1}
          transparent
          opacity={0.18}
        />
      ))}
    </>
  );
}

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--font-plex-mono), monospace",
  fontSize: "11px",
  color: "#8a8f98",
  whiteSpace: "nowrap",
  pointerEvents: "none",
  userSelect: "none",
};

function AxisLabel({ position, text }: { position: Pt; text: string }) {
  return (
    <Html position={position} center style={labelStyle}>
      {text}
    </Html>
  );
}

const EASE_MS = 550;

/** Cyan state arrow; gate changes slerp the quaternion over ~550 ms. */
function StateArrow({ theta, phi, reducedMotion }: BlochSceneProps) {
  const group = useRef<THREE.Group>(null);
  const anim = useRef({
    from: new THREE.Quaternion(),
    to: new THREE.Quaternion(),
    start: 0,
    active: false,
  });

  useEffect(() => {
    if (!group.current) return;
    const target = quatFromAngles(theta, phi);
    if (reducedMotion) {
      group.current.quaternion.copy(target);
      anim.current.active = false;
      return;
    }
    anim.current.from.copy(group.current.quaternion);
    anim.current.to.copy(target);
    anim.current.start = performance.now();
    anim.current.active = true;
  }, [theta, phi, reducedMotion]);

  useFrame(() => {
    const a = anim.current;
    if (!a.active || !group.current) return;
    const k = Math.min(1, (performance.now() - a.start) / EASE_MS);
    const eased = 1 - Math.pow(1 - k, 3); // cubic ease-out
    group.current.quaternion.slerpQuaternions(a.from, a.to, eased);
    if (k >= 1) a.active = false;
  });

  return (
    <group ref={group}>
      <mesh position={[0, 0.39, 0]}>
        <cylinderGeometry args={[0.012, 0.012, 0.78, 12]} />
        <meshStandardMaterial
          color="#7dedff"
          emissive="#7dedff"
          emissiveIntensity={0.45}
        />
      </mesh>
      <mesh position={[0, 0.85, 0]}>
        <coneGeometry args={[0.045, 0.15, 16]} />
        <meshStandardMaterial
          color="#7dedff"
          emissive="#7dedff"
          emissiveIntensity={0.45}
        />
      </mesh>
      <mesh position={[0, 0.94, 0]}>
        <sphereGeometry args={[0.034, 16, 16]} />
        <meshStandardMaterial
          color="#7dedff"
          emissive="#7dedff"
          emissiveIntensity={1.6}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}

function SceneContents(props: BlochSceneProps) {
  const root = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (!props.reducedMotion && root.current) {
      root.current.rotation.y += delta * 0.05;
    }
  });
  return (
    <group ref={root}>
      <Wireframe />
      <PhaseRing />
      <Axes />
      <StateArrow {...props} />
      <AxisLabel position={[0, 1.3, 0]} text="|0⟩" />
      <AxisLabel position={[0, -1.32, 0]} text="|1⟩" />
      <AxisLabel position={[1.34, 0, 0]} text="|+⟩" />
    </group>
  );
}

export default function BlochScene(props: BlochSceneProps) {
  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [2.4, 1.5, 2.4], fov: 42 }}
      gl={{ antialias: true, alpha: true }}
      onCreated={({ camera }) => camera.lookAt(0, 0, 0)}
      style={{ background: "transparent" }}
    >
      <ambientLight intensity={0.65} />
      <directionalLight position={[4, 5, 2]} intensity={0.9} />
      <SceneContents {...props} />
    </Canvas>
  );
}
