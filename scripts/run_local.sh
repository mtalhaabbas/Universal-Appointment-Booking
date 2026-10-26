#!/usr/bin/env bash
set -e

echo "=== Universal Appointment Booking Engine: Local Runner ==="

# 1. Activate venv if present
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 2. Database migrations
echo "Applying database migrations..."
python backend/manage.py migrate

# 3. Seed demo data
echo "Seeding demo businesses (Clinic, Salon, Gym)..."
python backend/manage.py seed_demo_data

# 4. Start local development server
echo "Starting Django server at http://127.0.0.1:8000 ..."
python backend/manage.py runserver 127.0.0.1:8000
