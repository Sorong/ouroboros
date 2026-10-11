#!/usr/bin/env sh
# python.sh <script> [args] — runs one of the plugin's scripts with the first Python that really
# runs. On Windows `python3` is often missing or the Store stub that runs nothing; there `python`
# or `py` is the real one. The hook and every command in `bin/` start through here.
#
# The floor is the oldest Python still supported upstream; raise it when that one reaches its end
# of life (3.10: October 2026).
name=$1
script="${0%/*}/$name"
shift
for python in python3 python py; do
    if "$python" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        exec "$python" "$script" "$@"
    fi
done
message="ouroboros: no Python 3.10 or newer found (tried python3, python, py)"
if [ "$name" = session_start.py ]; then
    # The hook stays silent where the loop doesn't run and never fails a session.
    top=$(git -C "${CLAUDE_PROJECT_DIR:-.}" rev-parse --show-toplevel 2>/dev/null) || exit 0
    [ -f "$top/.claude/ouroboros.json" ] && printf '{"systemMessage": "%s, the loop is off."}\n' "$message"
    exit 0
fi
echo "$message" >&2
exit 127
