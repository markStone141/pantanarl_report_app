from .local import *


# Password strength is covered by Django. Application tests only need a
# deterministic encoded password that authenticate() can verify quickly.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
