"use client";

import { useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { View } from "@react-three/drei";

/**
 * One-canvas / many-views architecture (research doc 04 §3, drei `View`).
 *
 * A single fixed, pointer-events-none WebGL canvas sits behind the page
 * content; every `<BlochView>` (or any other drei `<View>`) anywhere in the
 * DOM below this component renders into it via `gl.scissor` segmentation.
 * Pointer events are sourced from the content container (`eventSource`) so
 * 3D interaction still works even though the canvas itself ignores events.
 *
 * Usage (chapters never touch `Canvas`):
 *
 *   <SharedCanvas className="relative">
 *     ...any DOM, with <BlochView .../> wherever a sphere is needed...
 *   </SharedCanvas>
 */
export default function SharedCanvas({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null!);
  return (
    <div ref={container} className={className ?? "relative"}>
      {children}
      <Canvas
        aria-hidden
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
        eventSource={container}
        eventPrefix="client"
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
          overflow: "hidden",
        }}
      >
        <View.Port />
      </Canvas>
    </div>
  );
}
