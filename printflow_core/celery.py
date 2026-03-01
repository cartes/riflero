"""
Celery application configuration for printflow_core.
"""

import os
from celery import Celery

# Set the default Django settings module for the Celery program
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'printflow_core.settings')

app = Celery('printflow_core')

# Use Django settings prefixed with CELERY_ for configuration
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps (tasks.py inside each app)
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
