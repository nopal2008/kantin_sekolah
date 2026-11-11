# Backend and database setup

## SQLite (default)

The application uses SQLite by default and stores its database in `db.sqlite3` in the project folder. No database server or extra configuration is needed.

From PowerShell in the project folder, install dependencies, apply migrations, and start the application:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py create_vendor
.\.venv\Scripts\python.exe manage.py runserver
```

Students can create accounts at `/daftar-siswa/`. Pedagang accounts are created by the school administrator with `create_vendor`; vendors must be members of the `vendor` group.

If `DB_ENGINE` is set to `mysql` in the terminal or environment, Django will use that instead of SQLite. Clear it to return to SQLite:

```powershell
Remove-Item Env:DB_ENGINE -ErrorAction SilentlyContinue
```

## Optional MySQL / MariaDB

To use MySQL or MariaDB, create a database named `kantin_db` with the `utf8mb4_unicode_ci` collation in phpMyAdmin. Create a separate application user and grant it access; do not use the MySQL root account for the running application. Django 6.0 requires MariaDB 10.6 or later.

In phpMyAdmin, select the **SQL** tab and run the following after replacing the password placeholder with a unique, strong password:

```sql
CREATE DATABASE IF NOT EXISTS kantin_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'kantin_app'@'127.0.0.1'
    IDENTIFIED BY 'REPLACE_WITH_A_STRONG_UNIQUE_PASSWORD';

GRANT ALL PRIVILEGES ON kantin_db.* TO 'kantin_app'@'127.0.0.1';
```

Set the connection settings in PowerShell before running migrations or starting Django:

```powershell
$env:DB_ENGINE = "mysql"
$env:DB_NAME = "kantin_db"
$env:DB_USER = "kantin_app"
$env:DB_PASSWORD = "the-same-strong-password"
$env:DB_HOST = "127.0.0.1"
$env:DB_PORT = "3306"
$env:DB_SSL_CA = "C:\path\to\mysql-ca.pem" # Optional; set for verified TLS connections
```

Use the same PowerShell window for the migration and server commands so Django receives the database credentials:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py create_vendor
.\.venv\Scripts\python.exe manage.py runserver
```

`migrate` creates tables; phpMyAdmin only creates the empty database. After migrations, refresh phpMyAdmin and expand `kantin_db`. If the development server was already running, stop it with `Ctrl+C` and restart it after setting the MySQL environment variables. Django reads these settings when the server starts.

## Vendor access

There are two login pages:

- **Admin:** open `http://127.0.0.1:8000/admin/` and sign in with the account created by `createsuperuser`.
- **Vendor:** sign in at `http://127.0.0.1:8000/login/` with a regular vendor account. Successful login redirects to `http://127.0.0.1:8000/vendor/`.

To create a vendor account, open another PowerShell terminal in the project folder and run:

```powershell
.\.venv\Scripts\python.exe manage.py create_vendor
```

Follow the prompts to enter the username, optional email, and password. Password input is hidden. Each vendor can then sign in at `/login/`; the app takes them to `/vendor/`. Alternatively, the superuser can create a regular user in Django admin and add them to the **vendor** group. Vendors are not Django staff or superusers. Use a separate username and password per vendor.

Vendors can create, edit, and delete their own menu entries, and can view only orders and item subtotals for their menu items. For each vendor's part of an order, they can confirm and process it, mark it ready for pickup, then mark it complete. Mixed-vendor orders keep each vendor's status separate; students see the progress for every vendor. Site superusers can access all vendors' data. A menu's owner can be assigned or changed by a superuser in **Menu** in Django admin. Menus without an assigned vendor are not listed in a vendor's menu page. Data in SQLite `db.sqlite3` is separate from MySQL and is not copied automatically when switching database engines.

## E-wallet payment verification

Students can choose GoPay, DANA, or OVO at checkout. The default destination for all three is `087817607300`, account name `Muhammad Fatih Nauval Azzidan`. Set `EWALLET_DESTINATION_NUMBER` and `EWALLET_ACCOUNT_NAME` in the environment to change the displayed destination.

This is a manual transfer workflow, not an automatic payment-gateway integration. Students transfer the order total, upload an image of the receipt, and may enter the provider's transaction code. A staff user reviews submitted receipts at `/verifikasi-pembayaran/`; only verified e-wallet orders become available for vendor processing. Rejected orders are cancelled and their reserved stock is restored. Uploaded receipts are stored outside the public media directory and are only served to the order owner and staff.

## Vouchers and menu summaries

The first voucher is created by the migration with a Rp40,000 minimum purchase and a Rp5,000 fixed discount. Active vouchers are shown on the student menu and at `/voucher/`; the best qualifying discount is applied automatically at checkout. The order and payment store the discounted payable total.

Staff can create, edit, activate, or deactivate vouchers at `/admin-voucher/`. The public menu also summarizes daily orders, revenue, and items sold for the current week and month, including average, median, mode, daily comparisons, and percentage changes against the matching previous period. Year-to-date order and revenue totals remain available.

Both vendor tables and the public menu use 10 records per page. Django admin lists are also limited to 10 records per page. Dashboard charts use Chart.js and require the browser to be able to load its pinned CDN script.

## Production settings and operational notes

Before deployment, set `DJANGO_SECRET_KEY` to a generated secret, set `DJANGO_DEBUG=false`, and provide the real comma-separated `DJANGO_ALLOWED_HOSTS`. Set `DJANGO_CSRF_TRUSTED_ORIGINS` for HTTPS origins and `DJANGO_SECURE_COOKIES=true` when TLS is enabled. Never commit production credentials or secret keys.

When MySQL is selected, it uses a short connection timeout, persistent connections with health checks, and UTF-8. Set `DB_SSL_CA` to verify the MySQL server certificate when TLS is enabled. Checkout writes are transactional and lock the cart, menu stock, and student balance while validating the order. The dashboard caches only per-user aggregate counts and chart totals for up to 60 seconds; it does not cache customer records or session data. The bounded in-process cache works without an additional cache server and cannot become an external availability dependency.

Database outages are not hidden by falling back to an empty or stale database. The application returns an error rather than accepting writes it cannot persist; configure the web server's health checks and restart policy, and monitor database availability. Back up `kantin_db` and uploaded media independently.

## Deploying on PythonAnywhere

The project uses Django 6.0, so choose a PythonAnywhere Python version supported by your account that is Python 3.12 or newer. `requirements.txt` is UTF-8 and pins the packages installed in this project's virtual environment. The existing `STATIC_ROOT` is `staticfiles/`; run `collectstatic` after installing the dependencies.

Before pushing to GitHub, review the files being committed. `.gitignore` excludes the local virtual environment, SQLite database, uploaded files, collected static files, and environment files. Use a private GitHub repository if the source contains information you do not want public. From the project folder, create the repository on GitHub and push with:

```bash
git init
git add .
git commit -m "Prepare Django app for deployment"
git branch -M main
git remote add origin https://github.com/GITHUB_USERNAME/REPOSITORY.git
git push -u origin main
```

In PythonAnywhere, create a **Manual configuration** web app using Python 3.12 or newer. In a Bash console, clone the repository and create a virtual environment using a Python version available in your account (replace `3.13` if necessary):

```bash
git clone https://github.com/GITHUB_USERNAME/REPOSITORY.git ~/kantin_sekolah
mkvirtualenv --python=/usr/bin/python3.13 kantin-sekolah
workon kantin-sekolah
pip install -r ~/kantin_sekolah/requirements.txt
cd ~/kantin_sekolah
```

Generate a secret key with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`. Keep it private. In the PythonAnywhere **Web** tab, open the WSGI configuration file and set the project path and production environment before `get_wsgi_application()`:

```python
import os
import sys

project_home = "/home/USERNAME/kantin_sekolah"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
os.environ["DJANGO_SECRET_KEY"] = "PASTE_THE_GENERATED_SECRET_KEY"
os.environ["DJANGO_DEBUG"] = "false"
os.environ["DJANGO_ALLOWED_HOSTS"] = "USERNAME.pythonanywhere.com"
os.environ["DJANGO_SECURE_COOKIES"] = "true"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Replace both `USERNAME` values and use the exact domain shown in the PythonAnywhere **Web** tab. Do not use a value such as `://pythonanywhere.com`; `ALLOWED_HOSTS` must contain the actual hostname, without a scheme. Do not commit this WSGI file or the generated key to the project repository.

In the **Web** tab, set the virtualenv path to `/home/USERNAME/.virtualenvs/kantin-sekolah`. Add these static files mappings:

| URL | Directory |
| --- | --- |
| `/static/` | `/home/USERNAME/kantin_sekolah/staticfiles` |
| `/media/` | `/home/USERNAME/kantin_sekolah/media` |

Do not add a static mapping for `private_uploads`; those receipt uploads must remain private and are served through the app's authorization checks. Create the upload directories and initialize the database from the Bash console:

```bash
mkdir -p ~/kantin_sekolah/media ~/kantin_sekolah/private_uploads
cd ~/kantin_sekolah
workon kantin-sekolah
export DJANGO_SECRET_KEY='THE_SAME_GENERATED_SECRET_KEY'
export DJANGO_DEBUG=false
export DJANGO_ALLOWED_HOSTS='USERNAME.pythonanywhere.com'
export DJANGO_SECURE_COOKIES=true
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

Use the same secret and hostname as in the WSGI configuration, then click **Reload** in the Web tab. The ignored SQLite database and uploaded files are not included in Git, so the deployed database starts fresh after migrations; transfer any required existing records and public media separately using a secure method. Back up the database and uploads independently.
