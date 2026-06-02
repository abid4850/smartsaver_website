# Deploy HTTPS with NGINX + Let's Encrypt (smartsaver.abidnexus.com)

This guide assumes Ubuntu/Debian and a running Django app at `127.0.0.1:8000`.

## 1) DNS

Create an `A` record:

- Host: `smartsaver`
- Value: `<your_server_public_ip>`
- Domain: `abidnexus.com`

Verify:

```bash
dig +short smartsaver.abidnexus.com
```

## 2) Install NGINX + Certbot

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

## 3) Prepare webroot for ACME challenge

```bash
sudo mkdir -p /var/www/certbot/.well-known/acme-challenge
sudo chown -R www-data:www-data /var/www/certbot
```

## 4) Install NGINX site config

Copy `deployment/nginx/smartsaver.abidnexus.com.conf` to:

```bash
sudo cp deployment/nginx/smartsaver.abidnexus.com.conf /etc/nginx/sites-available/smartsaver.abidnexus.com
sudo ln -s /etc/nginx/sites-available/smartsaver.abidnexus.com /etc/nginx/sites-enabled/smartsaver.abidnexus.com
sudo nginx -t
sudo systemctl reload nginx
```

If default site conflicts, disable it:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

## 5) Issue certificate

Use webroot mode first (safe and explicit):

```bash
sudo certbot certonly --webroot \
  -w /var/www/certbot \
  -d smartsaver.abidnexus.com \
  --email you@abidnexus.com \
  --agree-tos \
  --no-eff-email
```

Then test and reload NGINX:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 6) Enable auto-renew

```bash
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
sudo certbot renew --dry-run
```

## 7) Django production env vars

Set these in your process manager/environment:

```bash
DJANGO_SECRET_KEY=<strong-random-secret>
DEBUG=False
SITE_URL=https://smartsaver.abidnexus.com
SITE_NAME=SmartSaver
ALLOWED_HOSTS=smartsaver.abidnexus.com,localhost,127.0.0.1
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
```

## 8) Static/media paths expected by NGINX

The included NGINX config uses:

- `/var/www/smartsaver/static/`
- `/var/www/smartsaver/media/`

Collect static files to match that path (adjust if your path differs):

```bash
python manage.py collectstatic --noinput
```

## 9) Final checks

```bash
curl -I http://smartsaver.abidnexus.com
curl -I https://smartsaver.abidnexus.com
```

Expected:

- HTTP returns `301` to HTTPS
- HTTPS returns `200` and includes security headers

## 10) Run Django with systemd (Gunicorn + optional RQ worker)

Install app dependencies in your server venv first:

```bash
cd /var/www/smartsaver/current
/var/www/smartsaver/venv/bin/pip install -r requirements.txt
```

Install env file:

```bash
sudo mkdir -p /etc/smartsaver
sudo cp deployment/systemd/smartsaver.env.example /etc/smartsaver/smartsaver.env
sudo chown root:www-data /etc/smartsaver/smartsaver.env
sudo chmod 640 /etc/smartsaver/smartsaver.env
```

Install and start web service:

```bash
sudo cp deployment/systemd/smartsaver-gunicorn.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smartsaver-gunicorn
sudo systemctl start smartsaver-gunicorn
sudo systemctl status smartsaver-gunicorn --no-pager
```

Optional: start background worker (for `django_rq` jobs):

```bash
sudo cp deployment/systemd/smartsaver-rqworker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smartsaver-rqworker
sudo systemctl start smartsaver-rqworker
sudo systemctl status smartsaver-rqworker --no-pager
```

Useful logs:

```bash
sudo journalctl -u smartsaver-gunicorn -f
sudo journalctl -u smartsaver-rqworker -f
```
