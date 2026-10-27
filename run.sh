#!/bin/sh
# Run from the project root so Pydantic can load .env and relative key paths.
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_root"

if [ -x .venv/bin/python ]; then
    python_bin=.venv/bin/python
elif [ -f .venv/Scripts/python.exe ]; then
    # Git Bash on Windows uses the existing Windows virtual environment.
    python_bin=.venv/Scripts/python.exe
else
    printf '%s\n' 'Project virtual environment missing. Create .venv and install: pip install -e ".[test]"' >&2
    exit 1
fi

# Prefer an installed Node.js; also support a project-local portable runtime.
if command -v node >/dev/null 2>&1; then
    node_bin=node
else
    node_bin=
    for candidate in .tools/node-*/bin/node .tools/node-*/node.exe; do
        if [ -f "$candidate" ]; then
            node_bin=$candidate
            break
        fi
    done
    if [ -z "$node_bin" ]; then
        printf '%s\n' 'Node.js 22+ is required. Install Node.js LTS and reopen your terminal.' >&2
        exit 1
    fi
fi

# Node owns both processes so Ctrl+C and startup failures clean up both apps.
# Additional arguments (for example --reload) are forwarded to Uvicorn.
"$node_bin" -e "if (Number(process.versions.node.split('.')[0]) < 22) { console.error('Node.js 22+ is required. Install Node.js LTS.'); process.exit(1); }"
exec "$node_bin" scripts/run.mjs "$python_bin" "$@"
