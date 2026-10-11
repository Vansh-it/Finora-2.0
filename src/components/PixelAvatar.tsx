import { useMemo } from 'react';

// ---------------------------------------------------------------------------
// PixelAvatar
//
// Draws a deterministic pixel-art character from an identity string (email or
// name). The same identity always produces the same character — no network, no
// storage, no randomness at render time. Pure SVG so it stays crisp at any size.
// ---------------------------------------------------------------------------

const GRID = 9;   // odd → perfectly mirror-symmetric
const HALF = 5;   // unique columns (0..4), the rest mirror across the centre

interface Palette {
  bg: string;
  base: string;
  shade: string;
  accent: string;
}

// Distinct, dark-theme-friendly character palettes. The first one is Finora's
// signature orange so a good share of users land on-brand.
const PALETTES: Palette[] = [
  { bg: '#1d1410', base: '#ff6b00', shade: '#c2410c', accent: '#ffd9a8' },
  { bg: '#101822', base: '#38bdf8', shade: '#0c4a6e', accent: '#c7f0ff' },
  { bg: '#141d16', base: '#34d399', shade: '#065f46', accent: '#c9f7e4' },
  { bg: '#1c1424', base: '#a78bfa', shade: '#5b21b6', accent: '#e5dbff' },
  { bg: '#231018', base: '#f472b6', shade: '#9d174d', accent: '#ffd9ec' },
  { bg: '#221a10', base: '#fbbf24', shade: '#92400e', accent: '#fff0c2' },
  { bg: '#101c22', base: '#22d3ee', shade: '#155e75', accent: '#ccf7ff' },
  { bg: '#1b1414', base: '#f87171', shade: '#991b1b', accent: '#ffd7d7' },
];

function hashSeed(input: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** tone: 0 = empty, 1 = base, 2 = shade, 3 = accent */
function buildCharacter(seed: string): { palette: Palette; grid: Int8Array } {
  const rand = mulberry32(hashSeed(seed || 'finora'));
  const palette = PALETTES[Math.floor(rand() * PALETTES.length)] ?? PALETTES[0];
  const grid = new Int8Array(GRID * GRID);

  for (let r = 0; r < GRID; r++) {
    // Denser torso, lighter crown — reads as a little character.
    const density = r <= 1 ? 0.32 : r >= 6 ? 0.72 : 0.55;
    for (let c = 0; c < HALF; c++) {
      const roll = rand();
      let tone = 0;
      if (roll < density) tone = roll < density * 0.3 ? 2 : 1;
      grid[r * GRID + c] = tone;
      grid[r * GRID + (GRID - 1 - c)] = tone;
    }
  }

  // A deterministic face: two eyes and a mouth, always symmetric.
  const eyeRow = 2 + Math.floor(rand() * 2);        // 2 or 3
  const eyeCol = 2 + Math.floor(rand() * 2);        // 2 or 3
  grid[eyeRow * GRID + eyeCol] = 3;
  grid[eyeRow * GRID + (GRID - 1 - eyeCol)] = 3;

  const mouthRow = Math.min(GRID - 2, eyeRow + 3);
  grid[mouthRow * GRID + 2] = 1;
  grid[mouthRow * GRID + (GRID - 2)] = 1;

  return { palette, grid };
}

export function PixelAvatar({ seed, size = 64, className }: { seed: string; size?: number; className?: string }) {
  const { palette, grid } = useMemo(() => buildCharacter(seed), [seed]);
  const fillFor = (tone: number) => (tone === 1 ? palette.base : tone === 2 ? palette.shade : tone === 3 ? palette.accent : null);

  return (
    <span
      className={className}
      style={{
        display: 'inline-flex',
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.28),
        padding: Math.max(2, Math.round(size * 0.07)),
        background: `radial-gradient(120% 120% at 30% 0%, ${palette.base}22, ${palette.bg})`,
        border: '1px solid rgba(255,255,255,0.14)',
        boxShadow: `inset 0 1px 0 rgba(255,255,255,0.08), 0 8px 22px ${palette.base}22`,
      }}
    >
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${GRID} ${GRID}`}
        shapeRendering="crispEdges"
        role="img"
        aria-label="Pixel character avatar"
        style={{ display: 'block', imageRendering: 'pixelated' }}
      >
        {Array.from({ length: GRID * GRID }, (_, i) => {
          const fill = fillFor(grid[i]);
          if (!fill) return null;
          const r = Math.floor(i / GRID);
          const c = i % GRID;
          return <rect key={i} x={c} y={r} width={1} height={1} fill={fill} />;
        })}
      </svg>
    </span>
  );
}

export default PixelAvatar;
