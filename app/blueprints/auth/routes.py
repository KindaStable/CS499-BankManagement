import os
import pandas as pd
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, current_app
)
from app.blueprints.auth.forms import (
    LoginForm, 
    RegistrationStep1Form, 
    RegistrationStep2Form, 
    RegistrationStep3Form, 
    DepositForm
)
from scripts.customer import webLogin, openAcc

# Create the Flask blueprint for authentication-related routes.
auth_bp = Blueprint('auth', __name__, template_folder='templates')

# Constants for distinguishing between login types.
NEW_ACCOUNT = 1
LOGIN = 2

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def get_customer_csv_path():
    return os.path.join(current_app.root_path, '..', 'csvFiles', 'customers.csv')

def process_login(form, session_key, login_type):
    if session_key in session:
        flash("Already Logged In")
        return url_for(f'accounts.{session_key}_dashboard'), None

    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        if session_key == "user":
            custPath = get_customer_csv_path()
            try:
                userInfo = pd.read_csv(custPath)
                if 'Username' not in userInfo or 'CustomerID' not in userInfo:
                    raise ValueError("Malformed customer CSV.")
                customerID = userInfo.loc[userInfo['Username'] == username, 'CustomerID'].iloc[0]
            except (IndexError, ValueError) as e:
                flash("User not found or data error", "danger")
                return None, str(e)

        user_type = "Customer" if session_key == "user" else "Employee"
        login_result = webLogin.login_page_button_pressed(login_type, user_type, username, password)
        if not login_result or login_result.get("status") == "error":
            error_message = login_result.get("message", "Login failed") if login_result else "Login function returned None"
            flash(error_message, "danger")
            return None, error_message

        session[session_key] = username
        if session_key == "user":
            session["customerID"] = int(customerID)

        flash("Login Successful!", "success")
        return url_for(f'accounts.{session_key}_dashboard'), None

    return None, None

# -----------------------------------------------------------------------------
# Authentication Routes
# -----------------------------------------------------------------------------
@auth_bp.route('/customer/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    redirect_url, error = process_login(form, "user", LOGIN)
    if redirect_url:
        return redirect(redirect_url)
    return render_template('auth/login.html', form=form)

@auth_bp.route('/teller/login', methods=['GET', 'POST'])
def teller_login():
    form = LoginForm()
    redirect_url, error = process_login(form, "teller", LOGIN)
    if redirect_url:
        return redirect(redirect_url)
    return render_template('auth/teller_login.html', form=form)

@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    form = LoginForm()
    redirect_url, error = process_login(form, "admin", LOGIN)
    if redirect_url:
        return redirect(redirect_url)
    return render_template('auth/admin_login.html', form=form)

# -----------------------------------------------------------------------------
# Customer Registration Routes
# -----------------------------------------------------------------------------
@auth_bp.route('/customer/register/step1', methods=['GET', 'POST'])
def register_step1():
    form = RegistrationStep1Form()
    if form.validate_on_submit():
        session['step1'] = {
            'first_name': form.first_name.data,
            'last_name': form.last_name.data,
            'address': form.address.data,
            'phone_number': form.phone_number.data,
            'tax_id': form.tax_id.data,
            'birthday': form.birthday.data,
        }
        return redirect(url_for('auth.register_step2'))
    return render_template('auth/register_step1.html', form=form)

@auth_bp.route('/customer/register/step2', methods=['GET', 'POST'])
def register_step2():
    form = RegistrationStep2Form()
    if form.validate_on_submit():
        session['step2'] = {
            'username': form.username.data,
            'password': form.password.data,
            'email': form.email.data,
            'security_question_1': form.security_question_1.data,
            'security_answer_1': form.security_answer_1.data.lower(),
            'security_question_2': form.security_question_2.data,
            'security_answer_2': form.security_answer_2.data.lower(),
        }
        return redirect(url_for('auth.register_step3'))
    return render_template('auth/register_step2.html', form=form)

@auth_bp.route('/customer/register/step3', methods=['GET', 'POST'])
def register_step3():
    form = RegistrationStep3Form()

    if form.validate_on_submit():
        step1_data = session.get('step1')
        step2_data = session.get('step2')

        if not step1_data or not step2_data:
            flash("Your session has expired. Please complete the registration again.", "danger")
            return redirect(url_for('auth.register_step1'))

        session['account_type'] = form.account_type.data
        return redirect(url_for('auth.finalize_registration'))

    return render_template('auth/register_step3.html', form=form)

@auth_bp.route('/customer/register/finalize', methods=['GET', 'POST'])
def finalize_registration():
    step1_data = session.get('step1')
    step2_data = session.get('step2')
    account_type = session.get('account_type')

    if not step1_data or not step2_data or not account_type:
        flash("Your session has expired. Please complete the registration again.", "danger")
        return redirect(url_for('auth.register_step1'))

    user_data = {**step1_data, **step2_data, 'account_type': account_type}
    form = DepositForm()

    if form.validate_on_submit():
        deposit_amount = form.deposit_amount.data

        try:
            login_result = webLogin.login_page_button_pressed(
            NEW_ACCOUNT,
            "Customer",
            user_data['username'],
            user_data['password'],
            user_data['first_name'], 
            user_data['last_name'],  
            user_data['address'],
            user_data['email'],
            user_data['phone_number'],
            user_data['tax_id'], 
            user_data['security_answer_1'],
            user_data['security_answer_2'],
        )

            if login_result.get("status") == "error":
                flash(login_result.get("message", "Registration failed"), "danger")
                return redirect(url_for('auth.register_step1'))

            custPath = get_customer_csv_path()
            userInfo = pd.read_csv(custPath)
            if 'Username' not in userInfo.columns:
                raise ValueError(f"Expected column 'Username' in CSV but got: {list(userInfo.columns)}")
            
            customer_row = userInfo[userInfo['Username'].str.lower() == user_data['username'].lower()]
            if customer_row.empty:
                raise IndexError("Username not found in CSV.")

            customerID = int(customer_row['CustomerID'].iloc[0])
            session["customerID"] = customerID

            newAccount = openAcc.open_account(
                customerID,
                user_data['account_type'],
                deposit_amount
            )

            session['registration_finalized'] = True
            session.pop('step1', None)
            session.pop('step2', None)
            session.pop('account_type', None)

            return redirect(url_for('accounts.user_dashboard'))

        except Exception as e:
            flash(f"Registration failed: {str(e)}", "danger")
            return render_template('auth/register_step4.html', account_type=account_type, form=form)

    if session.get("registration_finalized"):
        flash("Account already created. Please log in.", "info")
        return redirect(url_for("auth.login"))

    return render_template('auth/register_step4.html', account_type=account_type, form=form)