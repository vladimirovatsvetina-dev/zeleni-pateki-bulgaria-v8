import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from hmac import compare_digest
from pathlib import Path
from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
DB_PATH = Path("tourism.db")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT NOT NULL,
                price REAL NOT NULL CHECK(price >= 0),
                capacity INTEGER NOT NULL CHECK(capacity > 0),

                latitude REAL,
                longitude REAL,
                map_query TEXT,

                image_url TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK(is_active IN (0, 1))
                )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS booking_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tour_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                participants INTEGER NOT NULL
                    CHECK(participants BETWEEN 1 AND 10),
                preferred_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tour_id) REFERENCES tours(id)
            )
        """)
        count = connection.execute("SELECT COUNT(*) FROM tours").fetchone()[0]

        if count == 0:
            connection.executemany(
                """
                INSERT INTO tours
                    (code, name, location, description,
                    price, capacity,
                    latitude, longitude, map_query,
                    image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "rodopi",
                        "Уикенд в Родопите",
                        "Широка лъка",
                        "Двудневен преход за малка група.",
                        220,
                        10,
                        41.6799,
                        24.5818,
                        "Широка лъка, България",
                        "/static/images/rodopi.jpg",
                    ),
                    (
                        "belogradchik",
                        "Вело уикенд край Белоградчик",
                        "Белоградчик",
                        "Вело маршрут и природни забележителности.",
                        250,
                        8,
                        43.6272,
                        22.6868,
                        "Белоградчик, България",
                        "/static/images/belogradchik.jpg",
                    ),
                    (
                        "shabla",
                        "Наблюдение на птици край Шабла",
                        "Шабла",
                        "Природно преживяване с местен водач.",
                        280,
                        12,
                        43.5367,
                        28.5342,
                        "Шабла, България",
                        "/static/images/shabla.jpg",
                    ),
                    (
                        "plovdiv",
                        "Уикенд в Пловдив",
                        "Пловдив",
                        "Два дни културни зебележителности с водач.",
                        180,
                        12,
                        43.5367,
                        28.5342,
                        "Пловдив, България",
                        "/static/images/plovdiv.jpg",
                    ),
                ],
            )

        connection.execute("""
            CREATE TABLE IF NOT EXISTS tour_departures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tour_id INTEGER NOT NULL,
                departure_date TEXT NOT NULL,
                capacity INTEGER NOT NULL CHECK(capacity > 0),
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK(is_active IN (0, 1)),
                FOREIGN KEY (tour_id) REFERENCES tours(id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                departure_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                participants INTEGER NOT NULL CHECK(participants > 0),
                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK(status IN ('PENDING', 'CONFIRMED', 'CANCELLED')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (departure_id)
                    REFERENCES tour_departures(id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
                    CHECK(role IN ('public', 'operator', 'admin')),
                status TEXT NOT NULL
                    CHECK(status IN (
                        'ACTIVE',
                        'PENDING_APPROVAL',
                        'DISABLED'
                    )),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        admin_exists = connection.execute(
            "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
        if admin_exists is None:
            connection.execute(
                """
                INSERT INTO users
                    (username, email, password_hash, role, status)
                VALUES ('admin', 'admin@example.com', ?, 'admin', 'ACTIVE')
                """,
                (generate_password_hash("Admin123!"),),
            )

        departure_count = connection.execute(
            "SELECT COUNT(*) FROM tour_departures"
        ).fetchone()[0]

        if departure_count == 0:
            rodopi_id = connection.execute(
                "SELECT id FROM tours WHERE code = 'rodopi'"
            ).fetchone()["id"]

            connection.executemany(
                """
                INSERT INTO tour_departures
                    (tour_id, departure_date, capacity)
                VALUES (?, ?, ?)
                """,
                [
                    (rodopi_id, "2026-11-08", 10),
                    (rodopi_id, "2026-11-15", 10),
                    (rodopi_id, "2026-11-22", 10),
                ],
            )


def migrate_ownership():
    with get_connection() as connection:
        tour_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(tours)"
            ).fetchall()
        }
        if "operator_id" not in tour_columns:
            connection.execute(
                "ALTER TABLE tours ADD COLUMN operator_id INTEGER"
            )

        booking_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(bookings)"
            ).fetchall()
        }
        if "public_user_id" not in booking_columns:
            connection.execute(
                "ALTER TABLE bookings ADD COLUMN public_user_id INTEGER"
            )


init_db()
migrate_ownership()


def get_csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": get_csrf_token}


def validate_csrf():
    expected = session.get("csrf_token")
    received = request.form.get("csrf_token", "")
    if (
        not expected
        or not received
        or not compare_digest(expected, received)
    ):
        abort(400, description="Невалиден CSRF token.")


@app.before_request
def protect_state_changes():
    if request.method == "POST":
        validate_csrf()


def get_active_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None

    with get_connection() as connection:
        user = connection.execute(
            """
            SELECT id, username, email, role, status
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    if user is None or user["status"] != "ACTIVE":
        session.clear()
        return None

    session["username"] = user["username"]
    session["role"] = user["role"]
    return user


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if get_active_user() is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            user = get_active_user()
            if user is None:
                return redirect(url_for("login"))
            if user["role"] not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def validate_registration(username, email, password):
    return bool(username) and "@" in email and len(password) >= 8


def parse_departure_dates(values, required):
    dates = [value.strip() for value in values if value.strip()]
    if required and not dates:
        raise ValueError("Добавете поне една дата на заминаване.")

    try:
        dates = [
            datetime.strptime(value, "%Y-%m-%d").date().isoformat()
            for value in dates
        ]
    except ValueError:
        raise ValueError("Проверете датите на заминаване.") from None

    if len(set(dates)) != len(dates):
        raise ValueError("Датите на заминаване трябва да са различни.")
    return dates


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    with get_connection() as connection:
        user = connection.execute(
            """
            SELECT id, username, password_hash, role
            FROM users
            WHERE username = ? AND status = 'ACTIVE'
            """,
            (username,),
        ).fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        return render_template(
            "login.html",
            error="Невалидно потребителско име или парола.",
        ), 401

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    if user["role"] == "public":
        return redirect(url_for("home"))
    return redirect(url_for("admin_tours"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


def register_user(role, status, template):
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not validate_registration(username, email, password):
        return render_template(
            template,
            error="Въведете потребителско име, валиден e-mail и парола с поне 8 символа.",
        ), 400

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (username, email, password_hash, role, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    generate_password_hash(password),
                    role,
                    status,
                ),
            )
    except sqlite3.IntegrityError:
        return render_template(
            template,
            error="Това потребителско име или e-mail вече е регистриран.",
        ), 400

    if role == "operator":
        return render_template(
            "register_operator.html",
            message="Кандидатурата е получена и очаква одобрение от администратор.",
        )
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register_public():
    if request.method == "GET":
        return render_template("register_public.html")
    return register_user("public", "ACTIVE", "register_public.html")


@app.route("/operator/register", methods=["GET", "POST"])
def register_operator():
    if request.method == "GET":
        return render_template("register_operator.html")
    return register_user(
        "operator", "PENDING_APPROVAL", "register_operator.html"
    )


@app.route("/")
def home():
    with get_connection() as connection:
        tours = connection.execute("""
            SELECT id, code, name, location, description, price, image_url
            FROM tours
            WHERE is_active = 1
            ORDER BY id
            """).fetchall()

    return render_template("index.html", tours=tours)


@app.route("/tours/<int:tour_id>")
def tour_detail(tour_id):
    with get_connection() as connection:
        tour = connection.execute(
            """
            SELECT *
            FROM tours
            WHERE id = ? AND is_active = 1
            """,
            (tour_id,),
        ).fetchone()

        departures = connection.execute(
            """
            SELECT
                d.id,
                d.departure_date,
                d.capacity,
                d.capacity -
                COALESCE(SUM(
                    CASE
                        WHEN b.status = 'CONFIRMED'
                        THEN b.participants
                        ELSE 0
                    END
                ), 0) AS available
            FROM tour_departures AS d
            LEFT JOIN bookings AS b
              ON b.departure_id = d.id
            WHERE d.tour_id = ?
              AND d.is_active = 1
            GROUP BY d.id
            ORDER BY d.departure_date
            """,
            (tour_id,),
        ).fetchall()

    if tour is None:
        return "Офертата не е намерена.", 404

    return render_template("tour_detail.html", tour=tour, departures=departures)


def get_bookings():
    with get_connection() as connection:
        return connection.execute("""
            SELECT
                b.id,
                b.customer_name,
                b.email,
                b.participants,
                b.status,
                d.departure_date,
                d.capacity,
                t.name AS tour_name,
                t.location,
                t.latitude,
                t.longitude,
                t.map_query
            FROM bookings AS b
            JOIN tour_departures AS d
              ON d.id = b.departure_id
            JOIN tours AS t
              ON t.id = d.tour_id
            ORDER BY b.id DESC
            """).fetchall()


@app.route("/booking")
@app.route("/bookings")
@role_required("public")
def bookings():
    with get_connection() as connection:
        user_bookings = connection.execute(
            """
            SELECT
                b.id,
                b.customer_name,
                b.email,
                b.participants,
                b.status,
                d.departure_date,
                t.name AS tour_name,
                t.location,
                t.map_query
            FROM bookings AS b
            JOIN tour_departures AS d ON d.id = b.departure_id
            JOIN tours AS t ON t.id = d.tour_id
            WHERE b.public_user_id = ?
            ORDER BY b.id DESC
            """,
            (session["user_id"],),
        ).fetchall()
    return render_template("bookings.html", bookings=user_bookings)


@app.route("/admin/tours")
@role_required("admin", "operator")
def admin_tours():
    with get_connection() as connection:
        if session["role"] == "admin":
            tours = connection.execute(
                "SELECT * FROM tours ORDER BY id"
            ).fetchall()
        else:
            tours = connection.execute(
                "SELECT * FROM tours WHERE operator_id = ? ORDER BY id",
                (session["user_id"],),
            ).fetchall()

    return render_template("admin_tours.html", tours=tours)


@app.route("/admin/tours/new", methods=["GET", "POST"])
@role_required("admin", "operator")
def tour_create():
    if request.method == "GET":
        return render_template("tour_form.html", tour=None)

    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()
    map_query = request.form.get("map_query", "").strip()

    try:
        price = float(request.form.get("price", ""))
        capacity = int(request.form.get("capacity", ""))

        latitude_raw = request.form.get("latitude", "").strip()
        longitude_raw = request.form.get("longitude", "").strip()

        latitude = float(latitude_raw) if latitude_raw else None
        longitude = float(longitude_raw) if longitude_raw else None
    except ValueError:
        return "Проверете цена, капацитет и координати.", 400

    if not code or not name or not location or not description:
        return "Всички основни текстови полета са задължителни.", 400

    if price < 0 or capacity < 1:
        return "Невалидна цена или капацитет.", 400

    try:
        departure_dates = parse_departure_dates(
            request.form.getlist("departure_dates"),
            required=True,
        )
    except ValueError as error:
        return str(error), 400

    operator_id = (
        session["user_id"] if session["role"] == "operator" else None
    )
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO tours
                (code, name, location, description,
                 price, capacity,
                 latitude, longitude, map_query,
                 image_url, operator_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                name,
                location,
                description,
                price,
                capacity,
                latitude,
                longitude,
                map_query,
                request.form.get("image_url", "").strip(),
                operator_id,
            ),
        )
        connection.executemany(
            """
            INSERT INTO tour_departures
                (tour_id, departure_date, capacity)
            VALUES (?, ?, ?)
            """,
            [
                (cursor.lastrowid, departure_date, capacity)
                for departure_date in departure_dates
            ],
        )

    return redirect(url_for("admin_tours"))


@app.route("/admin/tours/<int:tour_id>/edit", methods=["GET", "POST"])
@role_required("admin", "operator")
def tour_edit(tour_id):
    with get_connection() as connection:
        tour = connection.execute(
            "SELECT * FROM tours WHERE id = ?", (tour_id,)
        ).fetchone()
        departures = connection.execute(
            """
            SELECT id, departure_date, capacity, is_active
            FROM tour_departures
            WHERE tour_id = ?
            ORDER BY departure_date
            """,
            (tour_id,),
        ).fetchall()

    if tour is None:
        return "Офертата не е намерена.", 404
    if (
        session["role"] == "operator"
        and tour["operator_id"] != session["user_id"]
    ):
        abort(403)

    if request.method == "GET":
        return render_template(
            "tour_form.html",
            tour=tour,
            departures=departures,
        )

    name = request.form.get("name", "").strip()
    location = request.form.get("location", "").strip()
    description = request.form.get("description", "").strip()

    try:
        price = float(request.form.get("price", ""))
        capacity = int(request.form.get("capacity", ""))
    except ValueError:
        return "Проверете цена и капацитет.", 400

    if price < 0 or capacity < 1:
        return "Невалидна цена или капацитет.", 400

    try:
        departure_dates = parse_departure_dates(
            request.form.getlist("departure_dates"),
            required=False,
        )
    except ValueError as error:
        return str(error), 400

    with get_connection() as connection:
        existing_dates = {
            row["departure_date"]
            for row in connection.execute(
                "SELECT departure_date FROM tour_departures WHERE tour_id = ?",
                (tour_id,),
            ).fetchall()
        }
        if existing_dates.intersection(departure_dates):
            return "Тази дата вече е добавена към тура.", 400

        connection.execute(
            """
            UPDATE tours
            SET name = ?,
                location = ?,
                description = ?,
                price = ?,
                capacity = ?,
                latitude = ?,
                longitude = ?,
                map_query = ?,
                image_url = ?
            WHERE id = ?
            """,
            (
                name,
                location,
                description,
                price,
                capacity,
                (
                    float(request.form["latitude"])
                    if request.form.get("latitude", "").strip()
                    else None
                ),
                (
                    float(request.form["longitude"])
                    if request.form.get("longitude", "").strip()
                    else None
                ),
                request.form.get("map_query", "").strip(),
                request.form.get("image_url", "").strip(),
                tour_id,
            ),
        )
        if departure_dates:
            connection.executemany(
                """
                INSERT INTO tour_departures
                    (tour_id, departure_date, capacity)
                VALUES (?, ?, ?)
                """,
                [
                    (tour_id, departure_date, capacity)
                    for departure_date in departure_dates
                ],
            )

    return redirect(url_for("admin_tours"))


@app.route("/admin/tours/<int:tour_id>/toggleIsActive", methods=["POST"])
@role_required("admin", "operator")
def tour_toggle_is_active(tour_id):
    with get_connection() as connection:
        tour = connection.execute(
            "SELECT operator_id FROM tours WHERE id = ?", (tour_id,)
        ).fetchone()
        if tour is None:
            return "Офертата не е намерена.", 404
        if (
            session["role"] == "operator"
            and tour["operator_id"] != session["user_id"]
        ):
            abort(403)
        connection.execute(
            """
            UPDATE tours
            SET is_active = CASE
                WHEN is_active = 1 THEN 0
                ELSE 1
            END
            WHERE id = ?
            """,
            (tour_id,),
        )

    return redirect(url_for("admin_tours"))


def get_available_capacity(connection, departure_id):
    row = connection.execute(
        """
        SELECT
            d.capacity,
            COALESCE(
                SUM(
                    CASE
                        WHEN b.status = 'CONFIRMED'
                        THEN b.participants
                        ELSE 0
                    END
                ),
                0
            ) AS reserved
        FROM tour_departures AS d
        LEFT JOIN bookings AS b
          ON b.departure_id = d.id
        WHERE d.id = ?
        GROUP BY d.id
        """,
        (departure_id,),
    ).fetchone()

    if row is None:
        return None

    return row["capacity"] - row["reserved"]


@app.route("/bookings/new", methods=["POST"])
@role_required("public")
def booking_create():
    try:
        departure_id = int(request.form.get("departure_id", ""))
        participants = int(request.form.get("participants", ""))
    except ValueError:
        return "Невалидни данни.", 400

    if participants < 1 or participants > 10:
        return "Броят участници трябва да е между 1 и 10.", 400

    with get_connection() as connection:
        user = connection.execute(
            "SELECT username, email FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
        departure = connection.execute(
            """
            SELECT *
            FROM tour_departures
            WHERE id = ?
              AND is_active = 1
            """,
            (departure_id,),
        ).fetchone()

        if departure is None:
            return "Заминаването не съществува.", 400

        connection.execute(
            """
            INSERT INTO bookings
                (departure_id, customer_name, email, participants,
                 status, public_user_id)
            VALUES (?, ?, ?, ?, 'PENDING', ?)
            """,
            (
                departure_id,
                user["username"],
                user["email"],
                participants,
                session["user_id"],
            ),
        )

    return redirect(url_for("bookings"))


@app.route("/admin/bookings")
@role_required("admin", "operator")
def booking_list():
    if session["role"] == "admin":
        bookings = get_bookings()
    else:
        with get_connection() as connection:
            bookings = connection.execute(
                """
                SELECT
                    b.id, b.customer_name, b.email, b.participants,
                    b.status, d.departure_date, d.capacity,
                    t.name AS tour_name, t.location, t.latitude,
                    t.longitude, t.map_query
                FROM bookings AS b
                JOIN tour_departures AS d ON d.id = b.departure_id
                JOIN tours AS t ON t.id = d.tour_id
                WHERE t.operator_id = ?
                ORDER BY b.id DESC
                """,
                (session["user_id"],),
            ).fetchall()
    return render_template("admin_bookings.html", bookings=bookings)


@app.route("/admin/bookings/<int:booking_id>/confirm", methods=["POST"])
@role_required("admin", "operator")
def booking_confirm(booking_id):
    with get_connection() as connection:
        booking = connection.execute(
            """
            SELECT *
            FROM bookings
            WHERE id = ?
            """,
            (booking_id,),
        ).fetchone()

        if booking is None:
            return "Booking не е намерен.", 404
        if session["role"] == "operator":
            owner = connection.execute(
                """
                SELECT t.operator_id
                FROM bookings AS b
                JOIN tour_departures AS d ON d.id = b.departure_id
                JOIN tours AS t ON t.id = d.tour_id
                WHERE b.id = ?
                """,
                (booking_id,),
            ).fetchone()
            if owner["operator_id"] != session["user_id"]:
                abort(403)

        if booking["status"] != "PENDING":
            return "Само PENDING booking може да се потвърди.", 400

        available = get_available_capacity(connection, booking["departure_id"])

        if available is None:
            return "Departure не е намерен.", 400

        if booking["participants"] > available:
            return "Няма достатъчно свободни места.", 400

        connection.execute(
            """
            UPDATE bookings
            SET status = 'CONFIRMED'
            WHERE id = ?
            """,
            (booking_id,),
        )

    return redirect(url_for("booking_list"))


@app.route("/admin/bookings/<int:booking_id>/cancel", methods=["POST"])
@role_required("admin", "operator")
def booking_cancel(booking_id):
    with get_connection() as connection:
        booking = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()

        if booking is None:
            return "Booking не е намерен.", 404
        if session["role"] == "operator":
            owner = connection.execute(
                """
                SELECT t.operator_id
                FROM bookings AS b
                JOIN tour_departures AS d ON d.id = b.departure_id
                JOIN tours AS t ON t.id = d.tour_id
                WHERE b.id = ?
                """,
                (booking_id,),
            ).fetchone()
            if owner["operator_id"] != session["user_id"]:
                abort(403)

        if booking["status"] == "CANCELLED":
            return "Booking вече е отменен.", 400

        connection.execute(
            """
            UPDATE bookings
            SET status = 'CANCELLED'
            WHERE id = ?
            """,
            (booking_id,),
        )

    return redirect(url_for("booking_list"))


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    with get_connection() as connection:
        users = connection.execute(
            """
            SELECT id, username, email, role, status, created_at
            FROM users
            ORDER BY id
            """
        ).fetchall()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/<int:user_id>/approve", methods=["POST"])
@role_required("admin")
def approve_operator(user_id):
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET status = 'ACTIVE'
            WHERE id = ?
              AND role = 'operator'
              AND status = 'PENDING_APPROVAL'
            """,
            (user_id,),
        )
        if cursor.rowcount == 0:
            return "Чакащ оператор не е намерен.", 404
    return redirect(url_for("admin_users"))


@app.route("/admin/users/new", methods=["GET", "POST"])
@role_required("admin")
def staff_user_create():
    if request.method == "GET":
        return render_template("staff_user_form.html")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "")
    if (
        not validate_registration(username, email, password)
        or role not in ("operator", "admin")
    ):
        return render_template(
            "staff_user_form.html",
            error="Проверете потребителското име, e-mail, паролата и ролята.",
        ), 400

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (username, email, password_hash, role, status)
                VALUES (?, ?, ?, ?, 'ACTIVE')
                """,
                (username, email, generate_password_hash(password), role),
            )
    except sqlite3.IntegrityError:
        return render_template(
            "staff_user_form.html",
            error="Това потребителско име или e-mail вече е регистриран.",
        ), 400
    return redirect(url_for("admin_users"))
