/**
 * Tailwind wird lokal kompiliert (kein CDN → keine Besucher-IPs an Dritte).
 * Build:  tailwindcss -i static/css/input.css -o static/css/site.css --minify
 * Im Docker-Build passiert das automatisch (siehe Dockerfile).
 */
module.exports = {
  content: [
    './templates/**/*.{html,txt}',
    './static/js/**/*.js',
    './*.py',
    './blueprints/**/*.py',
  ],
  theme: {
    extend: {
      colors: {
        neon:   '#39FF14',
        purple: '#8B2FC9',
        dark:   '#1C0D28',
        darker: '#130820',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        neon:   '0 0 8px #39FF14, 0 0 24px #39FF1440',
        purple: '0 0 8px #8B2FC9, 0 0 24px #8B2FC940',
      },
    },
  },
  plugins: [],
}
