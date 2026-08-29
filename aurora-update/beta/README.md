# Aurora AI Beta Update Channel

This directory is the public manifest/source channel used by Aurora's built-in beta updater.

Aurora reads `manifest.json`, downloads the source and non-interactive builder listed there,
verifies both SHA-256 hashes, builds the update locally, backs up the current executable,
swaps the executable after Aurora exits, restarts, and rolls back if the new process dies
during its initial startup window.

Do not store billing secrets, owner credentials, signing secrets, or account database data here.