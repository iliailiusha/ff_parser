#!/bin/bash
set -e

echo "Starting Xvfb on display :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac &
XVFB_PID=$!
sleep 2

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "ERROR: Xvfb failed to start"
    exit 1
fi

echo "Xvfb started (PID: $XVFB_PID)"
export DISPLAY=:99

echo "Starting bot..."
exec python -m goofish_parser.main
