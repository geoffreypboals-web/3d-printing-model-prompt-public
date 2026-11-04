#!/usr/bin/env bash
# Project: 3D Printing Model Prompt
# File: launch.sh
# Description: Double-click launcher. Finds free host ports for
#   the app and the bundled Ollama (or reuses the ones already resolved),
#   starts the stack, and opens the app in your browser. Same as
#   `python3 launch.py up` then `python3 launch.py open`. See launch.py.
# Inputs: none (APP_HOST_PORT / OLLAMA_HOST_PORT in .env pin the ports;
#   OLLAMA_HOST or LLM_PROVIDER=claude in .env skips the bundled Ollama).
# Outputs: the running stack and a browser tab.
# Troubleshooting: "permission denied" -- chmod +x launch.sh; Docker must be
#   running and your user in the docker group.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
python3 launch.py up && python3 launch.py open
status=$?
if [ $status -ne 0 ]; then
    echo ""
    echo "Something went wrong -- see the messages above."
    read -rp "Press Enter to close..."
fi
exit $status
