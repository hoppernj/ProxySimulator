import os
import secrets

secret_key = secrets.token_urlsafe(50)

BASE_DIR = os.getcwd() # os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRET_KEY = secret_key

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'assignments',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

USE_TZ = True
TIME_ZONE = 'UTC'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

