import forms from '@tailwindcss/forms';
import typography from '@tailwindcss/typography';

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'bg-page': '#0F0F15',
        'bg-card': '#1A1A2E',
        'bg-hover': '#2D2D4A',
        'bg-input': '#252536',
        'text-primary': '#FFFFFF',
        'text-secondary': '#E0E0E0',
        'text-tertiary': '#A0A0B0',
        'text-disabled': '#666680',
        'accent-coral': '#FF6B54',
        'accent-gold': '#D4A574',
        'accent-green': '#4CAF50',
        'accent-blue': '#87CEEB',
        'accent-amber': '#FFC107',
        coral: '#FF6B54',
        gold: '#D4A574',
      },
      fontFamily: {
        sans: ['Outfit', 'Inter', 'sans-serif'],
        display: ['DM Sans', 'Outfit', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      fontSize: {
        'display-lg': ['36px', { lineHeight: '1.2', fontWeight: '700' }],
        'display-md': ['28px', { lineHeight: '1.3', fontWeight: '600' }],
        'heading-lg': ['20px', { lineHeight: '1.4', fontWeight: '600' }],
        'heading-md': ['24px', { lineHeight: '1.4', fontWeight: '600' }],
        'body-lg': ['18px', { lineHeight: '1.6', fontWeight: '400' }],
        'body-md': ['16px', { lineHeight: '1.6', fontWeight: '400' }],
        'body-sm': ['14px', { lineHeight: '1.5', fontWeight: '400' }],
        caption: ['12px', { lineHeight: '1.4', fontWeight: '500' }],
      },
      boxShadow: {
        card: '0 4px 12px rgba(0, 0, 0, 0.3)',
        'card-hover': '0 8px 24px rgba(0, 0, 0, 0.35)',
        modal: '0 20px 60px rgba(0, 0, 0, 0.5)',
      },
      spacing: {
        xs: '4px',
        sm: '8px',
        md: '16px',
        lg: '24px',
        xl: '32px',
        xxl: '48px',
      },
      borderRadius: {
        sm: '4px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
      animation: {
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
      },
      keyframes: {
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.8' },
        },
      },
    },
  },
  plugins: [forms, typography],
};
