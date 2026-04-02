#!/bin/bash
WORKDIR=$(cat /tmp/ready 2>/dev/null || echo /home/agent)
cd "$WORKDIR"
exec bash
