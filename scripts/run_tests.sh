#!/usr/bin/env bash
set -e

echo "=== Running Universal Appointment Booking Engine Test Suite ==="

if [ -d "venv" ]; then
    source venv/bin/activate
fi

python backend/manage.py test backend/tests -v 2
