"use client";

import SharedCanvas from "@/components/three/SharedCanvas";
import Ch1Qubit from "@/components/learn/chapters/Ch1Qubit";
import Ch2Interference from "@/components/learn/chapters/Ch2Interference";
import Ch3Playground from "@/components/learn/chapters/Ch3Playground";
import Ch4Entanglement from "@/components/learn/chapters/Ch4Entanglement";
import Ch5Measurement from "@/components/learn/chapters/Ch5Measurement";

/**
 * The five-chapter body of /learn under ONE SharedCanvas (EXPLAINER-DESIGN
 * §7): a single fixed WebGL canvas serves every BlochView on the page via
 * drei View scissoring. Chapters are self-contained (zero props) and own
 * their state, copy, callouts, and aria-live regions.
 *
 * This module is loaded via next/dynamic ssr:false from ChaptersIsland so
 * three.js never executes on the server.
 */
export default function Chapters() {
  return (
    <SharedCanvas className="relative">
      <Ch1Qubit />
      <Ch2Interference />
      <Ch3Playground />
      <Ch4Entanglement />
      <Ch5Measurement />
    </SharedCanvas>
  );
}
