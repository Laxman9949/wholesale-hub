import os
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_, and_
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:1234@localhost/wholesale_hub"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

db = SQLAlchemy(app)
logging.basicConfig(level=logging.INFO)

STATUSES = ["New", "Confirmed", "Packed", "Out for Delivery", "Delivered", "Cancelled"]
PAYMENT_METHODS = ["Cash on Delivery", "UPI", "Bank Transfer"]


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    business_name = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(30), unique=True, nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)
    gst_number = db.Column(db.String(30))
    address = db.Column(db.String(255))
    city = db.Column(db.String(100), index=True)
    state = db.Column(db.String(100))
    pincode = db.Column(db.String(15))
    status = db.Column(db.String(20), default="active", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    products = db.relationship("Product", backref="distributor", lazy=True,
                               foreign_keys="Product.distributor_id")
    shop_orders = db.relationship("Order", backref="shopkeeper", lazy=True,
                                  foreign_keys="Order.shopkeeper_id")
    distributor_orders = db.relationship("Order", backref="order_distributor", lazy=True,
                                         foreign_keys="Order.distributor_id")


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    distributor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False, index=True)
    category = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text)
    cost_price = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False)
    discount = db.Column(db.Numeric(5, 2), default=0, nullable=False)
    stock = db.Column(db.Integer, default=0, nullable=False)
    unit = db.Column(db.String(50), default="piece")
    status = db.Column(db.String(20), default="active", nullable=False)
    manufacturing_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    order_items = db.relationship("OrderItem", backref="product", lazy=True)


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    shopkeeper_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    distributor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(30), default="New", nullable=False, index=True)
    payment_method = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    items = db.relationship("OrderItem", backref="order", lazy=True, cascade="all, delete-orphan")
    review = db.relationship("Review", backref="order", uselist=False, cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(12, 2), nullable=False)


class Wishlist(db.Model):
    __tablename__ = "wishlist"
    id = db.Column(db.Integer, primary_key=True)
    shopkeeper_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("shopkeeper_id", "product_id", name="uq_wishlist"),)


class Review(db.Model):
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, unique=True)
    shopkeeper_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    distributor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    review = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"success": False, "message": "Authentication required"}), 401
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            if user.role not in roles:
                if request.path.startswith("/api/"):
                    return jsonify({"success": False, "message": "Access denied"}), 403
                return render_template("error.html", code=403, message="You are not authorized to access this page."), 403
            if user.status != "active":
                session.clear()
                return jsonify({"success": False, "message": "Account is inactive"}), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def parse_decimal(value, default="0"):
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid numeric value")


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def user_dict(u):
    return {
        "id": u.id, "name": u.name, "business_name": u.business_name,
        "phone": u.phone, "email": u.email, "role": u.role,
        "gst_number": u.gst_number, "address": u.address, "city": u.city,
        "state": u.state, "pincode": u.pincode, "status": u.status,
        "created_at": u.created_at.isoformat() if u.created_at else None
    }


def product_dict(p):
    effective = Decimal(p.price or 0) - (Decimal(p.price or 0) * Decimal(p.discount or 0) / Decimal(100))
    return {
        "id": p.id, "distributor_id": p.distributor_id, "name": p.name,
        "category": p.category, "description": p.description or "",
        "cost_price": float(p.cost_price or 0), "price": float(p.price or 0),
        "discount": float(p.discount or 0), "final_price": float(effective),
        "stock": p.stock, "unit": p.unit, "status": p.status,
        "manufacturing_date": p.manufacturing_date.isoformat() if p.manufacturing_date else None,
        "expiry_date": p.expiry_date.isoformat() if p.expiry_date else None,
        "distributor": user_dict(p.distributor)
    }


def order_dict(o, include_items=True):
    data = {
        "id": o.id, "shopkeeper_id": o.shopkeeper_id, "distributor_id": o.distributor_id,
        "shopkeeper": user_dict(o.shopkeeper) if o.shopkeeper else None,
        "distributor": user_dict(o.order_distributor) if o.order_distributor else None,
        "total_amount": float(o.total_amount),
        "status": o.status, "payment_method": o.payment_method,
        "created_at": o.created_at.isoformat(), "updated_at": o.updated_at.isoformat()
    }
    if include_items:
        data["items"] = [{
            "id": i.id, "product_id": i.product_id, "product_name": i.product.name,
            "quantity": i.quantity, "price": float(i.price),
            "subtotal": float(Decimal(i.price) * i.quantity)
        } for i in o.items]
    return data


def validate_registration(form, role):
    required = ["name", "business_name", "phone", "email", "password", "gst_number",
                "address", "city", "state", "pincode"]
    missing = [x for x in required if not str(form.get(x, "")).strip()]
    if missing:
        return "Missing fields: " + ", ".join(missing)
    email = form["email"].strip().lower()
    if User.query.filter(func.lower(User.email) == email).first():
        return "Email already registered."
    if User.query.filter_by(phone=form["phone"].strip()).first():
        return "Phone already registered."
    if len(form["password"]) < 6:
        return "Password must contain at least 6 characters."
    if role not in {"admin", "distributor", "shopkeeper"}:
        return "Invalid role."
    return None


def create_user(form, role):
    err = validate_registration(form, role)
    if err:
        return None, err
    u = User(
        name=form["name"].strip(),
        business_name=form["business_name"].strip(),
        phone=form["phone"].strip(),
        email=form["email"].strip().lower(),
        password=generate_password_hash(form["password"]),
        role=role,
        gst_number=form["gst_number"].strip(),
        address=form["address"].strip(),
        city=form["city"].strip(),
        state=form["state"].strip(),
        pincode=form["pincode"].strip(),
        status="active"
    )
    db.session.add(u)
    db.session.commit()
    return u, None


@app.route("/")
def index():
    user = current_user()
    if user:
        return redirect(url_for(f"{user.role}_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email).first()
        if user and user.status == "active" and check_password_hash(user.password, password):
            session.clear()
            session["user_id"] = user.id
            session["name"] = user.name
            session["email"] = user.email
            session["role"] = user.role
            flash("Login successful.", "success")
            return redirect(url_for(f"{user.role}_dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        _, err = create_user(request.form, "shopkeeper")
        if err:
            flash(err, "danger")
        else:
            flash("Shopkeeper registration successful. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html", role="shopkeeper", title="Shopkeeper Registration")


@app.route("/distributor/register", methods=["GET", "POST"])
def distributor_register():
    if request.method == "POST":
        _, err = create_user(request.form, "distributor")
        if err:
            flash(err, "danger")
        else:
            flash("Distributor registration successful. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("distributor_register.html")


@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    if request.method == "POST":
        _, err = create_user(request.form, "admin")
        if err:
            flash(err, "danger")
        else:
            flash("Admin registration successful. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("admin_register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    stats = {
        "users": User.query.count(),
        "distributors": User.query.filter_by(role="distributor").count(),
        "shopkeepers": User.query.filter_by(role="shopkeeper").count(),
        "products": Product.query.count(),
        "orders": Order.query.count(),
        "sales": float(db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(Order.status != "Cancelled").scalar() or 0)
    }
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    return render_template("admin_dashboard.html", stats=stats, recent_orders=recent_orders)


@app.route("/distributor/dashboard")
@role_required("distributor")
def distributor_dashboard():
    uid = session["user_id"]
    base = Order.query.filter_by(distributor_id=uid)
    products = Product.query.filter_by(distributor_id=uid)
    stats = {
        "total_orders": base.count(),
        "new_orders": base.filter_by(status="New").count(),
        "confirmed": base.filter_by(status="Confirmed").count(),
        "packed": base.filter_by(status="Packed").count(),
        "out_for_delivery": base.filter_by(status="Out for Delivery").count(),
        "delivered": base.filter_by(status="Delivered").count(),
        "cancelled": base.filter_by(status="Cancelled").count(),
        "total_products": products.count(),
        "low_stock": products.filter(Product.stock > 0, Product.stock <= 10, Product.status == "active").count(),
        "total_sales": float(db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(Order.distributor_id == uid, Order.status != "Cancelled").scalar() or 0),
        "monthly_sales": float(db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
            Order.distributor_id == uid, Order.status != "Cancelled",
            Order.created_at >= datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ).scalar() or 0)
    }
    recent = base.order_by(Order.created_at.desc()).limit(10).all()
    return render_template("distributor_dashboard.html", stats=stats, recent_orders=recent,
                           user=current_user(), statuses=STATUSES)


@app.route("/shopkeeper/dashboard")
@role_required("shopkeeper")
def shopkeeper_dashboard():
    uid = session["user_id"]
    orders = Order.query.filter_by(shopkeeper_id=uid)
    stats = {
        "products": Product.query.filter_by(status="active").filter(Product.stock > 0).count(),
        "cart_items": sum(int(x.get("quantity", 0)) for x in session.get("cart", [])),
        "orders": orders.count(),
        "pending": orders.filter(Order.status.in_(["New", "Confirmed", "Packed", "Out for Delivery"])).count(),
        "delivered": orders.filter_by(status="Delivered").count(),
        "wishlist": Wishlist.query.filter_by(shopkeeper_id=uid).count()
    }
    return render_template("shopkeeper_dashboard.html", stats=stats, user=current_user())


@app.route("/orders/<int:order_id>")
@role_required("admin", "distributor", "shopkeeper")
def order_details(order_id):
    user = current_user()
    order = db.session.get(Order, order_id)
    if not order:
        return render_template("error.html", code=404, message="Order not found."), 404
    if user.role == "distributor" and order.distributor_id != user.id:
        return render_template("error.html", code=403, message="Not your order."), 403
    if user.role == "shopkeeper" and order.shopkeeper_id != user.id:
        return render_template("error.html", code=403, message="Not your order."), 403
    return render_template("order_details.html", order=order, statuses=STATUSES)


# ---------- Distributor APIs ----------

@app.route("/api/distributor/orders")
@role_required("distributor")
def distributor_orders_api():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    query = Order.query.filter_by(distributor_id=session["user_id"])
    if q:
        pattern = f"%{q}%"
        query = query.join(User, Order.shopkeeper_id == User.id).filter(or_(
            func.cast(Order.id, db.String).ilike(pattern),
            User.name.ilike(pattern), User.business_name.ilike(pattern),
            User.phone.ilike(pattern)
        ))
    if status:
        query = query.filter(Order.status == status)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    try:
        if start_date:
            query = query.filter(Order.created_at >= datetime.strptime(start_date, "%Y-%m-%d"))
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Order.created_at < end_dt)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid date. Use YYYY-MM-DD."}), 400
    pagination = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"success": True, "count": pagination.total,
                    "page": page, "pages": pagination.pages,
                    "orders": [order_dict(o, False) for o in pagination.items]})


@app.route("/api/distributor/orders/search")
@role_required("distributor")
def distributor_orders_search():
    return distributor_orders_api()


@app.route("/api/distributor/order/<int:order_id>/status", methods=["POST"])
@role_required("distributor")
def distributor_update_order_status(order_id):
    order = db.session.get(Order, order_id)
    if not order or order.distributor_id != session["user_id"]:
        return jsonify({"success": False, "message": "Order not found"}), 404
    new_status = request.get_json(silent=True, force=True).get("status") if request.is_json else request.form.get("status")
    if new_status not in STATUSES:
        return jsonify({"success": False, "message": "Invalid status"}), 400
    allowed = {
        "New": {"Confirmed", "Cancelled"},
        "Confirmed": {"Packed"},
        "Packed": {"Out for Delivery"},
        "Out for Delivery": {"Delivered"},
        "Delivered": set(),
        "Cancelled": set()
    }
    if new_status not in allowed.get(order.status, set()):
        return jsonify({"success": False, "message": f"Cannot change {order.status} to {new_status}"}), 400
    order.status = new_status
    order.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "order": order_dict(order, False)})


@app.route("/api/distributor/products")
@role_required("distributor")
def distributor_products():
    q = request.args.get("q", "").strip()
    query = Product.query.filter_by(distributor_id=session["user_id"])
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(pattern), Product.category.ilike(pattern)))
    products = query.order_by(Product.created_at.desc()).all()
    return jsonify({"success": True, "count": len(products), "products": [product_dict(p) for p in products]})


@app.route("/api/distributor/product/add", methods=["POST"])
@role_required("distributor")
def add_product():
    data = request.form if not request.is_json else (request.get_json(silent=True) or {})
    try:
        name, category = str(data.get("name", "")).strip(), str(data.get("category", "")).strip()
        if not name or not category:
            return jsonify({"success": False, "message": "Product name and category are required"}), 400
        price = parse_decimal(data.get("price"))
        cost = parse_decimal(data.get("cost_price"))
        discount = parse_decimal(data.get("discount"))
        stock = int(data.get("stock", 0))
        if price < 0 or cost < 0 or discount < 0 or discount > 100 or stock < 0:
            raise ValueError("Invalid product values")
        p = Product(
            distributor_id=session["user_id"], name=name, category=category,
            description=str(data.get("description", "")).strip(), cost_price=cost,
            price=price, discount=discount, stock=stock,
            unit=str(data.get("unit", "piece")).strip() or "piece",
            status="active", manufacturing_date=parse_date(data.get("manufacturing_date")),
            expiry_date=parse_date(data.get("expiry_date"))
        )
        db.session.add(p)
        db.session.commit()
        return jsonify({"success": True, "product": product_dict(p)})
    except (ValueError, TypeError) as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 400


@app.route("/api/distributor/product/<int:product_id>", methods=["PUT", "DELETE"])
@role_required("distributor")
def manage_product(product_id):
    p = db.session.get(Product, product_id)
    if not p or p.distributor_id != session["user_id"]:
        return jsonify({"success": False, "message": "Product not found"}), 404
    if request.method == "DELETE":
        if OrderItem.query.filter_by(product_id=p.id).first():
            p.status = "inactive"
        else:
            db.session.delete(p)
        db.session.commit()
        return jsonify({"success": True, "message": "Product deleted/deactivated"})
    data = request.get_json(silent=True) or {}
    try:
        for field in ["name", "category", "description", "unit", "status"]:
            if field in data:
                setattr(p, field, str(data[field]).strip())
        if "price" in data: p.price = parse_decimal(data["price"])
        if "cost_price" in data: p.cost_price = parse_decimal(data["cost_price"])
        if "discount" in data: p.discount = parse_decimal(data["discount"])
        if "stock" in data: p.stock = int(data["stock"])
        if "manufacturing_date" in data: p.manufacturing_date = parse_date(data["manufacturing_date"])
        if "expiry_date" in data: p.expiry_date = parse_date(data["expiry_date"])
        db.session.commit()
        return jsonify({"success": True, "product": product_dict(p)})
    except (ValueError, TypeError) as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 400


@app.route("/api/distributor/inventory")
@role_required("distributor")
def distributor_inventory():
    q = request.args.get("q", "").strip()
    filt = request.args.get("filter", "all")
    products = Product.query.filter_by(distributor_id=session["user_id"])
    if q:
        products = products.filter(Product.name.ilike(f"%{q}%"))
    products = products.all()
    today = date.today()
    def inventory_status(p):
        if p.expiry_date and p.expiry_date < today: return "Expired"
        if p.stock == 0: return "Out of Stock"
        if p.stock <= 10: return "Low Stock"
        if p.expiry_date and p.expiry_date <= today + timedelta(days=30): return "Expiring Soon"
        return "Available"
    if filt != "all":
        products = [p for p in products if inventory_status(p).lower().replace(" ", "_") == filt.lower().replace(" ", "_")]
    result = [{"product": product_dict(p), "inventory_status": inventory_status(p)} for p in products]
    return jsonify({"success": True, "count": len(result), "products": result})


@app.route("/api/distributor/shopkeepers")
@role_required("distributor")
def distributor_shopkeepers():
    q = request.args.get("q", "").strip()
    uid = session["user_id"]
    shop_ids = db.session.query(Order.shopkeeper_id).filter(Order.distributor_id == uid).distinct().subquery()
    query = User.query.filter(User.role == "shopkeeper", User.id.in_(shop_ids))
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(User.name.ilike(pattern), User.business_name.ilike(pattern),
                                 User.phone.ilike(pattern), User.city.ilike(pattern), User.email.ilike(pattern)))
    shops = query.all()
    result = []
    for s in shops:
        orders = Order.query.filter_by(distributor_id=uid, shopkeeper_id=s.id)
        result.append({**user_dict(s), "number_of_orders": orders.count(),
                       "total_purchase_amount": float(db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
                           Order.distributor_id == uid, Order.shopkeeper_id == s.id, Order.status != "Cancelled").scalar() or 0),
                       "last_order_date": (orders.order_by(Order.created_at.desc()).first().created_at.isoformat()
                                           if orders.first() else None)})
    return jsonify({"success": True, "count": len(result), "shopkeepers": result})


@app.route("/api/distributor/analysis")
@role_required("distributor")
def distributor_analysis():
    uid = session["user_id"]
    orders = Order.query.filter(Order.distributor_id == uid, Order.status != "Cancelled")
    total_sales = float(db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).filter(
        Order.distributor_id == uid, Order.status != "Cancelled").scalar() or 0)
    delivered = orders.filter(Order.status == "Delivered").count()
    pending = orders.filter(Order.status.in_(["New", "Confirmed", "Packed", "Out for Delivery"])).count()
    quantity = int(db.session.query(func.coalesce(func.sum(OrderItem.quantity), 0))
                   .join(Order, OrderItem.order_id == Order.id)
                   .filter(Order.distributor_id == uid, Order.status != "Cancelled").scalar() or 0)
    rows = db.session.query(func.date_format(Order.created_at, "%Y-%m").label("month"),
                            func.sum(Order.total_amount).label("sales")).filter(
        Order.distributor_id == uid, Order.status != "Cancelled"
    ).group_by(func.date_format(Order.created_at, "%Y-%m")).order_by("month").all()
    status_rows = db.session.query(Order.status, func.count(Order.id)).filter(
        Order.distributor_id == uid).group_by(Order.status).all()
    product_rows = db.session.query(Product.name, func.sum(OrderItem.quantity)).join(
        OrderItem, OrderItem.product_id == Product.id).join(Order, Order.id == OrderItem.order_id).filter(
            Order.distributor_id == uid, Order.status != "Cancelled"
        ).group_by(Product.id).order_by(func.sum(OrderItem.quantity).desc()).limit(10).all()
    return jsonify({"success": True, "total_sales": total_sales, "total_revenue": total_sales,
                    "total_orders": orders.count(), "delivered_orders": delivered,
                    "pending_orders": pending, "quantity_sold": quantity,
                    "monthly_sales": [{"month": m, "sales": float(s)} for m, s in rows],
                    "status_chart": [{"status": s, "count": c} for s, c in status_rows],
                    "product_sales": [{"product": n, "quantity": int(q)} for n, q in product_rows]})


# ---------- Shopkeeper APIs ----------

def product_query_for_shopkeeper(args):
    query = Product.query.join(User, Product.distributor_id == User.id).filter(
        Product.status == "active", User.status == "active"
    )
    q = args.get("q", "").strip()
    category = args.get("category", "").strip()
    distributor = args.get("distributor", "").strip()
    city = args.get("city", "").strip()
    min_price = args.get("min_price", "").strip()
    max_price = args.get("max_price", "").strip()
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(pattern), Product.category.ilike(pattern),
                                 User.name.ilike(pattern), User.business_name.ilike(pattern)))
    if category: query = query.filter(Product.category.ilike(f"%{category}%"))
    if distributor: query = query.filter(or_(User.name.ilike(f"%{distributor}%"),
                                             User.business_name.ilike(f"%{distributor}%")))
    if city: query = query.filter(User.city.ilike(f"%{city}%"))
    if min_price:
        query = query.filter(Product.price >= parse_decimal(min_price))
    if max_price:
        query = query.filter(Product.price <= parse_decimal(max_price))
    sort = args.get("sort", "")
    if sort == "price_asc": query = query.order_by(Product.price.asc())
    elif sort == "price_desc": query = query.order_by(Product.price.desc())
    else: query = query.order_by(Product.created_at.desc())
    return query


@app.route("/api/shopkeeper/products")
@role_required("shopkeeper")
def shopkeeper_products():
    try:
        query = product_query_for_shopkeeper(request.args)
        page = max(int(request.args.get("page", 1)), 1)
        per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        return jsonify({"success": True, "count": pagination.total, "page": page,
                        "pages": pagination.pages, "products": [product_dict(p) for p in pagination.items]})
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400


@app.route("/api/shopkeeper/products/search")
@role_required("shopkeeper")
def shopkeeper_products_search():
    return shopkeeper_products()


@app.route("/api/shopkeeper/distributors")
@role_required("shopkeeper")
def shopkeeper_distributors():
    q = request.args.get("q", "").strip()
    query = User.query.filter_by(role="distributor", status="active")
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(func.cast(User.id, db.String).ilike(pattern),
                                 User.name.ilike(pattern), User.business_name.ilike(pattern),
                                 User.city.ilike(pattern), User.phone.ilike(pattern)))
    distributors = query.order_by(User.business_name.asc()).all()
    result = []
    for d in distributors:
        result.append({**user_dict(d),
                       "available_products": Product.query.filter_by(distributor_id=d.id, status="active").filter(Product.stock > 0).count(),
                       "total_products": Product.query.filter_by(distributor_id=d.id, status="active").count()})
    return jsonify({"success": True, "count": len(result), "distributors": result})


@app.route("/api/shopkeeper/distributors/search")
@role_required("shopkeeper")
def shopkeeper_distributors_search():
    return shopkeeper_distributors()


@app.route("/api/shopkeeper/cart", methods=["GET", "POST", "DELETE"])
@role_required("shopkeeper")
def shopkeeper_cart():
    cart = session.get("cart", [])
    if request.method == "GET":
        items = []
        total = Decimal("0")
        for x in cart:
            p = db.session.get(Product, int(x["product_id"]))
            if not p: continue
            final = Decimal(p.price) - Decimal(p.price) * Decimal(p.discount or 0) / Decimal(100)
            qty = int(x["quantity"])
            items.append({"product": product_dict(p), "quantity": qty,
                          "subtotal": float(final * qty)})
            total += final * qty
        return jsonify({"success": True, "items": items, "total": float(total)})
    if request.method == "DELETE":
        session.pop("cart", None)
        return jsonify({"success": True, "message": "Cart cleared"})
    data = request.get_json(silent=True) or {}
    pid = int(data.get("product_id", 0))
    qty = int(data.get("quantity", 1))
    if qty <= 0: return jsonify({"success": False, "message": "Quantity must be positive"}), 400
    p = db.session.get(Product, pid)
    if not p or p.status != "active": return jsonify({"success": False, "message": "Product unavailable"}), 404
    if p.stock < qty: return jsonify({"success": False, "message": "Insufficient stock"}), 400
    if cart:
        current = db.session.get(Product, int(cart[0]["product_id"]))
        if current and current.distributor_id != p.distributor_id:
            return jsonify({"success": False, "message": "Products from different distributors cannot be in one order."}), 400
    found = next((x for x in cart if int(x["product_id"]) == pid), None)
    if found:
        if int(found["quantity"]) + qty > p.stock:
            return jsonify({"success": False, "message": "Insufficient stock"}), 400
        found["quantity"] = int(found["quantity"]) + qty
    else:
        cart.append({"product_id": pid, "quantity": qty})
    session["cart"] = cart
    session.modified = True
    return jsonify({"success": True, "message": "Added to cart", "cart_count": sum(x["quantity"] for x in cart)})


@app.route("/api/shopkeeper/cart/item/<int:product_id>", methods=["PUT", "DELETE"])
@role_required("shopkeeper")
def shopkeeper_cart_item(product_id):
    cart = session.get("cart", [])
    item = next((x for x in cart if int(x["product_id"]) == product_id), None)
    if not item:
        return jsonify({"success": False, "message": "Item not in cart"}), 404
    if request.method == "DELETE":
        cart.remove(item)
    else:
        qty = int((request.get_json(silent=True) or {}).get("quantity", 1))
        p = db.session.get(Product, product_id)
        if not p or qty < 1 or qty > p.stock:
            return jsonify({"success": False, "message": "Invalid quantity"}), 400
        item["quantity"] = qty
    session["cart"] = cart
    session.modified = True
    return jsonify({"success": True, "cart": cart})


@app.route("/api/shopkeeper/place-order", methods=["POST"])
@role_required("shopkeeper")
def place_order():
    data = request.get_json(silent=True) or {}
    cart = session.get("cart", [])
    if not cart:
        return jsonify({"success": False, "message": "Cart is empty"}), 400
    payment = str(data.get("payment_method", "")).strip()
    if payment not in PAYMENT_METHODS:
        return jsonify({"success": False, "message": "Invalid payment method"}), 400

    try:
        products = []
        distributor_id = None
        total = Decimal("0")
        for item in cart:
            p = db.session.get(Product, int(item["product_id"]))
            qty = int(item["quantity"])
            if not p or p.status != "active":
                raise ValueError("A product is unavailable.")
            if p.stock < qty:
                raise ValueError(f"Insufficient stock for {p.name}.")
            if distributor_id is None:
                distributor_id = p.distributor_id
            if p.distributor_id != distributor_id:
                raise ValueError("Products from different distributors cannot be in one order.")
            effective = Decimal(p.price) - Decimal(p.price) * Decimal(p.discount or 0) / Decimal(100)
            total += effective * qty
            products.append((p, qty, effective))
        order = Order(shopkeeper_id=session["user_id"], distributor_id=distributor_id,
                      total_amount=total, status="New", payment_method=payment)
        db.session.add(order)
        db.session.flush()
        for p, qty, effective in products:
            db.session.add(OrderItem(order_id=order.id, product_id=p.id, quantity=qty, price=effective))
            p.stock -= qty
        db.session.commit()
        session.pop("cart", None)
        return jsonify({"success": True, "order_id": order.id, "total": float(total)})
    except Exception as e:
        db.session.rollback()
        logging.exception("Order creation failed")
        return jsonify({"success": False, "message": str(e) if isinstance(e, ValueError) else "Unable to place order"}), 400


@app.route("/api/shopkeeper/orders")
@role_required("shopkeeper")
def shopkeeper_orders():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    query = Order.query.filter_by(shopkeeper_id=session["user_id"]).join(
        User, Order.distributor_id == User.id)
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(func.cast(Order.id, db.String).ilike(pattern),
                                 User.name.ilike(pattern), User.business_name.ilike(pattern)))
    if status:
        query = query.filter(Order.status == status)
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    try:
        if start_date:
            query = query.filter(Order.created_at >= datetime.strptime(start_date, "%Y-%m-%d"))
        if end_date:
            query = query.filter(Order.created_at < datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1))
    except ValueError:
        return jsonify({"success": False, "message": "Invalid date. Use YYYY-MM-DD."}), 400
    orders = query.order_by(Order.created_at.desc()).all()
    return jsonify({"success": True, "count": len(orders), "orders": [order_dict(o, False) for o in orders]})


@app.route("/api/shopkeeper/order/<int:order_id>")
@role_required("shopkeeper")
def shopkeeper_order_detail(order_id):
    o = db.session.get(Order, order_id)
    if not o or o.shopkeeper_id != session["user_id"]:
        return jsonify({"success": False, "message": "Order not found"}), 404
    return jsonify({"success": True, "order": order_dict(o)})


@app.route("/api/shopkeeper/wishlist/add", methods=["POST"])
@role_required("shopkeeper")
def wishlist_add():
    data = request.get_json(silent=True) or {}
    p = db.session.get(Product, int(data.get("product_id", 0)))
    if not p or p.status != "active":
        return jsonify({"success": False, "message": "Product unavailable"}), 404
    exists = Wishlist.query.filter_by(shopkeeper_id=session["user_id"], product_id=p.id).first()
    if not exists:
        db.session.add(Wishlist(shopkeeper_id=session["user_id"], product_id=p.id))
        db.session.commit()
    return jsonify({"success": True, "message": "Added to wishlist"})


@app.route("/api/shopkeeper/wishlist")
@role_required("shopkeeper")
def wishlist():
    q = request.args.get("q", "").strip()
    query = Wishlist.query.filter_by(shopkeeper_id=session["user_id"]).join(Product)
    if q: query = query.filter(Product.name.ilike(f"%{q}%"))
    rows = query.order_by(Wishlist.created_at.desc()).all()
    return jsonify({"success": True, "count": len(rows),
                    "wishlist": [{"id": x.id, "product": product_dict(x.product)} for x in rows]})


@app.route("/api/shopkeeper/wishlist/remove", methods=["POST"])
@role_required("shopkeeper")
def wishlist_remove():
    data = request.get_json(silent=True) or {}
    row = Wishlist.query.filter_by(shopkeeper_id=session["user_id"],
                                   product_id=int(data.get("product_id", 0))).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return jsonify({"success": True, "message": "Removed from wishlist"})


@app.route("/api/shopkeeper/review", methods=["POST"])
@role_required("shopkeeper")
def submit_review():
    data = request.get_json(silent=True) or {}
    order = db.session.get(Order, int(data.get("order_id", 0)))
    try:
        rating = int(data.get("rating", 0))
    except ValueError:
        rating = 0
    if not order or order.shopkeeper_id != session["user_id"]:
        return jsonify({"success": False, "message": "Order not found"}), 404
    if order.status != "Delivered":
        return jsonify({"success": False, "message": "Only delivered orders can be reviewed"}), 400
    if not 1 <= rating <= 5:
        return jsonify({"success": False, "message": "Rating must be 1-5"}), 400
    if order.review:
        return jsonify({"success": False, "message": "Order already reviewed"}), 400
    review = Review(order_id=order.id, shopkeeper_id=order.shopkeeper_id,
                    distributor_id=order.distributor_id, rating=rating,
                    review=str(data.get("review", "")).strip())
    db.session.add(review)
    db.session.commit()
    return jsonify({"success": True, "message": "Review submitted"})


# ---------- Generic/admin search ----------

@app.route("/api/search")
@role_required("admin", "distributor", "shopkeeper")
def global_search():
    q = request.args.get("q", "").strip()
    typ = request.args.get("type", "all")
    if not q:
        return jsonify({"success": True, "count": 0, "results": []})
    pattern = f"%{q}%"
    results = []
    if typ in ("all", "products"):
        pq = Product.query.filter(or_(Product.name.ilike(pattern), Product.category.ilike(pattern)))
        if session["role"] == "distributor": pq = pq.filter_by(distributor_id=session["user_id"])
        for p in pq.limit(20).all():
            results.append({"type": "product", "id": p.id, "title": p.name, "subtitle": p.category})
    if typ in ("all", "distributors", "shopkeepers"):
        roles = ["distributor", "shopkeeper"] if typ == "all" else [typ[:-1]]
        for u in User.query.filter(User.role.in_(roles), or_(User.name.ilike(pattern),
                    User.business_name.ilike(pattern), User.phone.ilike(pattern),
                    User.city.ilike(pattern))).limit(20).all():
            results.append({"type": u.role, "id": u.id, "title": u.name, "subtitle": u.business_name})
    if typ in ("all", "orders"):
        oq = Order.query
        if session["role"] == "distributor": oq = oq.filter_by(distributor_id=session["user_id"])
        if session["role"] == "shopkeeper": oq = oq.filter_by(shopkeeper_id=session["user_id"])
        oq = oq.filter(or_(func.cast(Order.id, db.String).ilike(pattern),
                           Order.status.ilike(pattern), Order.payment_method.ilike(pattern)))
        for o in oq.limit(20).all():
            results.append({"type": "order", "id": o.id, "title": f"Order #{o.id}", "subtitle": o.status})
    return jsonify({"success": True, "count": len(results), "results": results})


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": "Resource not found"}), 404
    return render_template("error.html", code=404, message="The requested page was not found."), 404


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": "Forbidden"}), 403
    return render_template("error.html", code=403, message="Access denied."), 403


@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    logging.exception("Internal server error")
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "message": "Internal server error"}), 500
    return render_template("error.html", code=500, message="Something went wrong. Please try again."), 500


@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("Database tables created.")


@app.cli.command("seed-admin")
def seed_admin():
    if User.query.filter_by(role="admin").first():
        print("An admin already exists.")
        return
    u = User(name="System Admin", business_name="Wholesale Hub",
             phone="9999999999", email="admin@wholesalehub.local",
             password=generate_password_hash("Admin@123"),
             role="admin", gst_number="ADMIN-GST", address="Head Office",
             city="Hyderabad", state="Telangana", pincode="500001")
    db.session.add(u)
    db.session.commit()
    print("Admin created: admin@wholesalehub.local / Admin@123")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
