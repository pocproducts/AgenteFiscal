# Design: Complete Landing Page Quality Upgrade

## Technical Approach

All changes are targeted modifications to existing components. No new files, no new dependencies. Changes grouped into 3 priority batches.

### Batch P0 (Visual Parity)
Apply across all 16 component files + page.tsx + globals.css — systematic find-and-replace/add patterns:

| Change | Pattern | Scope |
|--------|---------|-------|
| `font-display` on headings | Add class to all h1/h2/h3 title elements | 11 sections |
| Scroll-in animation | IntersectionObserver + state toggle + transition classes | All sections |
| `noise-overlay` on main | Add class to `<main>` element | `page.tsx` |
| `scroll-behavior: smooth` | CSS on html | `globals.css` |
| Nav scroll behavior | Add scroll state for position/rounded/height | `navigation.tsx` |
| Hero sphere absolute | Move sphere from flex sibling to absolute positioned | `hero-section.tsx` |
| Eyebrow line-style | Replace pill badges with `w-8 h-px` | All sections |
| Canvas colors | Add `className` prop passthrough to canvas wrappers | `animated-*.tsx` |

### Batch P1 (Polish)
| Change | Approach | Scope |
|--------|----------|-------|
| Fluid hero font | Replace Tailwind breakpoints with `clamp()` | `hero-section.tsx` |
| Tetrahedron Z-axis | Add Z rotation to animation loop | `animated-tetrahedron.tsx` |
| Code line numbers | Add line number column to code blocks | `developers-section.tsx`, `how-it-works-section.tsx` |
| Full-width marquees | Move marquee containers outside `max-w-7xl` | `integrations-section.tsx`, `testimonials-section.tsx` |
| Footer social hover | Add ArrowUpRight animation on social links | `footer-section.tsx` |
| `document.documentElement.lang` | Add to i18n language change handler | `lib/i18n/index.tsx` |

### Batch P2 (Nice-to-have)
- text-stroke utility on specific titles
- rounded-full CTA buttons
- Decorative corner elements on CTA
- Hover effects on feature/security cards

## Component Tree (unchanged — all 13 sections already exist)

```
app/(landing)/layout.tsx (pass-through)
  └── app/(landing)/page.tsx ← noise-overlay on <main>
       └── LanguageProvider
           ├── Navigation ← updated scroll behavior
           ├── HeroSection ← absolute sphere, fluid font, font-display
           ├── FeaturesSection ← font-display, scroll-in, line eyebrow
           ├── HowItWorksSection ← font-display, scroll-in, line numbers
           ├── MetricsSection ← font-display, scroll-in, line eyebrow
           ├── IntegrationsSection ← full-width marquee
           ├── SecuritySection ← font-display, scroll-in, line eyebrow
           ├── DevelopersSection ← font-display, line numbers
           ├── PricingSection ← font-display plan names
           ├── InfrastructureSection ← font-display, scroll-in
           ├── TestimonialsSection ← full-width marquee
           ├── CtaSection ← font-display, scroll-in
           └── FooterSection ← social link hover effects
```

## Data Flow (unchanged)

No data flow changes. All changes are presentational/animation-only.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/(landing)/page.tsx` | Modify | Add `noise-overlay` to main |
| `app/globals.css` | Modify | Add `scroll-behavior: smooth` |
| `components/landing/navigation.tsx` | Modify | Scroll-based position + rounded + height |
| `components/landing/hero-section.tsx` | Modify | Absolute sphere, font-display, fluid sizing |
| `components/landing/features-section.tsx` | Modify | font-display, scroll-in, line eyebrow |
| `components/landing/how-it-works-section.tsx` | Modify | font-display, scroll-in, line numbers |
| `components/landing/infrastructure-section.tsx` | Modify | font-display, scroll-in, line eyebrow |
| `components/landing/metrics-section.tsx` | Modify | font-display, scroll-in, line eyebrow |
| `components/landing/integrations-section.tsx` | Modify | font-display, full-width marquee |
| `components/landing/security-section.tsx` | Modify | font-display, scroll-in, line eyebrow |
| `components/landing/developers-section.tsx` | Modify | font-display, line numbers |
| `components/landing/pricing-section.tsx` | Modify | font-display plan names |
| `components/landing/testimonials-section.tsx` | Modify | font-display, full-width marquee |
| `components/landing/cta-section.tsx` | Modify | font-display, scroll-in |
| `components/landing/footer-section.tsx` | Modify | Social hover effects |
| `components/landing/animated-tetrahedron.tsx` | Modify | Add Z-axis rotation, larger scale |
| `lib/i18n/index.tsx` | Modify | Set document.documentElement.lang |
