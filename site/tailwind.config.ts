import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif']
      },
      colors: {
        ink: 'rgb(var(--color-ink) / <alpha-value>)',
        paper: 'rgb(var(--color-paper) / <alpha-value>)',
        moss: 'rgb(var(--color-moss) / <alpha-value>)',
        clay: 'rgb(var(--color-clay) / <alpha-value>)',
        cobalt: 'rgb(var(--color-cobalt) / <alpha-value>)',
        graphite: 'rgb(var(--color-graphite) / <alpha-value>)'
      },
      boxShadow: {
        panel: '0 24px 80px rgba(16, 16, 15, 0.12)'
      }
    }
  },
  plugins: []
} satisfies Config;
