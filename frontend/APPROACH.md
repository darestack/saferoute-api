# SafeRoute Frontend Approach

## Goal
Build a modern, conversion-optimized frontend for SafeRoute that establishes the "backend for static websites" positioning and drives signups for the dashboard.

---

## Stack & Hosting

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Pages** | Static HTML + vanilla JS | No build step, works on GitHub Pages, fast iteration |
| **Styling** | Tailwind CSS via CDN | Modern utility-first CSS, no build required, easy theming |
| **Fonts** | Space Grotesk + Inter (Google Fonts) | Distinctive display font, clean body font |
| **Icons** | Inline SVG | Zero dependencies, full control |
| **Hosting** | GitHub Pages | Free, static-friendly, automatic deploys from main |
| **Charts** | Chart.js (via CDN) | Lightweight analytics for dashboard |
| **Auth** | Supabase JS client | Reuses existing Supabase auth |

---

## Design Direction

### Aesthetic: "Mission Control" Dark Theme
- **Dark-first** with near-black backgrounds (`#0a0e17`, `#0f172a`)
- **Accent colors**: Emerald green (`#10b981`) + Cyan (`#06b6d4`)
- **Typography**: Space Grotesk for headings, Inter for body
- **Visual metaphor**: Security operations center / mission control

### Differentiation from Competitors
| Competitor | Typical Look | SafeRoute Approach |
|------------|-------------|-------------------|
| Formspree | Generic SaaS, light/dark | Dark-first, security aesthetic |
| StaticForms | Minimal, developer-focused | Polished but technical |
| Web3Forms | Open-source, basic | Premium feel with trust signals |

### 2026 Design Trends Applied
1. **Calm Design** — Reduced cognitive load, whitespace as functional tool
2. **Bento Grid Layouts** — Apple-inspired card grids for features
3. **Micro-interactions** — Subtle hover states, animated counters, pulse indicators
4. **Dark Mode First** — Primary design surface, not an afterthought
5. **Functional Motion** — Animations that communicate status, not decoration

---

## Site Structure

```
frontend/
├── src/
│   ├── main.ts              # Homepage entry
│   ├── dashboard.ts         # Dashboard SPA entry
│   ├── login.ts             # Login page logic
│   ├── callback.ts          # OAuth callback handler
│   ├── components/
│   │   ├── DashboardShell.ts    # UI state, modals, notifications
│   │   ├── DashboardCharts.ts   # Chart.js initialization
│   │   └── DashboardTables.ts   # Routes, logs, payments tables
│   ├── lib/
│   │   ├── api.ts           # Typed fetch wrapper with JSON-safe parsing
│   │   ├── auth.ts          # Token management utilities
│   │   └── router.ts        # Hash-based SPA router
│   ├── types/
│   │   ├── index.ts         # TypeScript interfaces
│   │   └── chart.d.ts       # Chart.js global type declaration
│   └── global.css           # Custom animations, utilities
├── public/
│   └── images/              # Static assets (logo, favicon)
├── tests/                   # Playwright E2E tests
├── index.html               # Marketing homepage
├── dashboard.html           # App dashboard (authenticated)
├── login.html               # Auth entry point
├── auth/
│   └── callback.html        # OAuth callback handler
├── docs/
│   └── api.md               # API reference
├── package.json             # Vite + TypeScript + Playwright
├── tsconfig.json            # Strict TypeScript config
└── vite.config.ts           # Multi-page Vite build config
```

---

## Pages

### 1. Homepage (`index.html`)
**Purpose**: Convert visitors to dashboard users

**Sections**:
- Hero with animated gradient orbs
- Stats bar (uptime, latency, encryption, compliance)
- Features bento grid (Spam Shield, Secret Masking, Form Validation, Manual Replay, Webhook Logs)
- How It Works (3 steps)
- Security score visualization
- Pricing (Free/Starter/Builder/Agency credit packs)
- CTA throughout

**SEO**:
- Title: "SafeRoute - Backend for Static Websites | Secure Form Handling & Webhook Routing"
- Meta description, OG tags, Twitter cards
- Semantic HTML5 elements
- Structured data (JSON-LD) for organization/software

### 2. Dashboard (`dashboard.html`)
**Purpose**: Self-service route management

**Layout**:
- Fixed sidebar navigation
- Top bar with user menu
- Main content area with:
  - Stats cards (requests, success rate, avg response, spam blocked)
  - Request volume chart
  - Response status donut
  - Recent activity table
  - Quick actions (create route, replay, delete)

**Interactions**:
- Animated stat counters on load
- Hover states on all interactive elements
- Toast notifications for actions
- Loading skeletons for async data

### 3. Login (`login.html`)
**Purpose**: Auth entry point

**Flow**:
- OAuth via Supabase (Google, GitHub)
- Backend-verified session
- Redirect to dashboard on success
- Auto-redirects to dashboard if already authenticated

---

## Brand & Visual Identity

### Color Palette
```css
--safe-bg: #0a0e17;        /* Near-black background */
--safe-surface: #0f172a;   /* Elevated surfaces */
--safe-card: #1e293b;      /* Card backgrounds */
--safe-border: #334155;    /* Subtle borders */
--safe-accent: #10b981;    /* Emerald green - primary action */
--safe-accent2: #06b6d4;   /* Cyan - secondary accent */
--safe-text: #f8fafc;      /* Primary text */
--safe-muted: #94a3b8;     /* Secondary text */
--safe-danger: #f43f5e;    /* Error states */
--safe-warning: #f59e0b;   /* Warning states */
```

### Typography Scale
- Display: Space Grotesk (headings, stats)
- Body: Inter (UI text, forms)
- Mono: System monospace (code snippets)

### Motion Design
- **Float animation**: 6s ease-in-out infinite (hero orbs)
- **Glow animation**: 2s alternate (CTA buttons)
- **Fade in**: 0.6s ease-out (section reveals)
- **Slide in**: 0.4s ease-out (toast notifications)
- **Counter animation**: 1s ease-out (stat counters)

---

## Security Considerations

1. **No secrets in frontend** — All API keys stay server-side
2. **CSP headers** — Set by Vercel/Netlify, restrict inline scripts
3. **Supabase RLS** — All data access filtered by user_id
4. **JWT in localStorage** — Acceptable for SPA; consider httpOnly cookies for higher security
5. **XSS prevention** — All user content escaped, no innerHTML with untrusted data

---

## Performance Targets

| Metric | Target | Approach |
|--------|--------|----------|
| First Contentful Paint | < 1.5s | Minimal CSS, system fonts fallback |
| Time to Interactive | < 3s | No JS frameworks, vanilla only |
| Lighthouse SEO | 100 | Semantic HTML, meta tags, structured data |
| Lighthouse Accessibility | 95+ | ARIA labels, focus states, color contrast |
| Lighthouse Best Practices | 95+ | HTTPS, no console errors |

---

## Current Status

### Completed
- `index.html` — Marketing homepage with hero, stats, bento features grid, how-it-works, credit-based pricing, and CTA sections
- `dashboard.html` — Authenticated dashboard with sidebar, stats cards, routes/logs tables, create-route modal, Chart.js visualizations
- `login.html` — OAuth entry point with Google and GitHub sign-in, auto-redirect for existing sessions
- `auth/callback.html` — OAuth callback handler with popup close and parent redirect
- `src/main.ts` — Homepage interactions (scroll animations, smooth scroll)
- `src/dashboard.ts` — Dashboard wired to real `/v1/*` API endpoints with Chart.js charts, XSS fixes, error handling improved
- `src/login.ts` — Login page OAuth logic extracted from inline script
- `src/callback.ts` — OAuth callback handler extracted from inline script
- `src/lib/api.ts` — Typed fetch wrapper with JSON-safe parsing
- `src/lib/auth.ts` — Token management utilities
- `src/lib/router.ts` — Hash-based SPA router
- `src/components/` — Modular dashboard components (shell, charts, tables)
- `src/types/` — TypeScript interfaces and type declarations
- `src/global.css` — Custom animations and utilities
- `docs/reference/api.md` — API reference covering all endpoints, Spam Shield, Turnstile, error codes, credit-based rate limits
- `.github/workflows/frontend.yml` — GitHub Pages deployment workflow with Vite build
- Playwright E2E tests implemented and passing

### Remaining
1. **Logs/stats population**: Fetch real webhook logs and route stats from API
2. **Route config UI**: Add full route editing (webhook secret, transform, spam/Turnstile settings)
3. **Webhook retry UI**: Add dashboard buttons to retry failed deliveries

---

## Out of Scope (Future)

- Multi-language support (i18n)
- Advanced analytics dashboards
- Mobile native apps
- Offline mode
- WebSocket real-time updates
