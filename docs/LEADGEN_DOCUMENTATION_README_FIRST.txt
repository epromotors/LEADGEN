LEADGEN DOCUMENTATION BUNDLE
============================

Contents
--------
1. LEADGEN_MASTER_PRODUCT_PLAN.md
   Read-only product scope, phased implementation plan, acceptance gates, and AI-agent recovery instructions.

2. LEADGEN_SYSTEM_ARCHITECTURE_PRODUCT_DOCUMENTATION.pdf
   Visual 18-page architecture/product reference with architecture diagrams, workflows, logical ERD, technology stack, API inventory, scripts, target advanced audit domains, roadmap, and safety constraints.

3. LEADGEN_SYSTEM_ARCHITECTURE_PRODUCT_DOCUMENTATION.md
   Editable architecture reference source corresponding to the PDF.

Recommended placement in LEADGEN-RELEASE
----------------------------------------
docs/LEADGEN_MASTER_PRODUCT_PLAN.md
docs/LEADGEN_SYSTEM_ARCHITECTURE_PRODUCT_DOCUMENTATION.pdf
docs/LEADGEN_SYSTEM_ARCHITECTURE_PRODUCT_DOCUMENTATION.md

Agent startup instruction
-------------------------
Read docs/LEADGEN_MASTER_PRODUCT_PLAN.md completely first. Read docs/LEADGEN_SYSTEM_ARCHITECTURE_PRODUCT_DOCUMENTATION.md for current system architecture and future-state context. The master product plan controls scope and phase gates; the architecture document explains the current platform and target design. Both distinguish documented/current capabilities from planned capabilities. Verify actual code, routes, ORM models, and configuration in the checked-out branch before implementing. Do not treat future features as implemented. Preserve published commits and the protected original checkout. Do not push, deploy, or write to production databases without separate authorization.

Source/accuracy note
--------------------
The architecture reference consolidates project documentation and release/test reports supplied during prior work. It is not a fresh source-code scan. Old repo docs disagree between 55 and 62 factors; the document flags this as documentation drift and requires the current factor contract/registry/strict validator in code to be the authority. Exact route mounts, ORM columns, script names and package versions must be confirmed from the active checkout before code changes.
