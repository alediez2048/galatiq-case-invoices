/**
 * Decorative green wave mesh for the empty-workspace introduction only. Geometry follows
 * the approved mockup. The slow drift animation is CSS-only and switched off under
 * prefers-reduced-motion (see app.css).
 */
const HORIZONTAL = Array.from({ length: 22 }, (_, i) => 30 + i * 7);
const VERTICAL = Array.from({ length: 25 }, (_, i) => i * 29);

export function WaveMesh() {
  return (
    <svg
      className="wave-mesh"
      viewBox="0 0 650 230"
      fill="none"
      aria-hidden="true"
      focusable="false"
      data-testid="wave-mesh"
    >
      <defs>
        <linearGradient id="wave-fade">
          <stop stopColor="#009a6c" stopOpacity="0" />
          <stop offset=".5" stopColor="#009a6c" />
          <stop offset="1" stopColor="#009a6c" stopOpacity=".2" />
        </linearGradient>
      </defs>
      <g className="wave-mesh__drift">
        {HORIZONTAL.map((y) => (
          <path
            key={`h${y}`}
            d={`M0 ${y + 50} C150 ${y - 150} 290 ${y + 180} 450 ${y - 20} S590 ${y - 50} 700 ${y + 30}`}
            stroke="url(#wave-fade)"
            strokeWidth=".65"
          />
        ))}
        {VERTICAL.map((x) => (
          <path
            key={`v${x}`}
            d={`M${x} 0 Q${x - 100} 95 ${x + 30} 240`}
            stroke="#009a6c"
            strokeOpacity=".18"
            strokeWidth=".6"
          />
        ))}
      </g>
    </svg>
  );
}
