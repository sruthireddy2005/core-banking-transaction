from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    url_for,
    send_from_directory
)

from database import get_db_connection

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import EMAIL_ADDRESS, EMAIL_APP_PASSWORD

import os
import random
import smtplib
import socket
import ssl
import string

from email.message import EmailMessage
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)

app.secret_key = "core_banking_secret_key"


# ============================================================
# CAPTCHA
# ============================================================

def generate_captcha():

    characters = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"

    return "".join(random.choices(characters, k=6))



# ============================================================
# FILE UPLOAD CONFIGURATION
# ============================================================

UPLOAD_FOLDER = "static/uploads"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ============================================================
# SEND OTP EMAIL
# ============================================================

def send_otp_email(receiver_email, otp):

    message = EmailMessage()

    message["Subject"] = "Core Banking - Login OTP"
    message["From"] = EMAIL_ADDRESS
    message["To"] = receiver_email

    message.set_content(
        f"""
Hello,

Your Core Banking login OTP is:

{otp}

This OTP is valid for 5 minutes.

If you did not request this OTP, please ignore this email.

Regards,
Core Banking System
"""
    )

    try:

        print("Connecting to Gmail SMTP on port 587...")

        with smtplib.SMTP(
            "smtp.gmail.com",
            587,
            timeout=30
        ) as server:

            server.ehlo()

            server.starttls(
                context=ssl.create_default_context()
            )

            server.ehlo()

            print("Logging into Gmail...")

            server.login(
                EMAIL_ADDRESS,
                EMAIL_APP_PASSWORD
            )

            print("Sending OTP email...")

            server.send_message(message)

        print("OTP email sent successfully.")

        return True

    except Exception as e:

        print("OTP email sending failed:")
        print(e)

        return False


# ============================================================
# SEND GENERAL NOTIFICATION EMAIL
# ============================================================

def send_notification_email(receiver_email, subject, body):

    try:

        message = EmailMessage()

        message["Subject"] = subject
        message["From"] = EMAIL_ADDRESS
        message["To"] = receiver_email

        message.set_content(body)

        with smtplib.SMTP(
            "smtp.gmail.com",
            587,
            timeout=30
        ) as server:

            server.ehlo()
            server.starttls()
            server.ehlo()

            server.login(
                EMAIL_ADDRESS,
                EMAIL_APP_PASSWORD
            )

            server.send_message(message)

        return True

    except Exception as e:

        print("Notification email error:", e)

        return False
            
# ============================================================
# ACCOUNT BALANCE CALCULATION
# ============================================================

def get_account_balance(cursor, account_id):

    # --------------------------------------------------------
    # Deposit - Withdraw
    # --------------------------------------------------------

    transaction_query = """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN transaction_type = 'DEPOSIT'
                            THEN amount

                        WHEN transaction_type = 'WITHDRAW'
                            THEN -amount

                        ELSE 0
                    END
                ),
                0
            ) AS transaction_balance

        FROM `TRANSACTION`

        WHERE account_id = %s
          AND status = 'SUCCESS'
    """

    cursor.execute(
        transaction_query,
        (account_id,)
    )

    result = cursor.fetchone()

    transaction_balance = Decimal(
        str(result["transaction_balance"] or 0)
    )


    # --------------------------------------------------------
    # Incoming Transfer - Outgoing Transfer
    # --------------------------------------------------------

    transfer_query = """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN to_account_id = %s
                            THEN amount

                        WHEN from_account_id = %s
                            THEN -amount

                        ELSE 0
                    END
                ),
                0
            ) AS transfer_balance

        FROM FUND_TRANSFER

        WHERE (
            to_account_id = %s
            OR from_account_id = %s
        )

        AND status = 'SUCCESS'
    """

    cursor.execute(
        transfer_query,
        (
            account_id,
            account_id,
            account_id,
            account_id
        )
    )

    result = cursor.fetchone()

    transfer_balance = Decimal(
        str(result["transfer_balance"] or 0)
    )


    # --------------------------------------------------------
    # Final Balance
    # --------------------------------------------------------

    return (
        transaction_balance
        + transfer_balance
    )

# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template("home.html")

# ============================================================
# HELP PAGE
# ============================================================

@app.route("/help")
def help_page():

    return render_template(
        "help.html"
    )


# ============================================================
# CONTACT PAGE
# ============================================================

@app.route("/contact")
def contact_page():

    return render_template(
        "contact.html"
    )

# ============================================================
# SERVICES PAGE
# ============================================================

@app.route("/services")
def services_page():
    return render_template("services.html")

# ============================================================
# CUSTOMER LOGIN
# ============================================================

@app.route(
    "/customer/login",
    methods=["GET", "POST"]
)
def customer_login():

    # ========================================================
    # GET REQUEST
    # Generate a new CAPTCHA
    # ========================================================

    if request.method == "GET":

        captcha = generate_captcha()

        session["customer_captcha"] = captcha

        return render_template(
            "customer/login.html",
            captcha=captcha
        )


    # ========================================================
    # POST REQUEST
    # Get email and CAPTCHA
    # ========================================================

    email = request.form["email"].strip()

    entered_captcha = request.form.get(
        "captcha",
        ""
    ).strip()


    # ========================================================
    # CHECK CAPTCHA
    # ========================================================

    correct_captcha = session.get(
        "customer_captcha"
    )


    if not correct_captcha:

        new_captcha = generate_captcha()

        session["customer_captcha"] = new_captcha

        return render_template(
            "customer/login.html",
            message="CAPTCHA expired. Please try again.",
            captcha=new_captcha
        )


    if entered_captcha.lower() != correct_captcha.lower():

        new_captcha = generate_captcha()

        session["customer_captcha"] = new_captcha

        return render_template(
            "customer/login.html",
            message="Invalid CAPTCHA. Please enter the correct CAPTCHA.",
            captcha=new_captcha
        )


    # ========================================================
    # CAPTCHA IS CORRECT
    # Remove CAPTCHA so it cannot be reused
    # ========================================================

    session.pop(
        "customer_captcha",
        None
    )


    # ========================================================
    # CHECK CUSTOMER EMAIL
    # ========================================================

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    query = """
        SELECT
            user_id,
            first_name,
            email,
            status
        FROM `USER`
        WHERE email = %s
    """


    cursor.execute(
        query,
        (email,)
    )


    customer = cursor.fetchone()


    # ========================================================
    # EMAIL NOT FOUND
    # ========================================================

    if customer is None:

        cursor.close()
        connection.close()

        # Generate new CAPTCHA
        new_captcha = generate_captcha()

        session["customer_captcha"] = new_captcha

        return render_template(
            "customer/login.html",
            message="Email is not registered.",
            captcha=new_captcha
        )


    # ========================================================
    # CUSTOMER STATUS CHECK
    # ========================================================

    if customer["status"] != "ACTIVE":

        cursor.close()
        connection.close()

        # Generate new CAPTCHA
        new_captcha = generate_captcha()

        session["customer_captcha"] = new_captcha

        return render_template(
            "customer/login.html",
            message="Your account is blocked or inactive.",
            captcha=new_captcha
        )


    # ========================================================
    # GENERATE OTP
    # ========================================================

    otp = str(
        random.randint(
            100000,
            999999
        )
    )


    # ========================================================
    # HASH OTP
    # ========================================================

    otp_hash = generate_password_hash(
        otp
    )


    # ========================================================
    # OTP EXPIRY
    # ========================================================

    expires_at = (
        datetime.now()
        + timedelta(minutes=5)
    )


    # ========================================================
    # CHECK EXISTING OTP
    # ========================================================

    check_query = """
        SELECT otp_id
        FROM OTP_VERIFICATION
        WHERE email = %s
          AND purpose = 'LOGIN'
        LIMIT 1
    """


    cursor.execute(
        check_query,
        (email,)
    )


    existing_otp = cursor.fetchone()


    # ========================================================
    # UPDATE EXISTING OTP
    # ========================================================

    if existing_otp:

        update_query = """
            UPDATE OTP_VERIFICATION
            SET
                otp_hash = %s,
                created_at = CURRENT_TIMESTAMP,
                expires_at = %s,
                attempts = 0
            WHERE otp_id = %s
        """


        cursor.execute(
            update_query,
            (
                otp_hash,
                expires_at,
                existing_otp["otp_id"]
            )
        )


    # ========================================================
    # CREATE NEW OTP
    # ========================================================

    else:

        insert_query = """
            INSERT INTO OTP_VERIFICATION
            (
                email,
                otp_hash,
                purpose,
                created_at,
                expires_at,
                attempts
            )
            VALUES
            (
                %s,
                %s,
                %s,
                CURRENT_TIMESTAMP,
                %s,
                %s
            )
        """


        cursor.execute(
            insert_query,
            (
                email,
                otp_hash,
                "LOGIN",
                expires_at,
                0
            )
        )


    # ========================================================
    # COMMIT OTP
    # ========================================================

    connection.commit()


    cursor.close()

    connection.close()


    # ========================================================
    # SEND OTP EMAIL
    # ========================================================

    email_sent = send_otp_email(
        email,
        otp
    )

# --------------------------------------------------------
# DEVELOPMENT FALLBACK
# --------------------------------------------------------
# If Gmail cannot be reached, do not stop the login.
# The OTP will be printed in the terminal.
# The OTP is already stored securely as a hash in the
# OTP_VERIFICATION table.
# --------------------------------------------------------

    if not email_sent:

        print("")
        print("==========================================")
        print("OTP EMAIL COULD NOT BE SENT")
        print("CUSTOMER EMAIL:", email)
        print("DEVELOPMENT OTP:", otp)
        print("==========================================")
        print("")



    # ========================================================
    # OTP VERIFICATION PAGE
    # ========================================================

    return render_template(
        "customer/verify_otp.html",
        email=email
    )
# ============================================================
# CUSTOMER OTP VERIFICATION
# ============================================================

@app.route(
    "/customer/verify-otp",
    methods=["POST"]
)
def verify_otp():

    email = request.form["email"].strip()

    entered_otp = request.form["otp"].strip()

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    query = """
        SELECT
            otp_id,
            otp_hash,
            expires_at,
            attempts
        FROM OTP_VERIFICATION
        WHERE email = %s
          AND purpose = 'LOGIN'
        ORDER BY created_at DESC
        LIMIT 1
    """

    cursor.execute(
        query,
        (email,)
    )

    otp_record = cursor.fetchone()

    if otp_record is None:

        cursor.close()
        connection.close()

        return render_template(
            "customer/verify_otp.html",
            email=email,
            message="OTP not found. Please request a new OTP."
        )

    if datetime.now() > otp_record["expires_at"]:

        cursor.close()
        connection.close()

        return render_template(
            "customer/verify_otp.html",
            email=email,
            message="OTP has expired. Please request a new OTP."
        )

    if otp_record["attempts"] >= 3:

        cursor.close()
        connection.close()

        return render_template(
            "customer/verify_otp.html",
            email=email,
            message="Maximum OTP attempts exceeded. Please request a new OTP."
        )

    # Verify OTP
    if not check_password_hash(
        otp_record["otp_hash"],
        entered_otp
    ):

        update_query = """
            UPDATE OTP_VERIFICATION
            SET attempts = attempts + 1
            WHERE otp_id = %s
        """

        cursor.execute(
            update_query,
            (otp_record["otp_id"],)
        )

        connection.commit()

        cursor.close()
        connection.close()

        return render_template(
            "customer/verify_otp.html",
            email=email,
            message="Invalid OTP."
        )

    # Login success
    session["customer_email"] = email
    session["customer_logged_in"] = True

    cursor.close()
    connection.close()

    return redirect(
        "/customer/dashboard"
    )


# ============================================================
# CUSTOMER REGISTRATION
# ============================================================

@app.route(
    "/customer/register",
    methods=["GET", "POST"]
)
def customer_register():

    if request.method == "GET":

        return render_template(
            "customer/register.html"
        )

    # ============================================================
    # GET FORM DATA
    # ============================================================

    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip()
    mobile_no = request.form.get("mobile_no", "").strip()
    password = request.form.get("password", "")
    dob = request.form.get("dob", "")
    gender = request.form.get("gender", "").strip()
    father_name = request.form.get("father_name", "").strip()
    address = request.form.get("address", "").strip()
    aadhaar_number = request.form.get("aadhaar_number", "").strip()
    pan_number = request.form.get("pan_number", "").strip().upper()

    # ============================================================
    # GET UPLOADED FILES
    # ============================================================

    aadhaar_photo = request.files.get("aadhaar_photo")
    pan_photo = request.files.get("pan_photo")

    # ============================================================
    # BASIC VALIDATION
    # ============================================================

    if not first_name:
        return render_template(
            "customer/register.html",
            message="First name is required."
        )

    if not last_name:
        return render_template(
            "customer/register.html",
            message="Last name is required."
        )

    if not email:
        return render_template(
            "customer/register.html",
            message="Email is required."
        )

    if not mobile_no:
        return render_template(
            "customer/register.html",
            message="Mobile number is required."
        )

    if not password:
        return render_template(
            "customer/register.html",
            message="Password is required."
        )

    if not dob:
        return render_template(
            "customer/register.html",
            message="Date of birth is required."
        )

    if not gender:
        return render_template(
            "customer/register.html",
            message="Gender is required."
        )

    if not father_name:
        return render_template(
            "customer/register.html",
            message="Father name is required."
        )

    if not address:
        return render_template(
            "customer/register.html",
            message="Address is required."
        )

    # ============================================================
    # AADHAAR VALIDATION
    # ============================================================

    if len(aadhaar_number) != 12 or not aadhaar_number.isdigit():
        return render_template(
            "customer/register.html",
            message="Aadhaar number must contain exactly 12 digits."
        )

    # ============================================================
    # PAN VALIDATION
    # ============================================================

    if len(pan_number) != 10:
        return render_template(
            "customer/register.html",
            message="PAN number must contain exactly 10 characters."
        )

    # ============================================================
    # CHECK UPLOADED FILES
    # ============================================================

    if not aadhaar_photo or aadhaar_photo.filename == "":
        return render_template(
            "customer/register.html",
            message="Please upload Aadhaar card photo."
        )

    if not pan_photo or pan_photo.filename == "":
        return render_template(
            "customer/register.html",
            message="Please upload PAN card photo."
        )

    connection = None
    cursor = None

    try:

        # ========================================================
        # DATABASE CONNECTION
        # ========================================================

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # ========================================================
        # CHECK DUPLICATE EMAIL
        # ========================================================

        cursor.execute(
            """
            SELECT user_id
            FROM `USER`
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )

        if cursor.fetchone():
            return render_template(
                "customer/register.html",
                message="Email is already registered."
            )

        # ========================================================
        # CHECK DUPLICATE MOBILE
        # ========================================================

        cursor.execute(
            """
            SELECT user_id
            FROM `USER`
            WHERE mobile_no = %s
            LIMIT 1
            """,
            (mobile_no,)
        )

        if cursor.fetchone():
            return render_template(
                "customer/register.html",
                message="Mobile number is already registered."
            )

        # ========================================================
        # CHECK DUPLICATE AADHAAR
        # ========================================================

        cursor.execute(
            """
            SELECT user_id
            FROM `USER`
            WHERE aadhaar_number = %s
            LIMIT 1
            """,
            (aadhaar_number,)
        )

        if cursor.fetchone():
            return render_template(
                "customer/register.html",
                message="Aadhaar number is already registered."
            )

        # ========================================================
        # CHECK DUPLICATE PAN
        # ========================================================

        cursor.execute(
            """
            SELECT user_id
            FROM `USER`
            WHERE pan_number = %s
            LIMIT 1
            """,
            (pan_number,)
        )

        if cursor.fetchone():
            return render_template(
                "customer/register.html",
                message="PAN number is already registered."
            )

        # ========================================================
        # SAVE DOCUMENTS
        # ========================================================

        aadhaar_filename = secure_filename(aadhaar_photo.filename)
        pan_filename = secure_filename(pan_photo.filename)

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")

        aadhaar_filename = (
            timestamp + "_aadhaar_" + aadhaar_filename
        )

        pan_filename = (
            timestamp + "_pan_" + pan_filename
        )

        aadhaar_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            aadhaar_filename
        )

        pan_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            pan_filename
        )

        aadhaar_photo.save(aadhaar_path)
        pan_photo.save(pan_path)

        # ========================================================
        # HASH PASSWORD
        # ========================================================

        password_hash = generate_password_hash(password)

        # ========================================================
        # INSERT CUSTOMER INTO USER TABLE
        # ========================================================

        query = """
            INSERT INTO `USER`
            (
                first_name,
                last_name,
                email,
                mobile_no,
                password_hash,
                dob,
                gender,
                father_name,
                address,
                aadhaar_number,
                pan_number,
                aadhaar_photo,
                pan_photo,
                status,
                created_at
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                CURRENT_TIMESTAMP
            )
        """

        values = (
            first_name,
            last_name,
            email,
            mobile_no,
            password_hash,
            dob,
            gender,
            father_name,
            address,
            aadhaar_number,
            pan_number,
            aadhaar_path,
            pan_path,
            "ACTIVE"
        )

        cursor.execute(query, values)
        connection.commit()

        # ========================================================
        # REGISTRATION SUCCESS
        # No registration email is sent.
        # Login OTP email remains unchanged.
        # ========================================================

        return redirect("/customer/login")

    except Exception as e:

        print("REGISTRATION ERROR:", e)

        if connection:
            connection.rollback()

        return render_template(
            "customer/register.html",
            message=f"Registration failed: {e}"
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================================
# CUSTOMER DASHBOARD
# ============================================================

@app.route("/customer/dashboard")
def customer_dashboard():

    # --------------------------------------------------------
    # CHECK CUSTOMER LOGIN
    # --------------------------------------------------------

    if not session.get("customer_logged_in"):

        return redirect(
            "/customer/login"
        )

    # --------------------------------------------------------
    # GET LOGGED-IN CUSTOMER EMAIL
    # --------------------------------------------------------

    email = session.get(
        "customer_email"
    )

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        # ====================================================
        # GET CUSTOMER INFORMATION
        # ====================================================

        customer_query = """
            SELECT
                user_id,
                first_name,
                last_name,
                email,
                status
            FROM `USER`
            WHERE email = %s
            LIMIT 1
        """

        cursor.execute(
            customer_query,
            (email,)
        )

        customer = cursor.fetchone()

        # ----------------------------------------------------
        # CUSTOMER NOT FOUND
        # ----------------------------------------------------

        if customer is None:

            session.clear()

            return redirect(
                "/customer/login"
            )

        # ====================================================
        # GET CUSTOMER ACCOUNT
        # ====================================================

        account_query = """
            SELECT
                account_id,
                account_number,

                'Savings Account' AS account_type,

                status,
                is_frozen,
                created_at

            FROM ACCOUNT

            WHERE user_id = %s

            LIMIT 1
        """

        cursor.execute(
            account_query,
            (customer["user_id"],)
        )

        account = cursor.fetchone()

        # ====================================================
        # ACCOUNT EXISTS
        # ====================================================

        if account:

            account_number = account[
                "account_number"
            ]

            account_type = account[
                "account_type"
            ]

            account_status = account[
                "status"
            ]

            is_frozen = account[
                "is_frozen"
            ]

            created_at = account[
                "created_at"
            ]

            # ------------------------------------------------
            # CALCULATE BALANCE
            # ------------------------------------------------

            balance = get_account_balance(
                cursor,
                account["account_id"]
            )

        # ====================================================
        # NO ACCOUNT
        # ====================================================

        else:

            account_number = None

            account_type = None

            account_status = "NO ACCOUNT"

            is_frozen = 0

            created_at = None

            balance = Decimal(
                "0.00"
            )

        # ====================================================
        # DISPLAY CUSTOMER DASHBOARD
        # ====================================================

        return render_template(
            "customer/dashboard.html",

            first_name=customer[
                "first_name"
            ],

            account_number=account_number,

            account_type=account_type,

            account_status=account_status,

            is_frozen=is_frozen,

            created_at=created_at,

            balance=f"{balance:.2f}"
        )

    finally:

        cursor.close()

        connection.close()

# ============================================================
# CUSTOMER ACCOUNT DETAILS
# ============================================================

# ============================================================
# CUSTOMER ACCOUNT DETAILS
# ============================================================

@app.route("/customer/account")
def customer_account():

    if not session.get("customer_logged_in"):
        return redirect("/customer/login")

    email = session.get("customer_email")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        # --------------------------------------------------------
        # CUSTOMER INFORMATION
        # --------------------------------------------------------

        customer_query = """
            SELECT
                user_id,
                first_name,
                last_name,
                email,
                mobile_no
            FROM `USER`
            WHERE email = %s
            LIMIT 1
        """

        cursor.execute(
            customer_query,
            (email,)
        )

        customer = cursor.fetchone()

        if customer is None:
            session.clear()
            return redirect("/customer/login")


        # --------------------------------------------------------
        # ACCOUNT INFORMATION
        # --------------------------------------------------------

        account_query = """
            SELECT
                account_id,
                account_number,
                account_type,
                branch,
                ifsc_code,
                open_date,
                status,
                is_frozen,
                created_at
            FROM ACCOUNT
            WHERE user_id = %s
            LIMIT 1
        """

        cursor.execute(
            account_query,
            (customer["user_id"],)
        )

        account = cursor.fetchone()


        # --------------------------------------------------------
        # ACCOUNT BALANCE
        # --------------------------------------------------------

        if account:

            balance = get_account_balance(
                cursor,
                account["account_id"]
            )

        else:

            balance = Decimal("0.00")


        # --------------------------------------------------------
        # LINKED ACCOUNTS
        # --------------------------------------------------------

        linked_accounts = []

        if account:

            linked_query = """
                SELECT
                    account_id,
                    account_number,
                    account_type,
                    balance,
                    status
                FROM ACCOUNT
                WHERE user_id = %s
                ORDER BY account_id
            """

            cursor.execute(
                linked_query,
                (customer["user_id"],)
            )

            linked_accounts = cursor.fetchall()

            # Calculate actual balance for every linked account
            for linked in linked_accounts:

                linked["balance"] = get_account_balance(
                    cursor,
                    linked["account_id"]
                )


        return render_template(
            "customer/account.html",
            customer=customer,
            account=account,
            balance=f"{balance:.2f}",
            linked_accounts=linked_accounts
        )

    finally:

        cursor.close()
        connection.close()

# ============================================================
# CUSTOMER PROFILE
# ============================================================

@app.route(
    "/customer/profile",
    methods=["GET"]
)
def customer_profile():

    # --------------------------------------------------------
    # Check customer login
    # --------------------------------------------------------

    if not session.get("customer_logged_in"):

        return redirect(
            "/customer/login"
        )


    # --------------------------------------------------------
    # Get logged-in customer email
    # --------------------------------------------------------

    email = session.get(
        "customer_email"
    )


    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    try:

        # ----------------------------------------------------
        # Get customer information
        # ----------------------------------------------------

        query = """
            SELECT
                user_id,
                first_name,
                last_name,
                email,
                mobile_no,
                dob,
                gender,
                father_name,
                address,
                aadhaar_number,
                pan_number,
                aadhaar_photo,
                pan_photo,
                status,
                created_at
            FROM `USER`
            WHERE email = %s
            LIMIT 1
        """

        cursor.execute(
            query,
            (email,)
        )

        customer = cursor.fetchone()


        # ----------------------------------------------------
        # Customer not found
        # ----------------------------------------------------

        if customer is None:

            session.clear()

            return redirect(
                "/customer/login"
            )


        # ----------------------------------------------------
        # Get account information
        # ----------------------------------------------------

        account_query = """
            SELECT
                account_id,
                account_number,
                status,
                is_frozen,
                created_at
            FROM ACCOUNT
            WHERE user_id = %s
            LIMIT 1
        """

        cursor.execute(
            account_query,
            (customer["user_id"],)
        )

        account = cursor.fetchone()


        # ----------------------------------------------------
        # Get balance
        # ----------------------------------------------------

        if account:

            balance = get_account_balance(
                cursor,
                account["account_id"]
            )

        else:

            balance = Decimal(
                "0.00"
            )


        # ----------------------------------------------------
        # Open profile page
        # ----------------------------------------------------

        return render_template(
            "customer/profile.html",
            customer=customer,
            account=account,
            balance=f"{balance:.2f}"
        )


    except Exception as e:

        return render_template(
            "customer/profile.html",
            customer=customer
            if "customer" in locals()
            else None,
            account=account
            if "account" in locals()
            else None,
            balance="0.00",
            error_message=f"Unable to load profile: {e}"
        )


    finally:

        cursor.close()

        connection.close()
# ============================================================
# CUSTOMER TRANSACTIONS
# ============================================================

@app.route("/customer/transactions")
def customer_transactions():

    if not session.get("customer_logged_in"):

        return redirect(
            "/customer/login"
        )

    email = session.get(
        "customer_email"
    )

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    customer_query = """
        SELECT
            user_id,
            first_name,
            last_name,
            email
        FROM `USER`
        WHERE email = %s
    """

    cursor.execute(
        customer_query,
        (email,)
    )

    customer = cursor.fetchone()

    if customer is None:

        cursor.close()
        connection.close()

        session.clear()

        return redirect(
            "/customer/login"
        )

    account_query = """
        SELECT
            account_id,
            account_number
        FROM ACCOUNT
        WHERE user_id = %s
        LIMIT 1
    """

    cursor.execute(
        account_query,
        (customer["user_id"],)
    )

    account = cursor.fetchone()

    if account is None:

        cursor.close()
        connection.close()

        return render_template(
            "customer/transactions.html",
            account_number=None,
            transactions=[]
        )

    transaction_query = """
        SELECT
            transaction_id,
            reference_num,
            transaction_type,
            amount,
            transaction_date,
            status
        FROM `TRANSACTION`
        WHERE account_id = %s
        ORDER BY transaction_date DESC
    """

    cursor.execute(
        transaction_query,
        (account["account_id"],)
    )

    transactions = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "customer/transactions.html",
        account_number=account["account_number"],
        transactions=transactions
    )


# ============================================================
# CUSTOMER ACCOUNT REQUEST
# ============================================================

@app.route(
    "/customer/account-request",
    methods=["GET", "POST"]
)
def customer_account_request():

    if not session.get("customer_logged_in"):

        return redirect(
            "/customer/login"
        )

    email = session.get(
        "customer_email"
    )

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    customer_query = """
        SELECT
            user_id,
            first_name,
            last_name,
            email,
            status
        FROM `USER`
        WHERE email = %s
    """

    cursor.execute(
        customer_query,
        (email,)
    )

    customer = cursor.fetchone()

    if customer is None:

        cursor.close()
        connection.close()

        session.clear()

        return redirect(
            "/customer/login"
        )

    if request.method == "GET":

        cursor.close()
        connection.close()

        return render_template(
            "customer/account_request.html",
            first_name=customer["first_name"],
            last_name=customer["last_name"],
            email=customer["email"],
            customer_status=customer["status"]
        )

    # Check account
    account_query = """
        SELECT account_id
        FROM ACCOUNT
        WHERE user_id = %s
        LIMIT 1
    """

    cursor.execute(
        account_query,
        (customer["user_id"],)
    )

    account = cursor.fetchone()

    if account:

        cursor.close()
        connection.close()

        return render_template(
            "customer/account_request.html",
            first_name=customer["first_name"],
            last_name=customer["last_name"],
            email=customer["email"],
            customer_status=customer["status"],
            message="You already have a bank account."
        )

    # Check existing request
    request_query = """
        SELECT
            request_id,
            status
        FROM ACCOUNT_REQUEST
        WHERE user_id = %s
        LIMIT 1
    """

    cursor.execute(
        request_query,
        (customer["user_id"],)
    )

    existing_request = cursor.fetchone()

    if existing_request:

        if existing_request["status"] == "PENDING":

            cursor.close()
            connection.close()

            return render_template(
                "customer/account_request.html",
                first_name=customer["first_name"],
                last_name=customer["last_name"],
                email=customer["email"],
                customer_status=customer["status"],
                message="Your account request is already pending."
            )

        if existing_request["status"] == "APPROVED":

            cursor.close()
            connection.close()

            return render_template(
                "customer/account_request.html",
                first_name=customer["first_name"],
                last_name=customer["last_name"],
                email=customer["email"],
                customer_status=customer["status"],
                message="Your account request has already been approved."
            )

        if existing_request["status"] == "REJECTED":

            update_query = """
                UPDATE ACCOUNT_REQUEST
                SET
                    status = 'PENDING',
                    submitted_at = CURRENT_TIMESTAMP,
                    approved_at = NULL
                WHERE request_id = %s
            """

            cursor.execute(
                update_query,
                (
                    existing_request["request_id"],
                )
            )

            connection.commit()

            cursor.close()
            connection.close()

            return redirect(
                "/customer/dashboard"
            )

    # New request
    insert_query = """
        INSERT INTO ACCOUNT_REQUEST
        (
            user_id,
            status,
            submitted_at,
            approved_at
        )
        VALUES
        (
            %s,
            'PENDING',
            CURRENT_TIMESTAMP,
            NULL
        )
    """

    cursor.execute(
        insert_query,
        (
            customer["user_id"],
        )
    )

    connection.commit()

    # ========================================================
    # SEND ACCOUNT REQUEST EMAIL
    # ========================================================
    send_notification_email(
        customer["email"],
        "Core Banking - Account Request Submitted",
        f"""
Dear {customer["first_name"]},

Your bank account request has been submitted successfully.

Status: PENDING

Our bank administrator will review your request.
You will receive another email after the request is approved or rejected.

Regards,
Core Banking System
"""
    )

    cursor.close()
    connection.close()

    return redirect(
        "/customer/dashboard"
    )


# ============================================================
# CUSTOMER DEPOSIT
# ============================================================

@app.route(
    "/customer/deposit",
    methods=["GET", "POST"]
)
def customer_deposit():

    if not session.get("customer_logged_in"):

        return redirect(
            "/customer/login"
        )

    email = session.get(
        "customer_email"
    )

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        customer_query = """
            SELECT
                user_id,
                first_name,
                last_name,
                email
            FROM `USER`
            WHERE email = %s
        """

        cursor.execute(
            customer_query,
            (email,)
        )

        customer = cursor.fetchone()

        if customer is None:

            session.clear()

            return redirect(
                "/customer/login"
            )

        account_query = """
            SELECT
                account_id,
                account_number,
                status,
                is_frozen
            FROM ACCOUNT
            WHERE user_id = %s
            LIMIT 1
        """

        cursor.execute(
            account_query,
            (customer["user_id"],)
        )

        account = cursor.fetchone()

        if account is None:

            return render_template(
                "customer/deposit.html",
                account_number=None,
                account_status="NO ACCOUNT",
                message="You do not have a bank account yet."
            )

        if request.method == "GET":

            return render_template(
                "customer/deposit.html",
                account_number=account["account_number"],
                account_status=account["status"]
            )

        if account["status"] != "ACTIVE":

            return render_template(
                "customer/deposit.html",
                account_number=account["account_number"],
                account_status=account["status"],
                message="Deposits are allowed only for ACTIVE accounts."
            )

        if account["is_frozen"] == 1:

            return render_template(
                "customer/deposit.html",
                account_number=account["account_number"],
                account_status=account["status"],
                message="Your account is frozen. Deposit cannot be performed."
            )

        amount_text = request.form["amount"].strip()

        try:

            amount = Decimal(amount_text)

        except (InvalidOperation, ValueError):

            return render_template(
                "customer/deposit.html",
                account_number=account["account_number"],
                account_status=account["status"],
                message="Please enter a valid amount."
            )

        amount = amount.quantize(
            Decimal("0.01")
        )

        if amount <= 0:

            return render_template(
                "customer/deposit.html",
                account_number=account["account_number"],
                account_status=account["status"],
                message="Deposit amount must be greater than zero."
            )

        # Generate unique reference
        while True:

            reference_num = (
                "DEP"
                + str(
                    random.randint(
                        1000000000,
                        9999999999
                    )
                )
            )

            reference_query = """
                SELECT transaction_id
                FROM `TRANSACTION`
                WHERE reference_num = %s
                LIMIT 1
            """

            cursor.execute(
                reference_query,
                (reference_num,)
            )

            if cursor.fetchone() is None:
                break

        # Insert transaction
        transaction_query = """
            INSERT INTO `TRANSACTION`
            (
                reference_num,
                account_id,
                transaction_type,
                amount,
                transaction_date,
                status
            )
            VALUES
            (
                %s,
                %s,
                'DEPOSIT',
                %s,
                CURRENT_TIMESTAMP,
                'SUCCESS'
            )
        """

        cursor.execute(
            transaction_query,
            (
                reference_num,
                account["account_id"],
                amount
            )
        )

        connection.commit()

        # ========================================================
        # SEND DEPOSIT EMAIL
        # ========================================================
        new_balance = get_account_balance(
            cursor,
            account["account_id"]
        )

        # ========================================================
        # SEND DEPOSIT EMAIL
        # ========================================================

        email_sent = send_notification_email(
            customer["email"],
            "Core Banking - Deposit Successful",
            f"""
Dear {customer["first_name"]},

Your deposit has been completed successfully.

--------------------------------------------
CORE BANKING TRANSACTION ALERT
--------------------------------------------

Transaction Type : DEPOSIT
Account Number   : XXXX{account["account_number"][-4:]}
Amount           : ₹{amount:.2f}
Reference Number : {reference_num}
Available Balance: ₹{new_balance:.2f}
Date             : {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}

--------------------------------------------

If you did not perform this transaction,
please contact the bank immediately.

Regards,
Core Banking System
"""
        )

        if email_sent:

            deposit_message = (
                f"Deposit of ₹{amount:.2f} completed successfully. "
                f"Reference: {reference_num}. "
                f"Email notification sent successfully."
            )

        else:

            deposit_message = (
                f"Deposit of ₹{amount:.2f} completed successfully. "
                f"Reference: {reference_num}. "
                f"However, email notification could not be sent. "
                f"Please check the Flask terminal for the email error."
            )

        return render_template(
            "customer/deposit.html",
            account_number=account["account_number"],
            account_status=account["status"],
            message=deposit_message
        )

    except Exception as e:

        connection.rollback()

        return render_template(
            "customer/deposit.html",
            account_number=(
                account["account_number"]
                if "account" in locals() and account
                else None
            ),
            account_status=(
                account["status"]
                if "account" in locals() and account
                else "UNKNOWN"
            ),
            message=f"Deposit failed: {e}"
        )

    finally:

        cursor.close()
        connection.close()

# ============================================================
# CUSTOMER WITHDRAW
# ============================================================

@app.route(
    "/customer/withdraw",
    methods=["GET", "POST"]
)
def customer_withdraw():

    if not session.get("customer_logged_in"):
        return redirect("/customer/login")

    email = session.get("customer_email")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        # ----------------------------------------------------
        # Get customer
        # ----------------------------------------------------

        customer_query = """
            SELECT
                user_id,
                first_name,
                last_name,
                email
            FROM `USER`
            WHERE email = %s
        """

        cursor.execute(
            customer_query,
            (email,)
        )

        customer = cursor.fetchone()

        if customer is None:

            session.clear()

            return redirect("/customer/login")


        # ----------------------------------------------------
        # Get account
        # ----------------------------------------------------

        account_query = """
            SELECT
                account_id,
                account_number,
                status,
                is_frozen
            FROM ACCOUNT
            WHERE user_id = %s
            LIMIT 1
        """

        cursor.execute(
            account_query,
            (customer["user_id"],)
        )

        account = cursor.fetchone()


        if account is None:

            return render_template(
                "customer/withdraw.html",
                account_number=None,
                account_status="NO ACCOUNT",
                balance="0.00",
                error_message="You do not have a bank account yet."
            )


        # ----------------------------------------------------
        # Calculate current balance
        # ----------------------------------------------------

        balance = get_account_balance(
            cursor,
            account["account_id"]
        )


        # ----------------------------------------------------
        # GET
        # ----------------------------------------------------

        if request.method == "GET":

            return render_template(
                "customer/withdraw.html",
                account_number=account["account_number"],
                account_status=account["status"],
                balance=f"{balance:.2f}"
            )


        # ----------------------------------------------------
        # Account status
        # ----------------------------------------------------

        if account["status"] != "ACTIVE":

            return render_template(
                "customer/withdraw.html",
                account_number=account["account_number"],
                account_status=account["status"],
                balance=f"{balance:.2f}",
                error_message="Withdrawal is allowed only for ACTIVE accounts."
            )


        # ----------------------------------------------------
        # Frozen account
        # ----------------------------------------------------

        if account["is_frozen"] == 1:

            return render_template(
                "customer/withdraw.html",
                account_number=account["account_number"],
                account_status=account["status"],
                balance=f"{balance:.2f}",
                error_message="Your account is frozen. Withdrawal cannot be performed."
            )


        # ----------------------------------------------------
        # Amount
        # ----------------------------------------------------

        amount_text = request.form["amount"].strip()

        try:

            amount = Decimal(amount_text)

        except (InvalidOperation, ValueError):

            return render_template(
                "customer/withdraw.html",
                account_number=account["account_number"],
                account_status=account["status"],
                balance=f"{balance:.2f}",
                error_message="Please enter a valid amount."
            )


        amount = amount.quantize(
            Decimal("0.01")
        )


        # ----------------------------------------------------
        # Validate amount
        # ----------------------------------------------------

        if amount <= 0:

            return render_template(
                "customer/withdraw.html",
                account_number=account["account_number"],
                account_status=account["status"],
                balance=f"{balance:.2f}",
                error_message="Withdrawal amount must be greater than zero."
            )


        # ----------------------------------------------------
        # Check sufficient balance
        # ----------------------------------------------------

        if amount > balance:

            # Create failed transaction reference
            while True:

                reference_num = (
                    "WDR"
                    + str(
                        random.randint(
                            1000000000,
                            9999999999
                        )
                    )
                )

                cursor.execute(
                    """
                    SELECT transaction_id
                    FROM `TRANSACTION`
                    WHERE reference_num = %s
                    LIMIT 1
                    """,
                    (reference_num,)
                )

                if cursor.fetchone() is None:
                    break


            # Record failed withdrawal
            failed_query = """
                INSERT INTO `TRANSACTION`
                (
                    reference_num,
                    account_id,
                    transaction_type,
                    amount,
                    transaction_date,
                    status
                )
                VALUES
                (
                    %s,
                    %s,
                    'WITHDRAW',
                    %s,
                    CURRENT_TIMESTAMP,
                    'FAILED'
                )
            """

            cursor.execute(
                failed_query,
                (
                    reference_num,
                    account["account_id"],
                    amount
                )
            )

            connection.commit()

            return render_template(
                "customer/withdraw.html",
                account_number=account["account_number"],
                account_status=account["status"],
                balance=f"{balance:.2f}",
                error_message=(
                    f"Insufficient balance. "
                    f"Available balance is ₹{balance:.2f}."
                )
            )


        # ----------------------------------------------------
        # Generate successful withdrawal reference
        # ----------------------------------------------------

        while True:

            reference_num = (
                "WDR"
                + str(
                    random.randint(
                        1000000000,
                        9999999999
                    )
                )
            )

            cursor.execute(
                """
                SELECT transaction_id
                FROM `TRANSACTION`
                WHERE reference_num = %s
                LIMIT 1
                """,
                (reference_num,)
            )

            if cursor.fetchone() is None:
                break


        # ----------------------------------------------------
        # Insert successful withdrawal
        # ----------------------------------------------------

        withdraw_query = """
            INSERT INTO `TRANSACTION`
            (
                reference_num,
                account_id,
                transaction_type,
                amount,
                transaction_date,
                status
            )
            VALUES
            (
                %s,
                %s,
                'WITHDRAW',
                %s,
                CURRENT_TIMESTAMP,
                'SUCCESS'
            )
        """

        cursor.execute(
            withdraw_query,
            (
                reference_num,
                account["account_id"],
                amount
            )
        )


        connection.commit()


        # ----------------------------------------------------
        # New balance
        # ----------------------------------------------------

        new_balance = balance - amount

        # ========================================================
        # SEND WITHDRAWAL EMAIL
        # ========================================================
        send_notification_email(
            customer["email"],
            "Core Banking - Withdrawal Successful",
            f"""
Dear {customer["first_name"]},

Your withdrawal was successful.

Transaction Type : Withdrawal
Account Number   : XXXX{account["account_number"][-4:]}
Amount           : ₹{amount:.2f}
Reference Number : {reference_num}
Available Balance: ₹{new_balance:.2f}
Date             : {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}

Regards,
Core Banking System
"""
        )

        return render_template(
            "customer/withdraw.html",
            account_number=account["account_number"],
            account_status=account["status"],
            balance=f"{new_balance:.2f}",
            success_message=(
                f"Withdrawal of ₹{amount:.2f} "
                f"completed successfully. "
                f"Reference: {reference_num}"
            )
        )


    except Exception as e:

        connection.rollback()

        return render_template(
            "customer/withdraw.html",
            account_number=(
                account["account_number"]
                if "account" in locals() and account
                else None
            ),
            account_status=(
                account["status"]
                if "account" in locals() and account
                else "UNKNOWN"
            ),
            balance=(
                f"{balance:.2f}"
                if "balance" in locals()
                else "0.00"
            ),
            error_message=f"Withdrawal failed: {e}"
        )


    finally:

        cursor.close()
        connection.close()

# ============================================================
# CUSTOMER FUND TRANSFER
# ============================================================

@app.route(
    "/customer/transfer",
    methods=["GET", "POST"]
)
def customer_transfer():

    # --------------------------------------------------------
    # CHECK CUSTOMER LOGIN
    # --------------------------------------------------------

    if not session.get("customer_logged_in"):

        return redirect("/customer/login")


    email = session.get("customer_email")


    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    try:

        # ----------------------------------------------------
        # GET CUSTOMER
        # ----------------------------------------------------

        customer_query = """
            SELECT
                user_id,
                first_name,
                last_name,
                email
            FROM `USER`
            WHERE email = %s
        """

        cursor.execute(
            customer_query,
            (email,)
        )

        customer = cursor.fetchone()


        if customer is None:

            session.clear()

            return redirect(
                "/customer/login"
            )


        # ----------------------------------------------------
        # GET SENDER ACCOUNT
        # ----------------------------------------------------

        account_query = """
            SELECT
                account_id,
                account_number,
                status,
                is_frozen
            FROM ACCOUNT
            WHERE user_id = %s
            LIMIT 1
        """

        cursor.execute(
            account_query,
            (customer["user_id"],)
        )

        sender_account = cursor.fetchone()


        # ----------------------------------------------------
        # NO ACCOUNT
        # ----------------------------------------------------

        if sender_account is None:

            return render_template(
                "customer/transfer.html",
                account_number=None,
                balance="0.00",
                error_message=(
                    "You do not have a bank account yet."
                )
            )


        # ----------------------------------------------------
        # GET CURRENT BALANCE
        # ----------------------------------------------------

        balance = get_account_balance(
            cursor,
            sender_account["account_id"]
        )


        # ----------------------------------------------------
        # GET REQUEST
        # ----------------------------------------------------

        if request.method == "GET":

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}"
            )


        # ----------------------------------------------------
        # CHECK SENDER STATUS
        # ----------------------------------------------------

        if sender_account["status"] != "ACTIVE":

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Your account is not active."
                )
            )


        # ----------------------------------------------------
        # CHECK SENDER FROZEN
        # ----------------------------------------------------

        if sender_account["is_frozen"] == 1:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Your account is frozen. "
                    "Fund transfer is not allowed."
                )
            )


        # ====================================================
        # FORM VALUES
        # ====================================================

        to_account_number = request.form[
            "to_account_number"
        ].strip()


        to_ifsc = request.form[
            "to_ifsc"
        ].strip().upper()


        transfer_type = request.form[
            "transfer_type"
        ].strip().upper()


        amount_text = request.form[
            "amount"
        ].strip()


        # ====================================================
        # GET SENDER IFSC AUTOMATICALLY
        # ====================================================

        sender_branch_query = """
            SELECT
                ifsc_code
            FROM BANK_BRANCH
            WHERE status = 'ACTIVE'
            ORDER BY branch_id
            LIMIT 1
        """

        cursor.execute(
            sender_branch_query
        )

        sender_branch = cursor.fetchone()


        if sender_branch is None:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "No active bank branch is configured."
                )
            )


        sender_ifsc = sender_branch["ifsc_code"]


        # ====================================================
        # VALIDATE RECEIVER ACCOUNT NUMBER
        # ====================================================

        if not to_account_number:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Please enter the receiver account number."
                )
            )


        # ====================================================
        # VALIDATE RECEIVER IFSC
        # ====================================================

        if not to_ifsc:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Please enter the receiver IFSC."
                )
            )


        cursor.execute(
            """
            SELECT
                branch_id,
                ifsc_code
            FROM BANK_BRANCH
            WHERE ifsc_code = %s
              AND status = 'ACTIVE'
            LIMIT 1
            """,
            (to_ifsc,)
        )

        receiver_branch = cursor.fetchone()


        if receiver_branch is None:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Receiver IFSC is invalid or inactive."
                )
            )


        # ====================================================
        # VALIDATE TRANSFER TYPE
        # ====================================================

        if transfer_type not in (
            "IMPS",
            "NEFT",
            "RTGS"
        ):

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Please select a valid transfer type."
                )
            )


        # ====================================================
        # VALIDATE AMOUNT
        # ====================================================

        try:

            amount = Decimal(
                amount_text
            )

        except (InvalidOperation, ValueError):

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Please enter a valid transfer amount."
                )
            )


        amount = amount.quantize(
            Decimal("0.01")
        )


        if amount <= 0:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Transfer amount must be greater than zero."
                )
            )


        # ====================================================
        # PREVENT SELF TRANSFER
        # ====================================================

        if (
            to_account_number
            == sender_account["account_number"]
        ):

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "You cannot transfer money to your own account."
                )
            )


        # ====================================================
        # FIND RECEIVER ACCOUNT
        # ====================================================

        receiver_query = """
            SELECT
                account_id,
                account_number,
                status,
                is_frozen
            FROM ACCOUNT
            WHERE account_number = %s
            LIMIT 1
        """

        cursor.execute(
            receiver_query,
            (to_account_number,)
        )

        receiver_account = cursor.fetchone()

        # ====================================================
        # GET RECEIVER CUSTOMER DETAILS FOR EMAIL
        # ====================================================
        receiver_customer = None

        if receiver_account is not None:
            receiver_customer_query = """
                SELECT
                    u.first_name,
                    u.last_name,
                    u.email
                FROM ACCOUNT a
                INNER JOIN `USER` u
                    ON a.user_id = u.user_id
                WHERE a.account_id = %s
                LIMIT 1
            """

            cursor.execute(
                receiver_customer_query,
                (receiver_account["account_id"],)
            )

            receiver_customer = cursor.fetchone()


        if receiver_account is None:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Receiver account was not found."
                )
            )


        # ====================================================
        # CHECK RECEIVER STATUS
        # ====================================================

        if receiver_account["status"] != "ACTIVE":

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Receiver account is not active."
                )
            )


        # ====================================================
        # CHECK RECEIVER FROZEN
        # ====================================================

        if receiver_account["is_frozen"] == 1:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    "Receiver account is frozen."
                )
            )


        # ====================================================
        # CHECK SUFFICIENT BALANCE
        # ====================================================

        if amount > balance:

            return render_template(
                "customer/transfer.html",
                account_number=(
                    sender_account["account_number"]
                ),
                balance=f"{balance:.2f}",
                error_message=(
                    f"Insufficient balance. "
                    f"Available balance is ₹{balance:.2f}."
                )
            )


        # ====================================================
        # GENERATE UNIQUE TRANSFER REFERENCE
        # ====================================================

        while True:

            reference_num = (
                "TRF"
                + str(
                    random.randint(
                        1000000000,
                        9999999999
                    )
                )
            )


            cursor.execute(
                """
                SELECT
                    transfer_id
                FROM FUND_TRANSFER
                WHERE reference_num = %s
                LIMIT 1
                """,
                (reference_num,)
            )


            if cursor.fetchone() is None:

                break


        # ====================================================
        # INSERT FUND TRANSFER
        # ====================================================

        transfer_query = """
            INSERT INTO FUND_TRANSFER
            (
                reference_num,
                from_account_id,
                to_account_id,
                from_ifsc,
                to_ifsc,
                amount,
                transfer_type,
                status,
                transfer_date
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'SUCCESS',
                CURRENT_TIMESTAMP
            )
        """


        cursor.execute(
            transfer_query,
            (
                reference_num,
                sender_account["account_id"],
                receiver_account["account_id"],
                sender_ifsc,
                to_ifsc,
                amount,
                transfer_type
            )
        )


        # ====================================================
        # CREATE SENDER TRANSACTION RECORD
        # ====================================================

        sender_transaction_ref = (
            reference_num + "-S"
        )


        cursor.execute(
            """
            INSERT INTO `TRANSACTION`
            (
                reference_num,
                account_id,
                transaction_type,
                amount,
                transaction_date,
                status
            )
            VALUES
            (
                %s,
                %s,
                'TRANSFER',
                %s,
                CURRENT_TIMESTAMP,
                'SUCCESS'
            )
            """,
            (
                sender_transaction_ref,
                sender_account["account_id"],
                amount
            )
        )


        # ====================================================
        # CREATE RECEIVER TRANSACTION RECORD
        # ====================================================

        receiver_transaction_ref = (
            reference_num + "-R"
        )


        cursor.execute(
            """
            INSERT INTO `TRANSACTION`
            (
                reference_num,
                account_id,
                transaction_type,
                amount,
                transaction_date,
                status
            )
            VALUES
            (
                %s,
                %s,
                'TRANSFER',
                %s,
                CURRENT_TIMESTAMP,
                'SUCCESS'
            )
            """,
            (
                receiver_transaction_ref,
                receiver_account["account_id"],
                amount
            )
        )


        # ====================================================
        # COMMIT ALL TRANSFER OPERATIONS
        # ====================================================

        connection.commit()

        # ====================================================
        # SEND TRANSFER EMAIL TO SENDER
        # ====================================================
        new_sender_balance = balance - amount

        send_notification_email(
            customer["email"],
            "Core Banking - Fund Transfer Successful",
            f"""
Dear {customer["first_name"]},

Your fund transfer was successful.

Transfer Type    : {transfer_type}
From Account     : XXXX{sender_account["account_number"][-4:]}
To Account       : XXXX{receiver_account["account_number"][-4:]}
Amount           : ₹{amount:.2f}
Reference Number : {reference_num}
Available Balance: ₹{new_sender_balance:.2f}
Date             : {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}

If you did not perform this transaction, please contact the bank immediately.

Regards,
Core Banking System
"""
        )

        # ====================================================
        # SEND TRANSFER EMAIL TO RECEIVER
        # ====================================================
        if receiver_customer:
            receiver_balance = get_account_balance(
                cursor,
                receiver_account["account_id"]
            )

            send_notification_email(
                receiver_customer["email"],
                "Core Banking - Amount Credited",
                f"""
Dear {receiver_customer["first_name"]},

An amount has been credited to your bank account.

Transfer Type    : {transfer_type}
From Account     : XXXX{sender_account["account_number"][-4:]}
To Account       : XXXX{receiver_account["account_number"][-4:]}
Amount           : ₹{amount:.2f}
Reference Number : {reference_num}
Available Balance: ₹{receiver_balance:.2f}
Date             : {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}

Regards,
Core Banking System
"""
            )

        # ====================================================
        # CALCULATE NEW SENDER BALANCE
        # ====================================================

        new_balance = (
            balance - amount
        )


        # ====================================================
        # SUCCESS MESSAGE
        # ====================================================

        return render_template(
            "customer/transfer.html",
            account_number=(
                sender_account["account_number"]
            ),
            balance=f"{new_balance:.2f}",
            success_message=(
                f"Transfer of ₹{amount:.2f} "
                f"completed successfully. "
                f"Reference: {reference_num}"
            )
        )


    # ========================================================
    # ERROR HANDLING
    # ========================================================

    except Exception as e:

        connection.rollback()


        return render_template(
            "customer/transfer.html",

            account_number=(
                sender_account["account_number"]
                if (
                    "sender_account" in locals()
                    and sender_account
                )
                else None
            ),

            balance=(
                f"{balance:.2f}"
                if "balance" in locals()
                else "0.00"
            ),

            error_message=(
                f"Transfer failed: {e}"
            )
        )


    # ========================================================
    # CLOSE DATABASE CONNECTION
    # ========================================================

    finally:

        cursor.close()

        connection.close()

# ============================================================
# CUSTOMER LOGOUT
# ============================================================

@app.route("/customer/logout")
def customer_logout():

    session.clear()

    return redirect("/")


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route(
    "/admin/login",
    methods=["GET", "POST"]
)
def admin_login():

    # ========================================================
    # GET REQUEST
    # Generate CAPTCHA
    # ========================================================

    if request.method == "GET":

        captcha = generate_captcha()

        session["admin_captcha"] = captcha

        return render_template(
            "admin/login.html",
            captcha=captcha
        )


    # ========================================================
    # GET FORM DATA
    # ========================================================

    email = request.form["email"].strip()

    password = request.form["password"]

    entered_captcha = request.form.get(
        "captcha",
        ""
    ).strip()


    # ========================================================
    # CHECK CAPTCHA
    # ========================================================

    correct_captcha = session.get(
        "admin_captcha"
    )


    if not correct_captcha:

        new_captcha = generate_captcha()

        session["admin_captcha"] = new_captcha

        return render_template(
            "admin/login.html",
            message="CAPTCHA expired. Please try again.",
            captcha=new_captcha
        )


    if entered_captcha.lower() != correct_captcha.lower():

        new_captcha = generate_captcha()

        session["admin_captcha"] = new_captcha

        return render_template(
            "admin/login.html",
            message="Invalid CAPTCHA. Please enter the CAPTCHA correctly.",
            captcha=new_captcha
        )


    # ========================================================
    # CAPTCHA CORRECT
    # Remove used CAPTCHA
    # ========================================================

    session.pop(
        "admin_captcha",
        None
    )


    # ========================================================
    # CHECK ADMIN FROM DATABASE
    # ========================================================

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    query = """
        SELECT
            admin_id,
            admin_name,
            email,
            password_hash,
            role,
            status
        FROM ADMIN
        WHERE email = %s
    """


    cursor.execute(
        query,
        (email,)
    )


    admin = cursor.fetchone()


    cursor.close()

    connection.close()


    # ========================================================
    # ADMIN NOT FOUND
    # ========================================================

    if admin is None:

        new_captcha = generate_captcha()

        session["admin_captcha"] = new_captcha

        return render_template(
            "admin/login.html",
            message="Admin email is not registered.",
            captcha=new_captcha
        )


    # ========================================================
    # ADMIN STATUS CHECK
    # ========================================================

    if admin["status"] != "ACTIVE":

        new_captcha = generate_captcha()

        session["admin_captcha"] = new_captcha

        return render_template(
            "admin/login.html",
            message="Admin account is inactive or blocked.",
            captcha=new_captcha
        )


    # ========================================================
    # PASSWORD CHECK
    # ========================================================

    if not check_password_hash(
        admin["password_hash"],
        password
    ):

        new_captcha = generate_captcha()

        session["admin_captcha"] = new_captcha

        return render_template(
            "admin/login.html",
            message="Invalid password.",
            captcha=new_captcha
        )


    # ========================================================
    # ADMIN LOGIN SUCCESS
    # ========================================================

    session["admin_logged_in"] = True

    session["admin_id"] = admin["admin_id"]

    session["admin_name"] = admin["admin_name"]

    session["admin_role"] = admin["role"]


    return redirect(
        "/admin/dashboard"
    )

@app.route('/admin/branches')
def admin_branches():

    # Check admin login
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))

    # Optional role check
    if session.get('role') != 'ADMIN':
        return redirect(url_for('admin_login'))

    try:
        cursor = mysql.connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                branch_id,
                branch_name,
                branch_code,
                ifsc_code,
                city,
                state,
                status
            FROM BRANCH
            ORDER BY branch_id DESC
        """)

        branches = cursor.fetchall()

        cursor.close()

        return render_template(
            'admin/branches.html',
            branches=branches
        )

    except Exception as e:
        print("Branch Management Error:", e)

        return render_template(
            'admin/branches.html',
            branches=[]
        )
    
# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin/dashboard")
def admin_dashboard():

    # --------------------------------------------------------
    # CHECK ADMIN LOGIN
    # --------------------------------------------------------

    if not session.get("admin_logged_in"):
        return redirect("/admin/login")


    # --------------------------------------------------------
    # DATABASE CONNECTION
    # --------------------------------------------------------

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    try:

        # ====================================================
        # GET LOGGED-IN ADMIN DETAILS
        # ====================================================

        admin_id = session.get("admin_id")

        admin_query = """
            SELECT
                admin_id,
                admin_name,
                email,
                role,
                status
            FROM ADMIN
            WHERE admin_id = %s
        """

        cursor.execute(
            admin_query,
            (admin_id,)
        )

        admin = cursor.fetchone()


        # ----------------------------------------------------
        # ADMIN NOT FOUND
        # ----------------------------------------------------

        if admin is None:

            session.clear()

            return redirect(
                "/admin/login"
            )


        # ====================================================
        # TOTAL CUSTOMERS
        # ====================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS total_customers
            FROM `USER`
        """)

        result = cursor.fetchone()

        total_customers = (
            result["total_customers"]
            or 0
        )


        # ====================================================
        # TOTAL ACCOUNTS
        # ====================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS total_accounts
            FROM ACCOUNT
        """)

        result = cursor.fetchone()

        total_accounts = (
            result["total_accounts"]
            or 0
        )


        # ====================================================
        # PENDING ACCOUNT REQUESTS
        # ====================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS pending_requests
            FROM ACCOUNT_REQUEST
            WHERE status = 'PENDING'
        """)

        result = cursor.fetchone()

        pending_requests = (
            result["pending_requests"]
            or 0
        )


        # ====================================================
        # TODAY'S TRANSACTIONS
        # ====================================================

        cursor.execute("""
            SELECT
                COUNT(*) AS today_transactions
            FROM `TRANSACTION`
            WHERE DATE(transaction_date) = CURDATE()
        """)

        result = cursor.fetchone()

        today_transactions = (
            result["today_transactions"]
            or 0
        )


        # ====================================================
        # PENDING ACCOUNT REQUEST LIST
        # ====================================================

        cursor.execute("""
            SELECT
                ar.request_id,
                ar.status,
                u.first_name,
                u.last_name
            FROM ACCOUNT_REQUEST ar

            INNER JOIN `USER` u
                ON ar.user_id = u.user_id

            WHERE ar.status = 'PENDING'

            ORDER BY ar.submitted_at DESC

            LIMIT 5
        """)

        pending_request_list = cursor.fetchall()


        # ====================================================
        # DISPLAY ADMIN DASHBOARD
        # ====================================================

        return render_template(

            "admin/dashboard.html",

            # Logged-in admin details
            admin=admin,

            # Existing dashboard information
            admin_name=admin["admin_name"],
            role=admin["role"],

            total_customers=total_customers,

            total_accounts=total_accounts,

            pending_requests=pending_requests,

            today_transactions=today_transactions,

            pending_request_list=pending_request_list
        )


    finally:

        cursor.close()

        connection.close()

# ============================================================
# ADMIN CUSTOMER MANAGEMENT
# ============================================================

@app.route("/admin/customers")
def admin_customers():

    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    search = request.args.get(
        "search",
        ""
    ).strip()

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        # ====================================================
        # SEARCH CUSTOMERS
        # ====================================================

        if search:

            query = """
                SELECT
                    u.user_id,
                    u.first_name,
                    u.last_name,
                    u.email,
                    u.mobile_no,
                    u.status,
                    u.created_at,

                    a.account_id,
                    a.account_number,
                    a.status AS account_status

                FROM `USER` u

                LEFT JOIN ACCOUNT a
                    ON u.user_id = a.user_id

                WHERE
                    u.first_name LIKE %s
                    OR u.last_name LIKE %s
                    OR CONCAT(
                        u.first_name,
                        ' ',
                        u.last_name
                    ) LIKE %s
                    OR u.email LIKE %s
                    OR u.mobile_no LIKE %s
                    OR a.account_number LIKE %s

                ORDER BY u.created_at DESC
            """

            search_value = f"%{search}%"

            cursor.execute(
                query,
                (
                    search_value,
                    search_value,
                    search_value,
                    search_value,
                    search_value,
                    search_value
                )
            )

        # ====================================================
        # ALL CUSTOMERS
        # ====================================================

        else:

            query = """
                SELECT
                    u.user_id,
                    u.first_name,
                    u.last_name,
                    u.email,
                    u.mobile_no,
                    u.status,
                    u.created_at,

                    a.account_id,
                    a.account_number,
                    a.status AS account_status

                FROM `USER` u

                LEFT JOIN ACCOUNT a
                    ON u.user_id = a.user_id

                ORDER BY u.created_at DESC
            """

            cursor.execute(query)


        customers = cursor.fetchall()


        return render_template(
            "admin/customers.html",
            customers=customers,
            search=search
        )


    finally:

        cursor.close()
        connection.close()


# ============================================================
# ADMIN KYC
# CUSTOMER + KYC + ACCOUNT + TRANSACTIONS
# ============================================================

@app.route("/admin/kyc")
def admin_kyc():

    if not session.get("admin_logged_in"):
        return redirect("/admin/login")


    # Optional customer ID

    user_id = request.args.get("user_id")


    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)


    try:

        # ====================================================
        # CUSTOMER QUERY
        # ====================================================

        customer_query = """

            SELECT

                u.user_id,
                u.first_name,
                u.last_name,
                u.email,
                u.mobile_no,

                u.dob,
                u.gender,
                u.father_name,
                u.address,

                u.aadhaar_number,
                u.aadhaar_photo,

                u.pan_number,
                u.pan_photo,

                u.status AS customer_status,
                u.created_at,

                a.account_id,
                a.account_number,
                a.status AS account_status,
                a.is_frozen,
                a.created_at AS account_created_at

            FROM `USER` u

            LEFT JOIN ACCOUNT a
                ON u.user_id = a.user_id

        """


        # ====================================================
        # CUSTOMER SELECTED
        # ====================================================

        if user_id:

            customer_query += """
                WHERE u.user_id = %s
                LIMIT 1
            """

            cursor.execute(
                customer_query,
                (user_id,)
            )


        # ====================================================
        # NO CUSTOMER SELECTED
        # ====================================================

        else:

            return render_template(
                "admin/kyc.html",
                customer=None,
                transactions=[],
                total_transactions=0,
                total_credit=Decimal("0.00"),
                total_debit=Decimal("0.00")
            )


        customer = cursor.fetchone()


        # ====================================================
        # CUSTOMER NOT FOUND
        # ====================================================

        if customer is None:

            return (
                "Customer not found.",
                404
            )


        # ====================================================
        # DEFAULT TRANSACTION VALUES
        # ====================================================

        transactions = []

        total_transactions = 0

        total_credit = Decimal("0.00")

        total_debit = Decimal("0.00")


        account_id = customer["account_id"]


        # ====================================================
        # GET TRANSACTIONS
        # ====================================================

        if account_id is not None:


            transaction_query = """

                SELECT

                    transaction_id,
                    reference_num,
                    transaction_type,
                    amount,
                    transaction_date,
                    status

                FROM `TRANSACTION`

                WHERE account_id = %s

                ORDER BY transaction_date DESC

            """


            cursor.execute(
                transaction_query,
                (account_id,)
            )


            transactions = cursor.fetchall()


            # =================================================
            # TOTAL TRANSACTIONS
            # =================================================

            count_query = """

                SELECT
                    COUNT(*) AS total_transactions

                FROM `TRANSACTION`

                WHERE account_id = %s

            """


            cursor.execute(
                count_query,
                (account_id,)
            )


            count_result = cursor.fetchone()


            total_transactions = (
                count_result["total_transactions"] or 0
            )


            # =================================================
            # TOTAL CREDIT
            # =================================================

            credit_query = """

                SELECT

                    COALESCE(
                        SUM(amount),
                        0
                    ) AS total_credit

                FROM `TRANSACTION`

                WHERE account_id = %s

                AND status = 'SUCCESS'

                AND transaction_type = 'DEPOSIT'

            """


            cursor.execute(
                credit_query,
                (account_id,)
            )


            credit_result = cursor.fetchone()


            total_credit = Decimal(
                str(
                    credit_result["total_credit"] or 0
                )
            )


            # =================================================
            # TOTAL DEBIT
            # =================================================

            debit_query = """

                SELECT

                    COALESCE(
                        SUM(amount),
                        0
                    ) AS total_debit

                FROM `TRANSACTION`

                WHERE account_id = %s

                AND status = 'SUCCESS'

                AND transaction_type IN
                    ('WITHDRAW', 'TRANSFER')

            """


            cursor.execute(
                debit_query,
                (account_id,)
            )


            debit_result = cursor.fetchone()


            total_debit = Decimal(
                str(
                    debit_result["total_debit"] or 0
                )
            )


        # ====================================================
        # RENDER KYC PAGE
        # ====================================================

        return render_template(

            "admin/kyc.html",

            customer=customer,

            transactions=transactions,

            total_transactions=total_transactions,

            total_credit=total_credit,

            total_debit=total_debit

        )


    finally:

        cursor.close()
        connection.close()


# ============================================================
# ADMIN KYC DOCUMENT
#
# IMPORTANT:
# THIS MUST EXIST ONLY ONCE IN app.py
# ============================================================

@app.route("/admin/kyc/document/<path:filename>")
def admin_kyc_document(filename):

    if not session.get("admin_logged_in"):
        return redirect("/admin/login")


    # --------------------------------------------------------
    # Normalize Windows/Linux path
    # --------------------------------------------------------

    filename = filename.replace("\\", "/")


    # --------------------------------------------------------
    # If database contains:
    #
    # static/uploads/file.jpg
    #
    # keep only:
    #
    # file.jpg
    # --------------------------------------------------------

    filename = os.path.basename(filename)


    return send_from_directory(

        app.config["UPLOAD_FOLDER"],

        filename

    )


# ============================================================
# ADMIN CUSTOMER DETAILS
#
# Customer name click -> KYC page
# ============================================================

@app.route("/admin/customer/<int:user_id>")
def admin_customer_details(user_id):

    if not session.get("admin_logged_in"):
        return redirect("/admin/login")


    return redirect(

        url_for(
            "admin_kyc",
            user_id=user_id
        )

    )


# ============================================================
# ADMIN TRANSACTIONS
#
# Shows all transactions OR one customer's transactions
# ============================================================

@app.route("/admin/transactions")
def admin_transactions():

    if not session.get("admin_logged_in"):
        return redirect("/admin/login")


    account_id = request.args.get(
        "account_id"
    )


    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )


    try:

        # ====================================================
        # BASE QUERY
        # ====================================================

        transaction_query = """

            SELECT

                t.transaction_id,
                t.reference_num,

                t.account_id,

                a.account_number,
                a.user_id,

                u.first_name,
                u.last_name,

                t.transaction_type,
                t.amount,
                t.transaction_date,
                t.status

            FROM `TRANSACTION` t

            INNER JOIN ACCOUNT a
                ON t.account_id = a.account_id

            INNER JOIN `USER` u
                ON a.user_id = u.user_id

        """


        # ====================================================
        # SPECIFIC ACCOUNT
        # ====================================================

        if account_id:

            transaction_query += """

                WHERE t.account_id = %s

                ORDER BY
                    t.transaction_date DESC

            """


            cursor.execute(
                transaction_query,
                (account_id,)
            )


        # ====================================================
        # ALL TRANSACTIONS
        # ====================================================

        else:

            transaction_query += """

                ORDER BY
                    t.transaction_date DESC

            """


            cursor.execute(
                transaction_query
            )


        transactions = cursor.fetchall()


        # ====================================================
        # CUSTOMER INFORMATION
        # ====================================================

        customer = None


        if account_id:


            customer_query = """

                SELECT

                    u.user_id,
                    u.first_name,
                    u.last_name,

                    a.account_id,
                    a.account_number

                FROM ACCOUNT a

                INNER JOIN `USER` u
                    ON a.user_id = u.user_id

                WHERE a.account_id = %s

                LIMIT 1

            """


            cursor.execute(
                customer_query,
                (account_id,)
            )


            customer = cursor.fetchone()


        # ====================================================
        # TRANSACTION SUMMARY
        # ====================================================

        total_transactions = 0

        total_credit = Decimal("0.00")

        total_debit = Decimal("0.00")


        if account_id:


            # Total count

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_transactions

                FROM `TRANSACTION`

                WHERE account_id = %s
                """,
                (account_id,)
            )


            result = cursor.fetchone()


            total_transactions = (
                result["total_transactions"] or 0
            )


            # Total credit

            cursor.execute(
                """

                SELECT

                    COALESCE(
                        SUM(amount),
                        0
                    ) AS total_credit

                FROM `TRANSACTION`

                WHERE account_id = %s

                AND status = 'SUCCESS'

                AND transaction_type = 'DEPOSIT'

                """,
                (account_id,)
            )


            result = cursor.fetchone()


            total_credit = Decimal(
                str(
                    result["total_credit"] or 0
                )
            )


            # Total debit

            cursor.execute(
                """

                SELECT

                    COALESCE(
                        SUM(amount),
                        0
                    ) AS total_debit

                FROM `TRANSACTION`

                WHERE account_id = %s

                AND status = 'SUCCESS'

                AND transaction_type IN
                    ('WITHDRAW', 'TRANSFER')

                """,
                (account_id,)
            )


            result = cursor.fetchone()


            total_debit = Decimal(
                str(
                    result["total_debit"] or 0
                )
            )


        # ====================================================
        # RENDER
        # ====================================================

        return render_template(

            "admin/transactions.html",

            transactions=transactions,

            customer=customer,

            total_transactions=total_transactions,

            total_credit=total_credit,

            total_debit=total_debit

        )


    finally:

        cursor.close()
        connection.close()


# ============================================================
# ADMIN ACCOUNT MANAGEMENT
# ============================================================

@app.route("/admin/accounts")
def admin_accounts():

    # Check admin login
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        query = """
            SELECT
                a.account_id,
                a.account_number,
                a.status,
                a.is_frozen,
                a.created_at,

                u.user_id,
                u.first_name,
                u.last_name,
                u.email

            FROM ACCOUNT a

            INNER JOIN `USER` u
                ON a.user_id = u.user_id

            ORDER BY a.created_at DESC
        """

        cursor.execute(query)

        accounts = cursor.fetchall()

        return render_template(
            "admin/accounts.html",
            accounts=accounts
        )

    finally:

        cursor.close()
        connection.close()


# ============================================================
# ADMIN ACCOUNT DETAILS
# ============================================================

@app.route("/admin/account/<int:account_id>")
def admin_account_details(account_id):

    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        # --------------------------------------------------------
        # ACCOUNT + CUSTOMER DETAILS
        # --------------------------------------------------------

        account_query = """
            SELECT
                a.account_id,
                a.account_number,
                a.account_type,
                a.branch,
                a.ifsc_code,
                a.open_date,
                a.status,
                a.is_frozen,
                a.created_at,

                u.user_id,
                u.first_name,
                u.last_name,
                u.email,
                u.mobile_no

            FROM ACCOUNT a

            INNER JOIN `USER` u
                ON a.user_id = u.user_id

            WHERE a.account_id = %s

            LIMIT 1
        """

        cursor.execute(
            account_query,
            (account_id,)
        )

        account = cursor.fetchone()

        if account is None:
            return "Account not found."


        # --------------------------------------------------------
        # CURRENT BALANCE
        # --------------------------------------------------------

        balance = get_account_balance(
            cursor,
            account["account_id"]
        )


        # --------------------------------------------------------
        # LINKED ACCOUNTS
        # --------------------------------------------------------

        linked_query = """
            SELECT
                account_id,
                account_number,
                account_type,
                status
            FROM ACCOUNT
            WHERE user_id = %s
            ORDER BY account_id
        """

        cursor.execute(
            linked_query,
            (account["user_id"],)
        )

        linked_accounts = cursor.fetchall()


        # Calculate balances
        for linked in linked_accounts:

            linked["balance"] = get_account_balance(
                cursor,
                linked["account_id"]
            )


        return render_template(
            "admin/account_details.html",
            account=account,
            balance=f"{balance:.2f}",
            linked_accounts=linked_accounts
        )

    finally:

        cursor.close()
        connection.close()

# ============================================================
# ADMIN ACCOUNT REQUESTS
# ============================================================

@app.route("/admin/requests")
def admin_requests():

    if not session.get("admin_logged_in"):

        return redirect(
            "/admin/login"
        )

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    query = """
        SELECT
            ar.request_id,
            ar.user_id,
            ar.status,
            ar.submitted_at,
            ar.approved_at,

            u.first_name,
            u.last_name,
            u.email,
            u.mobile_no,
            u.aadhaar_number,
            u.pan_number,
            u.aadhaar_photo,
            u.pan_photo

        FROM ACCOUNT_REQUEST ar

        INNER JOIN `USER` u
            ON ar.user_id = u.user_id

        ORDER BY ar.submitted_at DESC
    """

    cursor.execute(
        query
    )

    requests = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "admin/account_requests.html",
        requests=requests
    )


# ============================================================
# ADMIN APPROVE ACCOUNT REQUEST
# ============================================================

@app.route(
    "/admin/account-request/<int:request_id>/approve",
    methods=["POST"]
)
def approve_account_request(request_id):

    if not session.get("admin_logged_in"):

        return redirect(
            "/admin/login"
        )

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        query = """
            SELECT
                ar.request_id,
                ar.user_id,
                ar.status,
                u.first_name,
                u.email
            FROM ACCOUNT_REQUEST ar
            INNER JOIN `USER` u
                ON ar.user_id = u.user_id
            WHERE request_id = %s
        """

        cursor.execute(
            query,
            (request_id,)
        )

        account_request = cursor.fetchone()

        if account_request is None:

            return "Account request not found."

        if account_request["status"] != "PENDING":

            return "This account request has already been processed."

        user_id = account_request["user_id"]

        # Check account
        query = """
            SELECT account_id
            FROM ACCOUNT
            WHERE user_id = %s
            LIMIT 1
        """

        cursor.execute(
            query,
            (user_id,)
        )

        existing_account = cursor.fetchone()

        if existing_account:

            return "Customer already has an account."

        # Generate unique account number
        while True:

            account_number = str(
                random.randint(
                    100000000000,
                    999999999999
                )
            )

            query = """
                SELECT account_id
                FROM ACCOUNT
                WHERE account_number = %s
            """

            cursor.execute(
                query,
                (account_number,)
            )

            if cursor.fetchone() is None:

                break

        # Create account
        insert_account = """
            INSERT INTO ACCOUNT
            (
                account_number,
                user_id,
                created_at,
                status,
                is_frozen
            )
            VALUES
            (
                %s,
                %s,
                CURRENT_TIMESTAMP,
                'ACTIVE',
                FALSE
            )
        """

        cursor.execute(
            insert_account,
            (
                account_number,
                user_id
            )
        )

        # Approve request
        update_request = """
            UPDATE ACCOUNT_REQUEST
            SET
                status = 'APPROVED',
                approved_at = CURRENT_TIMESTAMP
            WHERE request_id = %s
        """

        cursor.execute(
            update_request,
            (request_id,)
        )

        connection.commit()

        # ========================================================
        # SEND ACCOUNT APPROVAL EMAIL
        # ========================================================
        send_notification_email(
            account_request["email"],
            "Core Banking - Account Request Approved",
            f"""
Dear {account_request["first_name"]},

Good news! Your bank account request has been APPROVED.

Account Number: {account_number}
Account Status: ACTIVE

You can now log in and use the available banking services.

Regards,
Core Banking System
"""
        )

        return redirect(
            "/admin/requests"
        )

    except Exception as e:

        connection.rollback()

        return f"Account approval failed: {e}"

    finally:

        cursor.close()
        connection.close()


# ============================================================
# ADMIN REJECT ACCOUNT REQUEST
# ============================================================

@app.route(
    "/admin/account-request/<int:request_id>/reject",
    methods=["POST"]
)
def reject_account_request(request_id):

    if not session.get("admin_logged_in"):

        return redirect(
            "/admin/login"
        )

    connection = get_db_connection()

    cursor = connection.cursor(
        dictionary=True
    )

    try:

        query = """
            SELECT
                ar.request_id,
                ar.user_id,
                ar.status,
                u.first_name,
                u.email
            FROM ACCOUNT_REQUEST ar
            INNER JOIN `USER` u
                ON ar.user_id = u.user_id
            WHERE request_id = %s
        """

        cursor.execute(
            query,
            (request_id,)
        )

        account_request = cursor.fetchone()

        if account_request is None:

            return "Account request not found."

        if account_request["status"] != "PENDING":

            return "This account request has already been processed."

        update_query = """
            UPDATE ACCOUNT_REQUEST
            SET
                status = 'REJECTED',
                approved_at = NULL
            WHERE request_id = %s
        """

        cursor.execute(
            update_query,
            (request_id,)
        )

        connection.commit()

        # ========================================================
        # SEND ACCOUNT REJECTION EMAIL
        # ========================================================
        send_notification_email(
            account_request["email"],
            "Core Banking - Account Request Rejected",
            f"""
Dear {account_request["first_name"]},

Your bank account request has been REJECTED after review.

Please contact the bank administrator for more information.
You may submit a new request if permitted by the bank.

Regards,
Core Banking System
"""
        )

        return redirect(
            "/admin/requests"
        )

    except Exception as e:

        connection.rollback()

        return f"Account rejection failed: {e}"

    finally:

        cursor.close()
        connection.close()

# ============================================================
# ADMIN REPORTS
# ============================================================

@app.route("/admin/reports")
def admin_reports():

    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        # --------------------------------------------------------
        # TOTAL CUSTOMERS
        # --------------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS total_customers
            FROM `USER`
        """)

        total_customers = cursor.fetchone()["total_customers"]


        # --------------------------------------------------------
        # TOTAL ACCOUNTS
        # --------------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS total_accounts
            FROM ACCOUNT
        """)

        total_accounts = cursor.fetchone()["total_accounts"]


        # --------------------------------------------------------
        # TOTAL DEPOSITS
        # --------------------------------------------------------

        cursor.execute("""
            SELECT
                COALESCE(SUM(amount), 0) AS total_deposits
            FROM `TRANSACTION`
            WHERE transaction_type = 'DEPOSIT'
              AND status = 'SUCCESS'
        """)

        total_deposits = cursor.fetchone()["total_deposits"]


        # --------------------------------------------------------
        # TOTAL WITHDRAWALS
        # --------------------------------------------------------

        cursor.execute("""
            SELECT
                COALESCE(SUM(amount), 0) AS total_withdrawals
            FROM `TRANSACTION`
            WHERE transaction_type = 'WITHDRAW'
              AND status = 'SUCCESS'
        """)

        total_withdrawals = cursor.fetchone()["total_withdrawals"]


        # --------------------------------------------------------
        # TOTAL TRANSACTIONS
        # --------------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS total_transactions
            FROM `TRANSACTION`
            WHERE status = 'SUCCESS'
        """)

        total_transactions = cursor.fetchone()["total_transactions"]


        # --------------------------------------------------------
        # TODAY'S TRANSACTIONS
        # --------------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS today_transactions
            FROM `TRANSACTION`
            WHERE DATE(transaction_date) = CURDATE()
              AND status = 'SUCCESS'
        """)

        today_transactions = cursor.fetchone()["today_transactions"]


        # --------------------------------------------------------
        # PENDING ACCOUNT REQUESTS
        # --------------------------------------------------------

        cursor.execute("""
            SELECT COUNT(*) AS pending_requests
            FROM ACCOUNT_REQUEST
            WHERE status = 'PENDING'
        """)

        pending_requests = cursor.fetchone()["pending_requests"]


        # --------------------------------------------------------
        # RECENT TRANSACTIONS
        # --------------------------------------------------------

        cursor.execute("""
            SELECT
                t.transaction_id,
                t.reference_num,
                t.transaction_type,
                t.amount,
                t.transaction_date,
                t.status,
                a.account_number,
                u.first_name,
                u.last_name
            FROM `TRANSACTION` t

            INNER JOIN ACCOUNT a
                ON t.account_id = a.account_id

            INNER JOIN `USER` u
                ON a.user_id = u.user_id

            ORDER BY t.transaction_date DESC

            LIMIT 20
        """)

        recent_transactions = cursor.fetchall()


        # --------------------------------------------------------
        # RENDER REPORTS PAGE
        # --------------------------------------------------------

        return render_template(
            "admin/reports.html",

            admin_name=session.get("admin_name"),

            total_customers=total_customers,

            total_accounts=total_accounts,

            total_deposits=total_deposits,

            total_withdrawals=total_withdrawals,

            total_transactions=total_transactions,

            today_transactions=today_transactions,

            pending_requests=pending_requests,

            recent_transactions=recent_transactions
        )


    except Exception as e:

        return f"Reports loading failed: {e}"


    finally:

        cursor.close()
        connection.close()

# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.route("/admin/logout")
def admin_logout():

    session.clear()

    return redirect("/")


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )