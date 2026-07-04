# SmartDocs

SmartDocs is an offline-first AI Agent Platform focused on document understanding, OCR, translation, summarization, retrieval, and document-centric AI workflows.

The platform combines multiple OCR engines, AI services, knowledge systems, and tool-based workflows behind a unified agent architecture.

---

# Platform Vision

SmartDocs is evolving from a document-processing application into an agent-driven platform.

Agent orchestration is the primary architectural layer.

Capabilities such as OCR, translation, summarization, document analysis, retrieval, and future AI functions are exposed through tools and skills.

The long-term architecture is:

User
→ Agent Core
→ Skills
→ Tools
→ Knowledge
→ Memory
→ Response

OCR remains a first-class capability but is no longer the architectural center of the system.

---

# Migration Strategy

SmartDocs-Agent is a successor project, not a rewrite of the existing SmartDocs codebase.

When implementing agent architecture:

* Create a new project version in a separate directory.
* Do not perform an in-place migration of the existing SmartDocs application.
* Do not replace the current SmartDocs implementation.
* Do not remove existing functionality from SmartDocs.

Preferred approach:

SmartDocs/
→ Existing production-capable document platform

SmartDocs-Agent/
→ New agent-oriented architecture
→ Built incrementally using SmartDocs capabilities

The original SmartDocs project must remain runnable and independently maintainable.

---

## Agent Migration Rules

When designing or implementing agent functionality:

1. Treat SmartDocs as the stable baseline.
2. Build new agent components in SmartDocs-Agent.
3. Reuse existing SmartDocs capabilities through adapters, APIs, services, or shared modules.
4. Do not move large subsystems unless explicitly approved.
5. Do not delete existing SmartDocs code during migration.
6. Validate new agent functionality independently before considering replacement.

---

## Architecture Evolution Constraint

The first goal is coexistence.

Not:

Old System
→ Replaced

Instead:

Old System
→ Continues working

New Agent System
→ Developed in parallel

Only after the new system reaches feature parity should replacement even be discussed.

Assume parallel development unless explicitly instructed otherwise.

---

# Core Principles

## Preserve Existing Functionality

Do not remove existing capabilities without explicit approval.

Protected capabilities:

* OCR engines
* OCR workflows
* Translation
* Summarization
* Correction
* Chat
* Existing artifact formats
* Existing APIs
* Existing UI workflows

---

## Prefer Additive Changes

Good:

* Add OCR engines
* Add tools
* Add skills
* Add knowledge bases
* Add retrieval mechanisms
* Add agent workflows

Bad:

* Rewrite working systems
* Replace OCR pipelines without approval
* Remove existing workflows
* Break backward compatibility

---

## Reuse Before Rebuild

Prefer:

* adapters
* integration layers
* shared viewers
* existing services

Avoid:

* duplicated pipelines
* duplicated rendering systems
* duplicated business logic

---

# Project Structure

app/
backend/
frontend/
ocr/
artifacts/
uploads/
docs/

---

# Agent Architecture

The platform follows a layered agent architecture.

User
↓
Agent Core
↓
Skill Selection
↓
Knowledge Retrieval
↓
Tool Execution
↓
Observation
↓
Response Synthesis
↓
UI

---

## Agent Core

The Agent Core is responsible for orchestration.

Responsibilities:

* understand user intent
* select skills
* retrieve context
* invoke tools
* evaluate tool results
* decide next actions
* synthesize responses

The Agent Core must NOT contain business logic.

Business logic belongs in tools and services.

---

## Skills

Skills define reusable workflows.

A skill may:

* retrieve knowledge
* call multiple tools
* orchestrate execution
* perform validation
* synthesize outputs

Skills should remain lightweight.

Skills orchestrate.

Tools execute.

---

## Tools

Tools expose capabilities.

Examples:

* OCR Tool
* Translation Tool
* Summary Tool
* Chat Tool
* Search Tool
* RAG Tool
* Document Analysis Tool
* Export Tool

Tools should:

* perform one responsibility
* return structured outputs
* remain independently testable

Do not embed orchestration inside tools.

---

## Knowledge Layer

Knowledge may include:

* OCR documentation
* User documentation
* Product documentation
* Technical references
* Domain knowledge
* Internal project knowledge

Knowledge systems should support:

* retrieval
* citation
* ranking
* future vector search

Knowledge is not business logic.

---

## Memory Layer

Memory is optional.

Possible memory types:

* conversation memory
* session memory
* document memory
* user preference memory

Memory must be isolated from business logic.

---

## Model Independence

The architecture must not depend on a specific LLM.

Supported models may include:

* Qwen
* GLM
* DeepSeek
* Claude
* GPT
* future local models

The Agent Core should communicate through a provider abstraction.

Never hard-code business workflows to a specific model.

---

# Agent Workflow

Preferred flow:

1. Analyze request
2. Select skill
3. Retrieve knowledge
4. Execute tools
5. Observe results
6. Decide whether more tools are required
7. Synthesize response
8. Return result

Multi-tool execution is preferred over monolithic prompts.

---

# Skills Framework

Skill loading should remain minimal.

Load only the skills required for the current task.

---

## OCR / AI / Model Investigation

Use:

* source-driven-development
* doubt-driven-development

Examples:

* OCR engine evaluation
* OCR integration
* OCR comparison
* model benchmarking
* model integration

---

## Code Changes

Use:

* code-review-and-quality

Examples:

* bug fixes
* feature implementation
* API changes
* UI changes
* refactoring explicitly requested

---

## Architecture Work

Use:

* context-engineering

Examples:

* agent architecture
* workflow redesign
* storage redesign
* retrieval architecture
* major platform changes

---

## Agent Development

Use:

* context-engineering
* source-driven-development
* doubt-driven-development

Examples:

* tool orchestration
* skill design
* memory systems
* retrieval systems
* agent planning logic

---

## Security Work

Use:

* source-driven-development
* doubt-driven-development
* code-review-and-quality

Examples:

* security audits
* authorization
* authentication
* file handling
* upload security
* vulnerability analysis

---

## Documentation Work

Use:

* source-driven-development

Examples:

* architecture documentation
* implementation documentation
* design documentation

Documentation must match verified implementation.

---

## Default Skill Set

For most SmartDocs tasks:

* source-driven-development
* doubt-driven-development

Add:

* code-review-and-quality

only when code changes are required.

Add:

* context-engineering

only when architectural changes are required.

Do not load additional skills unless necessary.

---

# OCR Domain

OCR remains a core platform capability.

---

## OCR Architecture

OCR Engine
↓
Structured Extraction
↓
Artifact Generation
↓
SmartDocs Processing
↓
UI Rendering

---

## OCR Engine Layer

Examples:

* Legacy PaddleOCR
* VietOCR
* PaddleOCR Modern
* GLM OCR

Produces:

* text
* confidence
* bounding boxes

---

## Structured Extraction Layer

Produces:

* markdown
* html
* tables
* layout blocks
* document structure

Examples:

* PP-StructureV3
* GLM OCR parser

---

## Artifact Layer

Produces:

* markdown
* json
* extracted images
* visualization outputs

---

## SmartDocs Processing Layer

Consumes OCR outputs for:

* correction
* translation
* summarization
* chat
* retrieval
* document analysis

---

## Rendering Layer

Displays:

* markdown rendered
* markdown raw
* extracted images
* json

---

# OCR Viewer Standard

Preferred viewer tabs:

1. Markdown (Rendered)
2. Markdown (Raw)
3. Extracted Images
4. JSON

Viewer behavior should be artifact-driven.

Reuse existing OCR visualizations whenever practical.

Avoid engine-specific viewers unless necessary.

---

# OCR Investigation Rules

Before modifying OCR behavior:

Determine which layer is responsible.

Possible layers:

* OCR engine
* structure extraction
* artifact generation
* SmartDocs processing
* renderer

Required process:

1. Inspect OCR output
2. Inspect structured output
3. Inspect artifacts
4. Inspect renderer
5. Identify responsible layer
6. Modify only that layer

Do not assume the failing layer.

---

# OCR Ordering Rule

Before changing document ordering:

Determine whether ordering is produced by:

* OCR engine
* structure extraction
* markdown serializer
* SmartDocs post-processing
* renderer

Modify only the responsible stage.

---

# Evidence Hierarchy

Prefer evidence in this order:

1. Source code
2. Official documentation
3. Reproducible testing
4. Benchmarks
5. Community discussion
6. README claims

Higher-ranked evidence overrides lower-ranked evidence.

Never trust README claims over verified source code behavior.

---

# Development Rules

## Think Before Coding

Before implementation:

* state assumptions
* identify ambiguity
* identify alternatives
* request clarification when required

Do not silently choose between multiple interpretations.

---

## Simplicity First

Prefer the smallest solution that solves the problem.

Avoid:

* speculative abstractions
* unnecessary configuration
* premature optimization
* unnecessary future-proofing

---

## Surgical Changes

Touch only what is required.

Do not:

* refactor unrelated code
* rename unrelated symbols
* reorganize unrelated modules
* modify unrelated UI

Report unrelated issues.

Do not fix them automatically.

---

# Validation Requirements

Before completion:

Backend:

* application starts successfully
* routes register successfully
* no import failures

Frontend:

* build succeeds
* no console errors

OCR:

* OCR execution works
* markdown generation works
* JSON generation works
* artifacts persist correctly

If modifying OCR:

Verify:

* text output
* markdown output
* JSON output

---

# Reporting Rules

Always separate:

## Implemented

Completed work.

## Verified

Actually tested.

## Unverified

Not tested.

## Planned

Not implemented.

Never present:

* planned work as implemented
* unverified work as verified

---

# Architecture Evolution Rules

The platform is expected to evolve.

Future additions may include:

* new OCR engines
* new agent skills
* new tools
* new knowledge bases
* new memory systems
* new retrieval systems
* new AI providers

Prefer extension over replacement.

Working systems should be extended before being rewritten.

---

# Boundaries

## Always

* Research before concluding
* Verify before claiming
* Preserve backward compatibility
* Reuse existing functionality
* Prefer evidence over assumptions
* Keep changes focused
* Identify the failing layer before fixing

## Never

* Rewrite architecture without approval
* Remove OCR engines without approval
* Remove OCR capabilities without approval
* Break existing workflows without justification
* Present assumptions as facts
* Claim verification without testing
* Change public contracts without approval
* Remove existing functionality during agent migration

## Default Assumption

Unless explicitly instructed otherwise:

* New architectures are created alongside existing systems.
* Existing systems are preserved.
* Migration is additive.
* Destructive refactoring is prohibited.
* Parallel implementations are preferred over replacement.

