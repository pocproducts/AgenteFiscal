# Proposal: Complete Landing Page — Full Optimus Reference Match

## Intent

Upgrade the existing landing page implementation to match the visual quality, animations, and polish of the Optimus AI Platform reference. Current implementation has all 16 components but differs in layout philosophy, animation approach, typography, and scroll behavior.

## Scope

### In Scope
- Apply `font-display` (Instrument Serif) to ALL section headings — biggest single visual gap
- Add consistent scroll-in animations to ALL sections (opacity + translateY on IntersectionObserver)
- Add `noise-overlay` on `<main>` wrapper
- Add `scroll-behavior: smooth` to globals.css
- Update Navigation scroll behavior: position shift + rounded-2xl + height shrink on scroll
- Change Hero sphere from flex layout sibling to absolute positioned background (600-800px)
- Align eyebrow style across all sections (decide pill-badge vs line-style — line-style per reference)
- Match canvas animation colors to section backgrounds
- Add fluid `clamp()` font sizing to hero title
- Add Z-axis rotation + face-filling points to tetrahedron canvas
- Add line numbers to code blocks in Developers and HowItWorks sections
- Move Integrations and Testimonials marquees to full-width
- Add social link hover effects to Footer
- Update i18n footer structure for 4-column layout
- Set `document.documentElement.lang` on language change
- Add `html { scroll-behavior: smooth }`

### Out of Scope
- No new sections (all 13 already exist)
- No route restructuring (already in (landing)/ route group)
- No new dependencies
- No changes to chat/auth functionality
- No backend changes

## Approach

1. Batch P0 changes (visual parity): typography, scroll animations, navigation, hero layout, noise overlay, smooth scroll, eyebrow alignment, canvas colors
2. Batch P1 changes (polish): fluid hero sizing, tetrahedron improvements, code line numbers, full-width marquees, footer social links, i18n improvements
3. Batch P2 changes (nice-to-have): text-stroke, rounded-full buttons, decorative elements, hover effects

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `components/landing/*.tsx` | Modified | 16 components with targeted improvements |
| `app/(landing)/page.tsx` | Modified | Add noise-overlay, reorder sections |
| `app/globals.css` | Modified | Add smooth-scroll, any missing utilities |
| `lib/i18n/index.tsx` | Modified | Add document.lang, update footer structure |
| `openspec/changes/` | Updated | New complete-landing-page artifacts |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Visual regression on existing sections | Low | Build verify, manual visual check |
| Canvas color mismatch on different sections | Low | Test each canvas against its section bg |
| Build failure from TS errors | Low | Targeted edits preserve existing types |

## Success Criteria

- [ ] All 13 sections render with consistent scroll-in animations
- [ ] All headings use `font-display` (Instrument Serif)
- [ ] Navigation has polished scroll behavior (position shift, rounded corners, height shrink)
- [ ] Hero sphere renders as absolute background behind text
- [ ] All sections have consistent `w-8 h-px` eyebrow style
- [ ] `noise-overlay` applies to entire landing page
- [ ] Canvas animations match their section background colors
- [ ] `pnpm build` succeeds
