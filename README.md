# LEADGEN

Agent startup sequence:

1. Read `.agent/brain.json`.
2. Read `.agent/rules.json`.
3. Read `.agent/task_state.json`.
4. For audit work, read `.agent/factor_registry.json`.
5. For scope and phase gates, consult `docs/LEADGEN_MASTER_PRODUCT_PLAN.md`.
6. For current implementation status and verified system architecture, consult `docs/LEADGEN_CURRENT_IMPLEMENTATION_STATUS.md` and `docs/LEADGEN_SYSTEM_ARCHITECTURE_PRODUCT_DOCUMENTATION.md`.
7. Trace the executable source before changing behavior.

Historical implementation notes are retained in `docs/archive/`. Runtime code is the source of truth.
