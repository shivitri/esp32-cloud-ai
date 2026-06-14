#!/bin/bash
exec gunicorn \
    --bind 0.0.0.0:10000 \
    --workers 1 \
    --timeout 120 \
    --worker-class sync \
    --access-logfile - \
    --error-logfile - \
    main:app
