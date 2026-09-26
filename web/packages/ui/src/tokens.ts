/**
 * Aegis Sovereign Luxury Design Tokens
 * 
 * Dark Obsidian & Champagne Gold Architectural Aesthetic
 * Built for ultra-high-precision private enterprise intelligence portals.
 */

export const tokens = {
  colors: {
    bg: {
      base: '#07090D',
      obsidian: '#0B0F17',
      surface: '#0E121A',
      card: '#141A24',
      elevated: '#1A2230',
      glass: 'rgba(14, 18, 26, 0.85)',
      paper: '#FAFAFA',
    },
    border: {
      subtle: '#1C2330',
      default: '#232B38',
      active: '#38455A',
      gold: 'rgba(212, 175, 55, 0.35)',
      goldActive: '#D4AF37',
    },
    gold: {
      DEFAULT: '#D4AF37',
      bright: '#F3E5AB',
      muted: '#A6882C',
      dim: '#6D591B',
      glow: 'rgba(212, 175, 55, 0.15)',
      glowHeavy: 'rgba(212, 175, 55, 0.35)',
      gradient: 'linear-gradient(135deg, #D4AF37 0%, #997A15 100%)',
    },
    emerald: {
      DEFAULT: '#10B981',
      bright: '#00E676',
      dim: '#065F46',
      bg: 'rgba(0, 230, 118, 0.08)',
      border: 'rgba(0, 230, 118, 0.3)',
      glow: 'rgba(0, 230, 118, 0.25)',
    },
    danger: {
      DEFAULT: '#FF5252',
      dim: '#7F1D1D',
      bg: 'rgba(255, 82, 82, 0.10)',
      border: 'rgba(255, 82, 82, 0.4)',
    },
    warning: {
      DEFAULT: '#FFA726',
      dim: '#78350F',
      bg: 'rgba(255, 167, 38, 0.10)',
      border: 'rgba(255, 167, 38, 0.4)',
    },
    text: {
      primary: '#E6EDF3',
      secondary: '#8B949E',
      tertiary: '#545D68',
      gold: '#F3E5AB',
      emerald: '#00E676',
      dark: '#111827',
    },
  },
  typography: {
    fonts: {
      heading: "'Cinzel', Georgia, serif",
      body: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
      mono: "'JetBrains Mono', SFMono-Regular, monospace",
    },
    letterSpacing: {
      tight: '-0.02em',
      normal: '0',
      wide: '0.05em',
      wider: '0.1em',
      widest: '0.15em',
    },
  },
  shadows: {
    card: '0 4px 20px rgba(0, 0, 0, 0.4)',
    goldGlow: '0 0 16px rgba(212, 175, 55, 0.20)',
    goldGlowHeavy: '0 0 28px rgba(212, 175, 55, 0.40)',
    emeraldGlow: '0 0 16px rgba(0, 230, 118, 0.25)',
    dangerGlow: '0 0 16px rgba(255, 82, 82, 0.25)',
    paper: '0 10px 40px rgba(0, 0, 0, 0.7)',
  },
  animation: {
    pulseSlow: 'pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
    shimmer: 'shimmer 2s infinite linear',
  },
} as const;

export type DesignTokens = typeof tokens;
