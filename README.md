# Wholesale Hub

A real Flask + MySQL wholesale ordering platform based on the supplied specification.

## Stack
- Python / Flask
- Flask-SQLAlchemy
- MySQL + PyMySQL
- HTML5 / CSS3 / JavaScript
- Flask sessions
- Werkzeug password hashing
- Chart.js for analytics

## 1. Create the database

Open MySQL:

```sql
CREATE DATABASE wholesale_hub CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## 2. Configure the connection

Windows PowerShell:

```powershell
$env:DATABASE_URL="mysql+pymysql://root:YOUR_PASSWORD@localhost/wholesale_hub"
$env:SECRET_KEY="replace-with-a-long-random-secret"
```

Or edit the default connection string in `app.py`.

## 3. Install packages

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Create tables

```powershell
flask --app app init-db
```

## 5. Optional demo admin

```powershell
flask --app app seed-admin
```

Demo admin:
- Email: `admin@wholesalehub.local`
- Password: `Admin@123`

Change it before production.

## 6. Run

```powershell
python app.py
```

Open:
`http://127.0.0.1:5000`

## Main workflow

1. Register a distributor.
2. Login as distributor.
3. Add products.
4. Register a shopkeeper.
5. Login as shopkeeper.
6. Search products.
7. Add products to cart.
8. Keep products from one distributor per order.
9. Place order.
10. Distributor receives the order through polling.
11. Distributor changes status: New → Confirmed → Packed → Out for Delivery → Delivered.
12. Shopkeeper sees updated status without manually refreshing.
13. Shopkeeper reviews delivered orders.

## Notes

- Order totals are calculated server-side.
- Product stock is checked again on the server before an order is committed.
- Orders are ownership-filtered by `shopkeeper_id` and `distributor_id`.
- Passwords are hashed.
- Search is performed through SQLAlchemy/MySQL, not by loading the whole database into JavaScript.
- The product image field is represented by a CSS placeholder because the supplied schema/spec did not require an image-upload column.
- For production deployment, add CSRF protection, HTTPS, secure cookies, rate limiting, database migrations (Alembic/Flask-Migrate), and stronger admin provisioning.
