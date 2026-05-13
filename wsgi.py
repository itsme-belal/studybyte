# wsgi.py — Gunicorn + eventlet entry point for Render
# Start command: gunicorn -k eventlet -w 1 wsgi:app
#
# IMPORTANT: eventlet.monkey_patch() is called at the TOP of app.py
# before any other imports. Do NOT import anything before app.py is loaded.

from app import app, socketio

# Gunicorn calls this 'application' object
application = app
