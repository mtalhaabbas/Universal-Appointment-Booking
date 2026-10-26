#!/usr/bin/env bash
set -e

if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "Processing pending Transactional Outbox events..."
python backend/manage.py process_outbox --limit 100
