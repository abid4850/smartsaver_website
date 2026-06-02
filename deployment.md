# 🚀 SmartSaver Production Deployment Guide

*(Django + uWSGI + Nginx)*

---

## 📌 Overview

Production deployment of **SmartSaver Website** using:

* Django
* PostgreSQL
* uWSGI
* Nginx
* systemd

---

## 🔗 Project Details

* 🌐 Domain: `smartsaver.abidnexus.com`
* 📦 Repository: https://github.com/abid4850/smartsaver_website

---

## ✅ Prerequisites

* Ubuntu VPS (22.04+ recommended)
* Root SSH access
* Domain pointed to VPS IP

---

## ⚙️ Step 1: Connect & Install Dependencies

```bash
ssh root@YOUR_VPS_IP

apt update && apt upgrade -y

apt install -y python3.12 python3.12-venv python3-dev \
gcc nginx postgresql libpq-dev git curl
```

---

## 👤 Step 2: Create App User

```bash
useradd -m -s /bin/bash -G www-data django_user
passwd django_user
usermod -aG sudo django_user

su - django_user
chmod 711 /home/django_user
```

---

## 🐘 Step 3: Setup PostgreSQL

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE smartsaver_db;

CREATE USER smartsaver_user WITH PASSWORD 'strong_password';

ALTER ROLE smartsaver_user SET client_encoding TO 'utf8';
ALTER ROLE smartsaver_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE smartsaver_user SET timezone TO 'UTC';

GRANT ALL PRIVILEGES ON DATABASE smartsaver_db TO smartsaver_user;

\q
```

---

## 📦 Step 4: Deploy Project

```bash
cd /home/django_user

git clone https://github.com/abid4850/smartsaver_website.git
cd smartsaver_website

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

pip install uwsgi psycopg2-binary
```

---

## ⚙️ Step 5: Production Settings

```bash
nano smart_saver/settings_prod.py
```

```python
from .settings import *

DEBUG = False

ALLOWED_HOSTS = [
    "smartsaver.abidnexus.com",
]

CSRF_TRUSTED_ORIGINS = [
    "https://smartsaver.abidnexus.com",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "smartsaver_db",
        "USER": "smartsaver_user",
        "PASSWORD": "strong_password",
        "HOST": "localhost",
        "PORT": "5432",
    }
}

STATIC_ROOT = "/home/django_user/smartsaver_website/staticfiles"
MEDIA_ROOT = "/home/django_user/smartsaver_website/media"

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

---

## ▶️ Step 6: Run Migrations

```bash
export DJANGO_SETTINGS_MODULE=smart_saver.settings_prod

python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

---

## 🔌 Step 7: uWSGI Configuration

```bash
nano /home/django_user/smartsaver_uwsgi.ini
```

```ini
[uwsgi]
chdir = /home/django_user/smartsaver_website
module = smart_saver.wsgi:application

home = /home/django_user/smartsaver_website/.venv
env = DJANGO_SETTINGS_MODULE=smart_saver.settings_prod

master = true
processes = 2
threads = 2

socket = /home/django_user/smartsaver.sock
chmod-socket = 660
chown-socket = django_user:www-data

vacuum = true
die-on-term = true
```

---

## 🌐 Step 8: Nginx Configuration

```bash
sudo nano /etc/nginx/conf.d/smartsaver.conf
```

```nginx
server {
    listen 80;
    server_name smartsaver.abidnexus.com;

    location / {
        include uwsgi_params;
        uwsgi_pass unix:/home/django_user/smartsaver.sock;
    }

    location /static/ {
        alias /home/django_user/smartsaver_website/staticfiles/;
    }

    location /media/ {
        alias /home/django_user/smartsaver_website/media/;
    }
}
```

```bash
nginx -t
systemctl restart nginx
```

---

## 🔁 Step 9: systemd Service

```bash
sudo nano /etc/systemd/system/smartsaver.service
```

```ini
[Unit]
Description=SmartSaver Django uWSGI
After=network.target

[Service]
User=django_user
Group=www-data
WorkingDirectory=/home/django_user/smartsaver_website

ExecStart=/home/django_user/smartsaver_website/.venv/bin/uwsgi \
--ini /home/django_user/smartsaver_uwsgi.ini

Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable smartsaver
systemctl start smartsaver
systemctl status smartsaver
```

---

## 🔁 Step 10: Auto Deployment Script

```bash
nano /home/django_user/smartsaver_website/auto_update.sh
```

```bash
#!/bin/bash

cd /home/django_user/smartsaver_website

source .venv/bin/activate

git pull origin main

pip install -r requirements.txt

export DJANGO_SETTINGS_MODULE=smart_saver.settings_prod

python manage.py migrate
python manage.py collectstatic --noinput

systemctl restart smartsaver
```

```bash
chmod +x auto_update.sh
```

### Cron Job

```bash
crontab -e
```

```bash
0 3 */3 * * /home/django_user/smartsaver_website/auto_update.sh >> /home/django_user/update.log 2>&1
```

---

## 🧪 Step 11: Testing

```bash
curl -I http://localhost
curl -I http://smartsaver.abidnexus.com
```

---

## 🔐 Step 12: Enable HTTPS (Let's Encrypt)

```bash
apt install certbot python3-certbot-nginx -y

certbot --nginx -d smartsaver.abidnexus.com
```

---

## ✅ Final Checklist

* [ ] Nginx running
* [ ] uWSGI service active
* [ ] Domain configured correctly
* [ ] HTTPS enabled
* [ ] Static files loading

---

## 🚨 Common Issues

* **502 Bad Gateway** → uWSGI not running
* **Static files missing** → incorrect STATIC_ROOT
* **400 Bad Request** → ALLOWED_HOSTS issue
* **SSL issues** → certbot not configured properly

---

## 🎯 Result

Your **SmartSaver** Django application is now:

* ⚡ Production-ready
* 🔐 Secure (HTTPS)
* 🔄 Auto-updating
* 📈 Scalable

---
