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
        ink: '#10100f',
        paper: '#f7f2e8',
        moss: '#52664b',
        clay: '#a46a4d',
        cobalt: '#2f5f9e',
        graphite: '#272a2f'
      },
      boxShadow: {
        panel: '0 24px 80px rgba(16, 16, 15, 0.12)'
      }
    }
  },
  plugins: []
} satisfies Config;
