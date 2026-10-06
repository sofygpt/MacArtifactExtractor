# Tahoe HfsPlus Implementation Plan

> For agentic workers: implement sequentially using executing-plans; native execution is used for this deliverable.

**Goal:** Runner downloads Apple Tahoe, extracts Intel firmware and HfsPlus with provenance.
**Architecture:** Python catalog resolver and binary/archive core; Python macOS orchestrator; manual GitHub workflow.
**Tech Stack:** Python 3 standard library, pkgutil, hdiutil, curl, UEFIExtract A75.
**Spec:** ../specs/2026-10-06-tahoe-hfsplus-design.md

## Global Constraints
- Only stable Tahoe 26.x; TLS Apple downloads and verified package signature.
- UEFIExtract A75 archive pinned by SHA-256; no execution of extracted drivers.
- Fail on absent drivers; retain ambiguity and logs, do not silently substitute.
- macOS-only operations require GitHub runner or explicit local invocation.

## Review Focus
- Apple catalog metadata missing or another macOS selected: fail clearly.
- ZIP traversal/symlinks: never write outside the extraction directory.
- IA32/ARM/MZ-only impostor: reject instead of naming it HfsPlus.efi.
- Multiple firmware versions: retain hashes, select no arbitrary canonical file.
- Disk pressure and failure cleanup: preflight, detach mounts, retain diagnostic output.

### Task 1: Source selection and binary/archive core
Files: scripts/core.py, scripts/apple_catalog.py, tests/test_core.py, tests/test_catalog.py.
Interfaces: catalog resolver emits source.json with version/build/pkg URL/size;
core returns PE metadata and candidate records, hashes and canonical selection.
- [x] Write tests for domain filtering, stable metadata, ZIP entries and PE/ambiguity.
- [x] Run tests and observe missing implementation.
- [x] Implement core and resolver, run the complete unittest suite.

### Task 2: Orchestrator and workflow
Files: scripts/extract_tahoe.py, .github/workflows/extract-hfsplus.yml, README.md.
Consumes: source.json and core validators; produces output/manifest.json,
SHA256SUMS, candidates/ and optional HfsPlus.efi.
- [x] Implement package verification, read-only mount and selected firmware extraction.
- [x] Pin UEFIExtract and Actions, add minimum permissions/manual trigger.
- [x] Validate workflow YAML, CLI and macOS command construction; document first-run limitations.

### Task 3: Delivery verification
- [x] Review source/runner input boundaries and cleanup paths.
- [x] Run complete tests, Python compilation and YAML checks.
- [ ] Package the project including hidden workflow directory; save deliverable.
