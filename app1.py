import sqlite3
import PySimpleGUI as sg
from datetime import datetime

DB_PATH = "Project.db"



def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def fetch_one(sql, params=()):
    with db_connect() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchone()


def fetch_all(sql, params=()):
    with db_connect() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall()


def exec_sql(sql, params=()):
    with db_connect() as conn:
        conn.execute(sql, params)
        conn.commit()


def exec_return_id(sql, params=()):
    with db_connect() as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


def safe_float(x):
    x = (x or "").strip()
    if not x:
        return None
    return float(x)


def safe_int(x):
    x = (x or "").strip()
    if not x:
        return None
    return int(x)


def parse_yyyy_mm_dd(s):
    s = (s or "").strip()
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt_rating(x):
    if x is None:
        return "No ratings"
    return f"{x:.2f}"



def get_user_by_email(email):
    return fetch_one("SELECT User_id, Name, Email FROM USER WHERE Email = ?", (email,))


def is_owner(user_id):
    return fetch_one("SELECT 1 FROM OWNER WHERE User_id = ?", (user_id,)) is not None


def is_customer(user_id):
    return fetch_one("SELECT 1 FROM CUSTOMER WHERE User_id = ?", (user_id,)) is not None


def owner_signup_with_property(owner_name, email, gsm, prop):
    """
    Create USER + OWNER + PROPERTY in one flow (as required by prompt).
    prop = dict(name, desc, capacity, type, price, city, district)
    """
    if get_user_by_email(email):
        return None, "This email already exists."

    uid = exec_return_id("INSERT INTO USER(Name, Email) VALUES (?, ?)", (owner_name, email))
    exec_sql("INSERT INTO OWNER(User_id, Gsm) VALUES (?, ?)", (uid, gsm))

    exec_sql(
        """
        INSERT INTO PROPERTY(Name, Description, Capacity, Type, Nightly_price, City, District, Owner_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prop["name"],
            prop["desc"],
            prop["capacity"],
            prop["type"],
            prop["price"],
            prop["city"],
            prop["district"],
            uid,
        ),
    )
    return uid, None


def customer_signup(customer_name, email):
    if get_user_by_email(email):
        return None, "This email already exists."

    uid = exec_return_id("INSERT INTO USER(Name, Email) VALUES (?, ?)", (customer_name, email))
    exec_sql("INSERT INTO CUSTOMER(User_id) VALUES (?)", (uid,))
    return uid, None



def owner_get_gsm(owner_id):
    r = fetch_one("SELECT Gsm FROM OWNER WHERE User_id = ?", (owner_id,))
    return r[0] if r else ""


def owner_update_gsm(owner_id, gsm):
    exec_sql("UPDATE OWNER SET Gsm = ? WHERE User_id = ?", (gsm, owner_id))


def owner_properties(owner_id):
    return fetch_all(
        """
        SELECT Property_no, Name, City, District, Capacity, Type, Nightly_price, COALESCE(Description,'')
        FROM PROPERTY
        WHERE Owner_id = ?
        ORDER BY Property_no DESC
        """,
        (owner_id,),
    )


def owner_add_property(owner_id, prop):
    exec_sql(
        """
        INSERT INTO PROPERTY(Name, Description, Capacity, Type, Nightly_price, City, District, Owner_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            prop["name"],
            prop["desc"],
            prop["capacity"],
            prop["type"],
            prop["price"],
            prop["city"],
            prop["district"],
            owner_id,
        ),
    )


def owner_edit_property(owner_id, prop_no, updates):
    exec_sql(
        """
        UPDATE PROPERTY
        SET Name = ?, Description = ?, Capacity = ?, Type = ?, Nightly_price = ?, City = ?, District = ?
        WHERE Property_no = ? AND Owner_id = ?
        """,
        (
            updates["name"],
            updates["desc"],
            updates["capacity"],
            updates["type"],
            updates["price"],
            updates["city"],
            updates["district"],
            prop_no,
            owner_id,
        ),
    )



def search_properties(filters):
    """
    filters keys:
      city, district, min_cap, ptype,
      min_price, max_price,
      min_rating, max_rating,
      start_date, end_date
    """
    sql = """
    SELECT
        P.Property_no,
        P.Name,
        P.City,
        P.District,
        P.Capacity,
        P.Type,
        P.Nightly_price,
        COALESCE(P.Description,'') AS Description,
        R.avg_rating
    FROM PROPERTY P
    LEFT JOIN (
        SELECT B.Property_no AS prop_no, AVG(E.Rating) AS avg_rating
        FROM BOOKING B
        JOIN EVALUATION E ON E.Booking_no = B.Booking_no
        GROUP BY B.Property_no
    ) R ON R.prop_no = P.Property_no
    WHERE 1=1
    """
    params = []

    def add(cond, *ps):
        nonlocal sql, params
        sql += f" AND {cond}\n"
        params.extend(ps)

    if filters.get("city"):
        add("P.City = ?", filters["city"])
    if filters.get("district"):
        add("P.District = ?", filters["district"])
    if filters.get("ptype"):
        add("P.Type = ?", filters["ptype"])
    if filters.get("min_cap") is not None:
        add("P.Capacity >= ?", filters["min_cap"])
    if filters.get("min_price") is not None:
        add("P.Nightly_price >= ?", filters["min_price"])
    if filters.get("max_price") is not None:
        add("P.Nightly_price <= ?", filters["max_price"])

    if filters.get("min_rating") is not None:
        add("R.avg_rating IS NOT NULL AND R.avg_rating >= ?", filters["min_rating"])
    if filters.get("max_rating") is not None:
        add("R.avg_rating IS NOT NULL AND R.avg_rating <= ?", filters["max_rating"])

    sd = filters.get("start_date")
    ed = filters.get("end_date")
    if sd and ed:
        add(
            """
            NOT EXISTS (
                SELECT 1
                FROM BOOKING B
                WHERE B.Property_no = P.Property_no
                  AND date(B.Start_date) < date(?)
                  AND date(B.End_date)   > date(?)
                  AND (B.Status IS NULL OR B.Status <> 'CANCELLED')
            )
            """,
            ed.isoformat(),
            sd.isoformat(),
        )

        add(
            """
            NOT EXISTS (
                SELECT 1
                FROM CALENDAR_BLOCK C
                WHERE C.Property_no = P.Property_no
                  AND date(C.Start_date) < date(?)
                  AND date(C.End_date)   > date(?)
            )
            """,
            ed.isoformat(),
            sd.isoformat(),
        )

    sql += " ORDER BY P.Property_no DESC"
    return fetch_all(sql, tuple(params))



def win_main():
    layout = [
        [sg.Text("House Rental System", font=("Helvetica", 18, "bold"))],
        [sg.Button("Login"), sg.Button("Sign up as Owner"), sg.Button("Sign up as Customer")],
        [sg.Button("Exit")],
    ]
    return sg.Window("Main Menu", layout, finalize=True)


def win_login():
    layout = [
        [sg.Text("Login")],
        [sg.Text("Email", size=12), sg.Input(key="email")],
        [sg.Button("Login"), sg.Button("Back")],
    ]
    return sg.Window("Login", layout, modal=True, finalize=True)


def win_signup_owner():
    layout = [
        [sg.Text("Owner Sign Up (includes creating a first property)", font=("Helvetica", 12, "bold"))],
        [sg.Frame("Owner Info", [
            [sg.Text("Name", size=12), sg.Input(key="oname")],
            [sg.Text("Email", size=12), sg.Input(key="oemail")],
            [sg.Text("GSM", size=12), sg.Input(key="ogsm")],
        ])],
        [sg.Frame("First Property Info", [
            [sg.Text("Property Name", size=12), sg.Input(key="pname")],
            [sg.Text("Description", size=12), sg.Multiline(key="pdesc", size=(40, 4))],
            [sg.Text("Capacity", size=12), sg.Input(key="pcap")],
            [sg.Text("Type", size=12), sg.Input(key="ptype")],
            [sg.Text("Nightly Price", size=12), sg.Input(key="pprice")],
            [sg.Text("City", size=12), sg.Input(key="pcity")],
            [sg.Text("District", size=12), sg.Input(key="pdist")],
        ])],
        [sg.Button("Create Owner + Property"), sg.Button("Back")],
    ]
    return sg.Window("Sign Up - Owner", layout, modal=True, finalize=True)


def win_signup_customer():
    layout = [
        [sg.Text("Customer Sign Up", font=("Helvetica", 12, "bold"))],
        [sg.Text("Name", size=12), sg.Input(key="cname")],
        [sg.Text("Email", size=12), sg.Input(key="cemail")],
        [sg.Button("Create Customer"), sg.Button("Back")],
    ]
    return sg.Window("Sign Up - Customer", layout, modal=True, finalize=True)


def win_owner_panel(owner_id, owner_name):
    props = owner_properties(owner_id)
    headings = ["No", "Name", "City", "District", "Cap", "Type", "Price", "Description"]
    layout = [
        [sg.Text(f"Owner Panel — {owner_name} (id={owner_id})", font=("Helvetica", 14, "bold"))],
        [sg.Frame("Profile", [
            [sg.Text("GSM", size=10), sg.Input(owner_get_gsm(owner_id), key="gsm"), sg.Button("Update GSM")],
        ])],
        [sg.Frame("My Properties", [
            [sg.Table(values=props, headings=headings, key="ptable", enable_events=True,
                      auto_size_columns=True, justification="left", num_rows=8)],
            [sg.Button("Add Property"), sg.Button("Edit Selected Property")],
        ])],
        [sg.Button("Logout")],
    ]
    return sg.Window("Owner Panel", layout, finalize=True)


def win_property_form(title, initial=None):
    initial = initial or {
        "name": "", "desc": "", "capacity": "", "type": "", "price": "", "city": "", "district": ""
    }
    layout = [
        [sg.Text(title, font=("Helvetica", 12, "bold"))],
        [sg.Text("Name", size=12), sg.Input(initial["name"], key="name")],
        [sg.Text("Description", size=12), sg.Multiline(initial["desc"], key="desc", size=(40, 4))],
        [sg.Text("Capacity", size=12), sg.Input(str(initial["capacity"]), key="capacity")],
        [sg.Text("Type", size=12), sg.Input(initial["type"], key="type")],
        [sg.Text("Nightly Price", size=12), sg.Input(str(initial["price"]), key="price")],
        [sg.Text("City", size=12), sg.Input(initial["city"], key="city")],
        [sg.Text("District", size=12), sg.Input(initial["district"], key="district")],
        [sg.Button("Save"), sg.Button("Cancel")],
    ]
    return sg.Window(title, layout, modal=True, finalize=True)


def win_customer_panel(customer_id, customer_name):
    headings = ["No", "Name", "City", "District", "Cap", "Type", "Price", "Description", "AvgRating"]
    layout = [
        [sg.Text(f"Customer Panel — {customer_name} (id={customer_id})", font=("Helvetica", 14, "bold"))],
        [sg.Frame("Property Search Filters (leave blank to ignore)", [
            [sg.Text("City", size=10), sg.Input(key="city", size=15),
             sg.Text("District", size=10), sg.Input(key="district", size=15)],
            [sg.Text("Min Capacity", size=10), sg.Input(key="min_cap", size=15),
             sg.Text("Type", size=10), sg.Input(key="ptype", size=15)],
            [sg.Text("Min Price", size=10), sg.Input(key="min_price", size=15),
             sg.Text("Max Price", size=10), sg.Input(key="max_price", size=15)],
            [sg.Text("Min Rating", size=10), sg.Input(key="min_rating", size=15),
             sg.Text("Max Rating", size=10), sg.Input(key="max_rating", size=15)],
            [sg.Text("Start Date (YYYY-MM-DD)", size=20), sg.Input(key="start_date", size=15),
             sg.Text("End Date", size=8), sg.Input(key="end_date", size=15)],
            [sg.Button("Search")],
        ])],
        [sg.Table(values=[], headings=headings, key="results", enable_events=True,
                  auto_size_columns=True, justification="left", num_rows=10)],
        [sg.Button("View Details"), sg.Button("Logout")],
    ]
    return sg.Window("Customer Panel", layout, finalize=True)


def win_property_details(row):
    """
    row: (no, name, city, district, cap, type, price, desc, avg_rating)
    """
    if not isinstance(row, (list, tuple)) or len(row) < 9:
        layout = [
            [sg.Text("Property Details", font=("Helvetica", 14, "bold"))],
            [sg.Text(f"Unexpected selection format: {row}")],
            [sg.Button("Close")],
        ]
        return sg.Window("Details", layout, modal=True, finalize=True)

    prop_no, name, city, district, cap, ptype, price, desc, avg = row
    layout = [
        [sg.Text("Property Details", font=("Helvetica", 14, "bold"))],
        [sg.Text(f"Property No: {prop_no}")],
        [sg.Text(f"Name: {name}")],
        [sg.Text(f"City/District: {city} / {district}")],
        [sg.Text(f"Capacity: {cap}")],
        [sg.Text(f"Type: {ptype}")],
        [sg.Text(f"Nightly Price: {price}")],
        [sg.Text("Description:")],
        [sg.Multiline(desc or "", size=(60, 6), disabled=True)],
        [sg.Text(f"Average Rating: {fmt_rating(avg)}")],
        [sg.Button("Close")],
    ]
    return sg.Window("Details", layout, modal=True, finalize=True)



def main():
    sg.theme("DarkAmber")

    results_cache = []

    main_w = win_main()
    current = None  

    while True:
        event, values = main_w.read()
        if event in (sg.WIN_CLOSED, "Exit"):
            break

        if event == "Login":
            w = win_login()
            while True:
                e, v = w.read()
                if e in (sg.WIN_CLOSED, "Back"):
                    w.close()
                    break

                if e == "Login":
                    email = (v["email"] or "").strip()
                    u = get_user_by_email(email)
                    if not u:
                        sg.popup_error("User not found.")
                        continue

                    uid, name, _ = u
                    w.close()

                    if is_owner(uid):
                        main_w.close()
                        main_w = win_owner_panel(uid, name)
                        current = ("owner", uid, name)
                    elif is_customer(uid):
                        main_w.close()
                        main_w = win_customer_panel(uid, name)
                        current = ("customer", uid, name)
                        results_cache = []  # reset
                    else:
                        sg.popup_error("User exists but is neither OWNER nor CUSTOMER.")
                        main_w.close()
                        main_w = win_main()
                        current = None
                    break

        if event == "Sign up as Owner":
            w = win_signup_owner()
            while True:
                e, v = w.read()
                if e in (sg.WIN_CLOSED, "Back"):
                    w.close()
                    break

                if e == "Create Owner + Property":
                    try:
                        owner_name = (v["oname"] or "").strip()
                        email = (v["oemail"] or "").strip()
                        gsm = (v["ogsm"] or "").strip()

                        prop = {
                            "name": (v["pname"] or "").strip(),
                            "desc": (v["pdesc"] or "").strip(),
                            "capacity": safe_int(v["pcap"]),
                            "type": (v["ptype"] or "").strip(),
                            "price": safe_float(v["pprice"]),
                            "city": (v["pcity"] or "").strip(),
                            "district": (v["pdist"] or "").strip(),
                        }

                        if not owner_name or not email or not gsm:
                            sg.popup_error("Owner: Name, Email, GSM are required.")
                            continue
                        if not prop["name"] or prop["capacity"] is None or not prop["type"] or prop["price"] is None or not prop["city"] or not prop["district"]:
                            sg.popup_error("Property: Name, Capacity, Type, Price, City, District are required.")
                            continue

                        uid, err = owner_signup_with_property(owner_name, email, gsm, prop)
                        if err:
                            sg.popup_error(err)
                        else:
                            sg.popup("Owner created with a first property. You can now login with your email.")
                            w.close()
                            break
                    except Exception as ex:
                        sg.popup_error(f"Error: {ex}")

        if event == "Sign up as Customer":
            w = win_signup_customer()
            while True:
                e, v = w.read()
                if e in (sg.WIN_CLOSED, "Back"):
                    w.close()
                    break

                if e == "Create Customer":
                    try:
                        cname = (v["cname"] or "").strip()
                        cemail = (v["cemail"] or "").strip()
                        if not cname or not cemail:
                            sg.popup_error("Name and Email are required.")
                            continue

                        uid, err = customer_signup(cname, cemail)
                        if err:
                            sg.popup_error(err)
                        else:
                            sg.popup("Customer created. You can now login with your email.")
                            w.close()
                            break
                    except Exception as ex:
                        sg.popup_error(f"Error: {ex}")

        if current and current[0] == "owner":
            owner_id = current[1]
            owner_name = current[2]

            if event == "Update GSM":
                try:
                    owner_update_gsm(owner_id, (values["gsm"] or "").strip())
                    sg.popup("GSM updated.")
                except Exception as ex:
                    sg.popup_error(f"Error: {ex}")

            if event == "Add Property":
                pw = win_property_form("Add Property")
                e, v = pw.read()
                if e == "Save":
                    try:
                        prop = {
                            "name": (v["name"] or "").strip(),
                            "desc": (v["desc"] or "").strip(),
                            "capacity": safe_int(v["capacity"]),
                            "type": (v["type"] or "").strip(),
                            "price": safe_float(v["price"]),
                            "city": (v["city"] or "").strip(),
                            "district": (v["district"] or "").strip(),
                        }
                        if not prop["name"] or prop["capacity"] is None or not prop["type"] or prop["price"] is None or not prop["city"] or not prop["district"]:
                            sg.popup_error("Name, Capacity, Type, Price, City, District are required.")
                        else:
                            owner_add_property(owner_id, prop)
                            sg.popup("Property added.")
                            pw.close()
                            main_w.close()
                            main_w = win_owner_panel(owner_id, owner_name)
                    except Exception as ex:
                        sg.popup_error(f"Error: {ex}")
                else:
                    pw.close()

            if event == "Edit Selected Property":
                selected = values.get("ptable")
                if not selected:
                    sg.popup_error("Please select a property from the table.")
                else:
                    props = owner_properties(owner_id)
                    row = props[selected[0]]
                    prop_no = row[0]
                    initial = {
                        "name": row[1],
                        "city": row[2],
                        "district": row[3],
                        "capacity": row[4],
                        "type": row[5],
                        "price": row[6],
                        "desc": row[7],
                    }
                    pw = win_property_form(f"Edit Property #{prop_no}", initial=initial)
                    e, v = pw.read()
                    if e == "Save":
                        try:
                            updates = {
                                "name": (v["name"] or "").strip(),
                                "desc": (v["desc"] or "").strip(),
                                "capacity": safe_int(v["capacity"]),
                                "type": (v["type"] or "").strip(),
                                "price": safe_float(v["price"]),
                                "city": (v["city"] or "").strip(),
                                "district": (v["district"] or "").strip(),
                            }
                            if not updates["name"] or updates["capacity"] is None:
                                sg.popup_error("At least Name and Capacity must be valid.")
                            else:
                                owner_edit_property(owner_id, prop_no, updates)
                                sg.popup("Property updated.")
                                pw.close()
                                main_w.close()
                                main_w = win_owner_panel(owner_id, owner_name)
                        except Exception as ex:
                            sg.popup_error(f"Error: {ex}")
                    else:
                        pw.close()

            if event == "Logout":
                current = None
                main_w.close()
                main_w = win_main()

        if current and current[0] == "customer":
            if event == "Search":
                try:
                    city = (values["city"] or "").strip() or None
                    district = (values["district"] or "").strip() or None
                    ptype = (values["ptype"] or "").strip() or None

                    min_cap = safe_int(values["min_cap"])
                    min_price = safe_float(values["min_price"])
                    max_price = safe_float(values["max_price"])
                    min_rating = safe_float(values["min_rating"])
                    max_rating = safe_float(values["max_rating"])

                    sd_raw = (values["start_date"] or "").strip()
                    ed_raw = (values["end_date"] or "").strip()
                    sd = parse_yyyy_mm_dd(sd_raw) if sd_raw else None
                    ed = parse_yyyy_mm_dd(ed_raw) if ed_raw else None

                    if (sd and not ed) or (ed and not sd):
                        sg.popup_error("If you use date range, you must fill BOTH Start Date and End Date.")
                        continue
                    if sd and ed and ed <= sd:
                        sg.popup_error("End Date must be after Start Date.")
                        continue

                    filt = {
                        "city": city,
                        "district": district,
                        "ptype": ptype,
                        "min_cap": min_cap,
                        "min_price": min_price,
                        "max_price": max_price,
                        "min_rating": min_rating,
                        "max_rating": max_rating,
                        "start_date": sd,
                        "end_date": ed,
                    }
                    rows = search_properties(filt)
                    results_cache = rows  
                    main_w["results"].update(values=rows)
                except Exception as ex:
                    sg.popup_error(f"Search error: {ex}")

            if event == "View Details":
                sel = values.get("results")
                if not sel:
                    sg.popup_error("Please select a property from the results table.")
                else:
                    try:
                        row = results_cache[sel[0]]  
                    except Exception:
                        sg.popup_error("Selection is out of sync. Please press Search again.")
                        continue

                    dw = win_property_details(row)
                    dw.read()
                    dw.close()

            if event == "Logout":
                current = None
                results_cache = []
                main_w.close()
                main_w = win_main()

    main_w.close()


if __name__ == "__main__":
    main()
