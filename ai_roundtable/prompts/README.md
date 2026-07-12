# Prompts Directory

This directory contains prompt templates for the AI Roundtable system.

## Templates

- `opening.md` — Opening moderator prompt (Round 0)
- `guest.md` — Guest AI speaking prompt
- `moderator.md` — Moderator summary prompt
- `compress.md` — Context compression prompt

## Template Variables

Variables are written as `{{variable_name}}` and replaced at runtime.

### opening.md
- `{{moderator_name}}` — Name of the moderator AI
- `{{topic}}` — The discussion topic

### guest.md
- `{{agent_name}}` — Name of this guest AI
- `{{context}}` — Current context (topic summary + history + recent rounds)
- `{{round_num}}` — Current round number
- `{{moderator_question}}` — The moderator's guiding question
- `{{action_type}}` — Assigned action type for this round
- `{{action_instruction}}` — Detailed action instruction
- `{{prior_speeches}}` — Speeches from earlier speakers this round (empty in round 1)

### moderator.md
- `{{moderator_name}}` — Name of the moderator AI
- `{{context}}` — Current context
- `{{round_num}}` — Current round number
- `{{round_speeches}}` — All guest speeches from this round

### compress.md
- `{{round_content}}` — Full round content to compress
