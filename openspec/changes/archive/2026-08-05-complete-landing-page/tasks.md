# Tasks: Complete Landing Page Quality Upgrade

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~350-450 (targeted edits across 18 files) |
| 400-line budget risk | Medium |
| Chained PRs recommended | No (targeted edits, not rewrites) |
| Delivery strategy | single-pr (size:exception) |

## Phase 1: Foundation (globals.css + page.tsx + i18n)

- [x] 1.1 Add `html { scroll-behavior: smooth }` to `app/globals.css`
- [x] 1.2 Add `noise-overlay` class to `<main>` in `app/(landing)/page.tsx`
- [x] 1.3 Set `document.documentElement.lang` on language change in `lib/i18n/index.tsx`

## Phase 2: Navigation

- [x] 2.1 Update `components/landing/navigation.tsx`:
  - Add scroll state for position shift, rounded-2xl, height change (h-20→h-14)
  - Scale container from `max-w-[1400px]` to `max-w-[1200px]` on scroll
  - Change logo font to `font-display`

## Phase 3: Hero Section

- [x] 3.1 Update `components/landing/hero-section.tsx`:
  - Move sphere from flex sibling to absolute positioned (600-800px, opacity-40, behind text)
  - Add `font-display` class to heading
  - Add fluid font sizing with `text-[clamp(3rem,12vw,10rem)]`
  - Add `w-8 h-px` eyebrow replacing pill badge
  - Add scroll-in animation (opacity/translate transition)

## Phase 4: Canvas Components

- [x] 4.1 Update `components/landing/animated-tetrahedron.tsx`:
  - Add Z-axis rotation for triple-axis motion
  - Increase scale factor from 0.3 to ~0.5

## Phase 5: Section Components — font-display + scroll-in + eyebrow alignment

- [x] 5.1 `components/landing/features-section.tsx`:
  - Add `font-display` to title
  - Add scroll-in animation (IntersectionObserver + state)
  - Replace pill badge eyebrow with `w-8 h-px` line
- [x] 5.2 `components/landing/how-it-works-section.tsx`:
  - Add `font-display` to title
  - Add scroll-in animation
  - Replace pill badge eyebrow with `w-8 h-px` line
- [x] 5.3 `components/landing/infrastructure-section.tsx`:
  - Add `font-display` to title
  - Add scroll-in animation
  - Replace pill badge eyebrow with `w-8 h-px` line
- [x] 5.4 `components/landing/metrics-section.tsx`:
  - Add `font-display` to section title and counter values
  - Replace pill badge eyebrow with `w-8 h-px` line
- [x] 5.5 `components/landing/integrations-section.tsx`:
  - Add `font-display` to title
  - Move marquees to full-width outside container
- [x] 5.6 `components/landing/security-section.tsx`:
  - Add `font-display` to title
  - Add scroll-in animation
  - Replace pill badge eyebrow with `w-8 h-px` line
- [x] 5.7 `components/landing/developers-section.tsx`:
  - Add `font-display` to title
  - Replace pill badge eyebrow with `w-8 h-px` line
- [x] 5.8 `components/landing/pricing-section.tsx`:
  - Add `font-display` to plan names
- [x] 5.9 `components/landing/testimonials-section.tsx`:
  - Add `font-display` to quote text
  - Move logo marquee to full-width outside container
- [x] 5.10 `components/landing/cta-section.tsx`:
  - Add `font-display` to heading
  - Add scroll-in animation
- [x] 5.11 `components/landing/footer-section.tsx`:
  - Change brand font to `font-display`
  - Add social link hover effects with ArrowUpRight animation

## Phase 6: Verification

- [ ] 6.1 Run `pnpm build` and verify no errors
- [ ] 6.2 Verify landing page loads at `/` without console errors
