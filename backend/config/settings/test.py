from .base import configure

globals().update(configure("test"))
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
