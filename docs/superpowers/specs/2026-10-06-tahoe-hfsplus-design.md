# Tahoe HfsPlus extraction

Build a manually triggered GitHub Actions workflow for the user's own repository.
The runner reads the public Apple software-update catalog, selects a stable Tahoe
26.x InstallAssistant package (or an exact requested version/build), verifies its
Apple package signature, expands it without executing installation scripts,
mounts SharedSupport read-only and extracts only Intel firmware payloads.
UEFIExtract A75 is pinned by release and published SHA-256. Only the known
HfsPlus GUID's PE32 section body is accepted, with x86_64/PE32+/EFI-driver checks.

Outputs: extracted drivers, source manifest, checksums, firmware inventory and
logs. Duplicate bytes are grouped. Multiple different valid binaries are retained
under their hashes; no arbitrary canonical HfsPlus.efi is selected. Empty results
are a failure. Never substitute a binary from OcBinaryData when extraction fails.
Optional comparison requires an exact 40-character OcBinaryData commit.

Use macos-15-intel; download a Tahoe package independently of the runner OS.
Clear Xcode only in an ephemeral GitHub-hosted runner, with an explicit boundary
check; refuse insufficient disk space. No host firmware reads, flashing, EFI writes,
publishing, account credentials, or macOS installation. Package metadata must
confirm major version 26. Network package paths stay on Apple domains over HTTPS.

Local tests cover the security boundaries, archive traversal, PE architecture,
signature result parsing, metadata selection and ambiguity handling. A real
multi-GB Apple download, pkgutil/hdiutil operations and GitHub-hosted execution
remain unverified in this Linux environment and must be reported as such.
