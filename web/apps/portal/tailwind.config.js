/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
    '../../packages/ui/src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        obsidian: {
          base: '#07090D',
          dark: '#0B0F17',
          surface: '#0E121A',
          card: '#141A24',
          elevated: '#1A2230',
        },
        border: {
          subtle: '#1C2330',
          DEFAULT: '#232B38',
          active: '#38455A',
        },
        gold: {
          DEFAULT: '#D4AF37',
          bright: '#F3E5AB',
          muted: '#A6882C',
          dim: '#6D591B',
        },
        emerald: {
          DEFAULT: '#10B981',
          bright: '#00E676',
        },
        danger: {
          DEFAULT: '#FF5252',
        },
        warning: {
          DEFAULT: '#FFA726',
        },
      },
      fontFamily: {
        serif: ['var(--font-cinzel)', 'Cinzel', 'Georgia', 'serif'],
        sans: ['var(--font-inter)', 'Inter', '-apple-system', 'sans-serif'],
        mono: ['var(--font-jetbrains)', 'JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        gold: '0 0 16px rgba(212, 175, 55, 0.20)',
        'gold-heavy': '0 0 28px rgba(212, 175, 55, 0.40)',
        emerald: '0 0 16px rgba(0, 230, 118, 0.25)',
        danger: '0 0 16px rgba(255, 82, 82, 0.25)',
        paper: '0 10px 40px rgba(0, 0, 0, 0.7)',
      },
      keyframes: {
        shimmer: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        shimmer: 'shimmer 2s infinite linear',
      },
    },
  },
  plugins: [],
};
