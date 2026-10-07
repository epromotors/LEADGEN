# LEADGEN

Agent startup sequence:

1. Read `.agent/brain.json`.
2. Read `.agent/rules.json`.
3. Read `.agent/task_state.json`.
4. For audit work, read `.agent/factor_registry.json`.
5. Trace the executable source before changing behavior.

Historical implementation notes are retained in `docs/archive/`. Runtime code is the source of truth.
