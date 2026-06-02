# SmartSaver

SmartSaver is a Django price comparison website with API endpoints and a modern UI for finding better deals and cheaper alternatives.

## Features

- Product search by keyword, category, and brand
- Product price comparison across multiple platforms
- Cheaper alternatives endpoint and UI section
- Django admin for managing products, prices, and alerts
- Seed command with realistic sample data

## Tech

- Django 6
- Django REST Framework
- django-filter
- SQLite (default)

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run migrations:

```powershell
python manage.py makemigrations
python manage.py migrate
```

4. Seed sample data:

```powershell
python manage.py seed_data
```

5. Auto-add more products from multiple marketplaces with web image resolution:

```powershell
python manage.py auto_add_products --markets amazon,ebay,bestbuy,newegg --count-per-market 10
```

Marketplace aliases are supported, so this also works:

```powershell
python manage.py auto_add_products --markets amzon,eboy,bustbuy,newsage
```

7. Schedule daily automatic imports on Windows Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_auto_add_products_task.ps1 -StartTime "02:00"
```

This creates a task named `SmartSaver-AutoAddProducts` that runs
`scripts/run_auto_add_products.ps1` every day and writes logs to `logs/auto_add_products.log`.

To refresh product images and import recent news stories with images from public feeds:

```powershell
python manage.py refresh_product_images --process
python manage.py import_news_from_feeds --limit-per-feed 5
```

For weekly schedule (example: every Sunday at 02:00):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_auto_add_products_task.ps1 -TaskName "SmartSaver-AutoAddProducts" -Schedule Weekly -DayOfWeek Sunday -StartTime "02:00"
```

8. Start the server:

```powershell
python manage.py runserver
```

Open http://127.0.0.1:8000/

## API Endpoints

- `GET /api/search/?q=<query>&category=<category>&brand=<brand>`
- `GET /api/compare/<product_id>/`
- `GET /api/alternatives/<product_id>/`

## Admin Access

Create superuser:

```powershell
python manage.py createsuperuser
```

Then open `/admin/`.

## Notes

- For production, switch to PostgreSQL and configure Redis/Celery.
- Current sample integration uses seeded data for reliable MVP validation.

## Environment

Copy `.env.example` to `.env` (or set environment variables via your hosting platform). Important variables:

- `DJANGO_SECRET_KEY`: set a strong secret in production. If unset, the app will generate a secure local fallback for development.
- `SERPAPI_KEY`: optional API key for SerpAPI image results.
- `REDIS_URL`: URL for Redis when using `django_rq`.

On deployment, ensure `DEBUG=False` and `DJANGO_SECRET_KEY` is set.
