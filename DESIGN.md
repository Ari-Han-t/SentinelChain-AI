# SentinelChain Design System

SentinelChain is an operational instrument, not a collection of dashboard cards. The topology is the primary workspace; evidence, guidance, and action controls appear only in context.

## Visual language

- Palette: `#090b0d` canvas, `#0f1215` surface, `#15191d` raised surface, `#292e33` line, `#f2f3f3` primary text, `#999fa4` secondary text, and `#ff5f57` as the only alert accent.
- Type: Space Grotesk for headings, DM Sans for readable interface text, IBM Plex Mono for identifiers and timestamps. Self-host these fonts before production.
- Spacing uses a 4px base. Corners are 3-6px. Shadows are reserved for overlays such as the node inspector.
- Primary body text is at least 16px. Smaller text is metadata only and must retain WCAG AA contrast.

## Interaction vocabulary

- `ProcessNode`: stage type, name, owner, monitored state, and pending-action count.
- `MonitoredEdge`: named handoff; a dashed alert edge indicates a propagating exception.
- `Inspector`: selected node, guidance, cited evidence, manual update, history, and approvals.
- `EvidenceRecord`: always shows source, occurrence time, confidence, and dispute state.
- `ActionProposal`: reason, expected impact, owner, urgency, status, and explicit human decision.
- Status is never color-only. Pair labels and icons with line style or shape.

## Motion and accessibility

- Use 160-240ms transitions for selection and drawers. Only changed or at-risk paths animate.
- Respect `prefers-reduced-motion`; animation must never be required to understand state.
- All graph nodes and controls need keyboard equivalents, visible focus, accessible names, and a logical reading order.
- Touch targets are at least 44px. Mobile replaces the spatial canvas with a vertical stage rail and bottom-sheet inspector.

## Content rules

- Azure AI Foundry guidance must cite evidence and distinguish deterministic state from model interpretation.
- Healthy states say “No action needed,” why, and when the next check occurs.
- Empty states identify what is missing and provide a relevant action.
- Never use decorative KPI cards, fake terminal copy, gradients, or generic cyber-security imagery.
