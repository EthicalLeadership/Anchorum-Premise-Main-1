# Theme extensions

The shell uses semantic state and focus tokens mapped to the host-provided
COUNSEL palette. Components must consume these tokens rather than introducing
component-specific colors.

`src/styles/tokens.css` maps:

- `--tp-bg`, `--tp-fg`, `--tp-line`, `--tp-muted`, and `--tp-acc` to the
  corresponding COUNSEL surface, text, line, muted, and accent tokens.
- `--state-ok`, `--state-warn`, `--state-fail`, `--state-hold`, and
  `--state-idle` to COUNSEL's green, amber, red, and neutral ramps.
- Each state token has a matching `-bg` fill token.
- `--focus-ring`, `--focus-width`, and `--focus-offset` define focus treatment.

This checkout does not currently provide the COUNSEL palette. The CSS uses
browser system colors as a neutral preview fallback; state labels remain
textual, so color is never the only state indicator. The production theme must
provide the `--counsel-*` custom properties before claiming palette conformance.

The body typeface, `--tp-mono`, and spacing values are referenced by the shell;
the shell does not add a separate type or spacing scale beyond the preview
tokens required to render it.
