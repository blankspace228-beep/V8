# Aurora AI 2.10 Beta — Signed Update Security

Embedded public key:

`pJKPZoMm1Fu3bFH4jap3GuCflwZoR0pyWnnytPkwQbU=`

Added:
- mandatory Ed25519 verification of update manifests
- SHA-256 verification still required for update payload, decoded source, and builder
- optional Windows Authenticode signing in the builder
- optional Authenticode enforcement through `require_authenticode=true`
- Aurora Release Publisher utility
- separate private release key

The private signing key is intentionally not stored in this repository.
A public/stable release should use a trusted Windows code-signing certificate in addition to the signed manifest.