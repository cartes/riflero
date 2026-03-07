# Copilot Instructions — PrintFlow / riflero.cl

## Commands

```bash
# Run development server
python manage.py runserver

# Run all tests
python manage.py test

# Run a single test class or method
python manage.py test tenant_app.tests.MyTestClass
python manage.py test tenant_app.tests.MyTestClass.test_method

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Seed data
python poblar_chile.py       # Chilean geographic data (Region → Provincia → Comuna)
python poblar_catalogo.py    # Master product catalog (ProductoGlobal)

# Celery worker (requires Redis running)
celery -A printflow_core worker -l info

# Collect static files
python manage.py collectstatic
```

Environment variables are loaded from `.env` via `python-decouple`. See `printflow_core/settings.py` for all supported variables (SECRET_KEY, DB_*, CELERY_BROKER_URL, MP_ACCESS_TOKEN, MP_SPLIT_FEE_PERCENTAGE).

## Architecture

**PrintFlow** is a multi-tenant SaaS marketplace for Chilean print shops (imprentas/talleres). Each shop gets a subdomain (`{subdominio}.riflero.cl`) with its own product catalog, orders, and competitive pricing radar.

### Multi-tenancy

Tenancy is handled entirely by `printflow_core/middleware.py` (`TenantMiddleware`):
- Extracts the subdomain from the HTTP `Host` header.
- Looks up the matching `Tienda` and injects it as `request.tenant`.
- Reserved subdomains (`www`, `app`, `admin`, `api`) yield `request.tenant = None`.

All views filter data by `tienda_id`. There are no separate databases or schemas — tenant isolation is enforced at the query level.

### App structure

The entire business logic lives in one app: **`tenant_app`**.

| File | Purpose |
|------|---------|
| `models.py` | 11 models — geography, shops, products, orders, pricing, scraping |
| `views.py` | 19 FBVs (+ 1 CBV) for public pages and the owner dashboard |
| `api_views.py` | Transparent Mercado Pago checkout + cascading commune dropdown |
| `webhooks.py` | Mercado Pago IPN listener (`/webhooks/mercadopago/`) |
| `tasks.py` | Celery task: Playwright-based competitor price scraping |
| `forms.py` | `RegistroTiendaForm` (shop registration) |
| `admin.py` | Heavily customised admin — `ejecutar_scraping_manual`, `aprobar_tiendas` actions |
| `services/mercadopago_service.py` | SDK wrapper for payment creation |

`printflow_core/` holds project config: `settings.py`, `urls.py`, `middleware.py`, `celery.py`.

### Data model highlights

- `Tienda` (shop/tenant) has a OneToOne with `User`, owns all `ProductoTienda`, `Orden`, and one `PrintScore`.
- `ProductoTienda.precio_final` is a **property**: `precio_base * (1 + margen_ganancia / 100)`.
- `ProductoGlobal` is the master catalog scraped from competitors; `ProductoTienda` can be linked to one via FK.
- A `post_save` signal on `RadarPrecio` automatically updates `ProductoTienda.precio_base` to the lowest scraped competitor price when `scraping_activado` is True on the shop.
- `Orden.estado_pago` choices: `'pendiente'`, `'completado'`, `'fallido'`, `'rechazado'`.
- `HistorialScraping` records audit logs for each scraping run (`'EXITO'`, `'ADVERTENCIA'`, `'ERROR'`).

### Payments (Mercado Pago)

- Each `Tienda` stores its own `mp_vendedor_id` and `mp_access_token` for split payments.
- `MP_SPLIT_FEE_PERCENTAGE` (env var) defines the platform fee.
- `Orden.mp_payment_id` is the key for webhook reconciliation; `external_reference` in MP = `orden.id`.
- `/api/checkout/` and `/webhooks/mercadopago/` use `@csrf_exempt` — this is intentional.

### Scraping (Playwright)

- `tasks.py` contains a single Celery task that drives headless Chromium via Playwright.
- Scraping is triggered from the Django admin via the `ejecutar_scraping_manual` action.
- Results are stored in `RadarPrecio` and logged in `HistorialScraping`.

## Key Conventions

- **Language:** All model `verbose_name`, help texts, form labels, and UI strings are in **Spanish (es-cl)**. Keep this consistent.
- **Views:** Prefer **function-based views**. The only CBV is `CustomPasswordChangeView`. Use `render()` for HTML responses and `JsonResponse()` for API/AJAX responses. No Django REST Framework.
- **Models:** Every model field should have a `verbose_name` and `help_text`. Use `gettext_lazy` for translatable strings. All models include `creado_en` / `actualizado_en` audit fields.
- **Prices:** Always use `DecimalField` for monetary values — never `FloatField`.
- **Indexes:** Add `Meta.indexes` on fields used in `filter()`, `order_by()`, or `select_related()` hot paths.
- **Protected routes:** Use `@login_required(login_url='login')`. Sensitive POST-only actions also get `@require_POST`.
- **Tenant safety:** Any queryset on `ProductoTienda`, `Orden`, or `RadarPrecio` **must** filter by `tienda` (via `request.tenant`) to prevent cross-shop data leaks.
- **Environment config:** All secrets and environment-specific values go through `decouple.config()` — never hardcode in `settings.py`.
- **Tailwind CSS:** Applied via widget `attrs` in forms and inline in templates. No separate CSS build step — Tailwind is loaded via CDN.
