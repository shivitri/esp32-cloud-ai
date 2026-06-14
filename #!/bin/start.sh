#!/bin/bash
# This allows the worker to run longer without timing out
# The key is: --timeout 120 (2 minutes instead of default 30 seconds)
# and --workers 1 for Render's free tier

exec gunicorn \
    --bind 0.0.0.0:10000 \
    --workers 1 \
    --timeout 120 \
    --worker-class sync \
    --access-logfile - \
    --error-logfile - \
    main:app
