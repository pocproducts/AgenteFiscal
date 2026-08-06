# Specification: Complete Landing Page Quality Upgrade

## Requirement: Typography — font-display on all headings

ALL section headings MUST use the `font-display` class (Instrument Serif, Georgia, serif) instead of `font-bold` or default sans-serif.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|-------|
| Section heading renders | Any section is visible | Heading is inspected | `font-display` class is present |

Affected: hero heading, features title, how-it-works title, infrastructure title, metrics title, integrations title, security title, developers title, pricing plan names, testimonials quote, cta heading

## Requirement: Scroll-in animations

Every section MUST have a scroll-in animation triggered by IntersectionObserver: starts at `opacity-0 translate-y-8`, animates to `opacity-100 translate-y-0` over 700ms when section enters viewport.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|-------|
| Section enters viewport | User scrolls to section | First intersection | Section fades in with translate animation over 700ms |

## Requirement: Noise overlay

The main landing page wrapper MUST have the `noise-overlay` class for the SVG noise texture.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|-------|
| Page renders | User loads landing | Page is visible | SVG noise texture is visible at 0.03 opacity |

## Requirement: Smooth scroll

The HTML element MUST have `scroll-behavior: smooth` for anchor navigation.

## Requirement: Navigation scroll behavior

On scroll, the navigation MUST:
- Add `top-4` position shift
- Change border-radius to `rounded-2xl`
- Shrink from `h-20` to `h-14`
- Scale container from `max-w-[1400px]` to `max-w-[1200px]`

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|-------|
| Scroll down | User scrolls below threshold | Scroll fires | Nav gets top-4, rounded-2xl, h-14, narrower container |
| Scroll to top | User reaches top | Scroll fires | Nav returns to default state |

## Requirement: Hero sphere positioning

The AnimatedSphere MUST be positioned as an absolute background element (600-800px, opacity-40, behind text, right-aligned) rather than a flex layout sibling.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|-------|
| Hero renders | Page loads | Hero visible | Sphere is behind text, not beside it |

## Requirement: Eyebrow consistency

All sections MUST use `w-8 h-px bg-foreground/30` line-style eyebrow indicators instead of pill badges with colored dots.

## Requirement: Canvas animation colors

Each canvas animation MUST use colors that match its containing section's background:
- hero: white chars on dark (#fff)
- cta: white chars on dark (#fff)
- footer: white chars on dark (#fff)

## Requirement: Code line numbers

Code blocks in Developers section and HowItWorks section MUST display line numbers alongside code content.

## Requirement: Marquee full-width

Integrations and Testimonials logo marquees MUST span full viewport width (outside container constraints).
