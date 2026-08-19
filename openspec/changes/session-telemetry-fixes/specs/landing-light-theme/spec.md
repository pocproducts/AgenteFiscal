# Landing Light Theme Specification

## Purpose

Landing routes always render in light mode regardless of OS preference; the ThemeProvider is scoped to the chat layout; the chat dark/light toggle keeps working; no theme-flash regression.

## Requirements

### Requirement: LLT-1 — Landing always light

The `(landing)` layout MUST render its children in light mode regardless of OS preference or stored theme. Landing components MUST NOT inherit a dark class from a root provider.

#### Scenario: Landing on dark OS

- GIVEN the OS prefers dark and the ThemeProvider is scoped to `(chat)`
- WHEN the user opens the landing page
- THEN the page renders light
- AND no landing component carries the `.dark` class

#### Scenario: Landing on light OS

- GIVEN the OS prefers light
- WHEN the user opens the landing page
- THEN the page renders light

### Requirement: LLT-2 — No theme flash on landing

The landing page MUST NOT flash dark styling while loading or hydrating.

#### Scenario: First visit with dark preference

- GIVEN a first visit with dark OS preference
- WHEN the landing HTML renders and hydrates
- THEN no dark styling appears at any point during load

### Requirement: LLT-3 — Chat theme toggle keeps working

The `(chat)` layout MUST host the ThemeProvider, and the dark/light toggle MUST keep working for chat routes without affecting the landing theme.

#### Scenario: Toggle to dark in chat

- GIVEN a chat route with the toggle
- WHEN the user switches to dark
- THEN chat renders dark
- AND the landing page remains light on revisit

#### Scenario: Toggle to light in chat

- GIVEN a chat route currently in dark
- WHEN the user switches to light
- THEN chat renders light
- AND the change applies without theme flash