"""
AbiCare - Accounts Views
=========================
Handles:
- Login / Logout  (all roles)
- Forced password change on first login
- Profile update
- Patient portal account creation by staff
- Staff account creation by admin
- Password reset with admin approval
- Admin: reset patient password (no old password needed)
"""

import secrets
import string
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import (authenticate, login, logout,
                                  update_session_auth_hash)
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import User, PasswordResetRequest
from apps.audit_logs.utils import log_action


# ─────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────

def _generate_temp_password(length=10):
    """
    Generate a random temporary password.
    Always includes at least one uppercase, one digit, one special char
    so it passes Django's password validators.
    Example output: Kx7#mPqR2!
    """
    upper   = string.ascii_uppercase
    lower   = string.ascii_lowercase
    digits  = string.digits
    special = '!@#$%^&*'
    # Guarantee one of each required type
    pwd = [
        secrets.choice(upper),
        secrets.choice(lower),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    # Fill the rest randomly from all chars
    all_chars = upper + lower + digits + special
    pwd += [secrets.choice(all_chars) for _ in range(length - 4)]
    # Shuffle so the guaranteed chars are not always at the start
    secrets.SystemRandom().shuffle(pwd)
    return ''.join(pwd)


def _redirect_after_login(user):
    """Each role goes to their own portal on login."""
    role_map = {
        'patient':      '/portal/',
        'doctor':       '/doctor-portal/',
        'nurse':        '/nurse-portal/',
        'lab_tech':     '/lab-portal/',
        'receptionist': '/reception-portal/',
        'admin':        '/dashboard/',
    }
    if user.is_superuser:
        return '/dashboard/'
    return role_map.get(user.role, '/dashboard/')


# ─────────────────────────────────────────────────────────────────────
# LOGIN / LOGOUT
# ─────────────────────────────────────────────────────────────────────

@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        if request.user.must_change_password:
            return redirect('accounts:force_change_password')
        return redirect(_redirect_after_login(request.user))

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # Allow patients to log in with hospital number OR username
        user = authenticate(request, username=username, password=password)

        # If not found by username, try hospital number for patients
        if user is None:
            try:
                from apps.patients.models import Patient
                patient = Patient.objects.get(
                    hospital_number__iexact=username,
                    is_active=True
                )
                if patient.user_account:
                    user = authenticate(
                        request,
                        username=patient.user_account.username,
                        password=password
                    )
            except Exception:
                pass

        if user is not None:
            if user.is_active:
                login(request, user)
                log_action(user, 'LOGIN', request, f"Logged in: {user.username}")

                # ── Forced password change ────────────────────────────
                if user.must_change_password:
                    messages.warning(request,
                        "Welcome! You must change your temporary password before continuing.")
                    return redirect('accounts:force_change_password')

                messages.success(request,
                    f"Welcome back, {user.first_name or user.username}!")
                next_url = request.GET.get('next') or _redirect_after_login(user)
                return redirect(next_url)
            else:
                messages.error(request, "Your account has been deactivated. Contact admin.")
                log_action(None, 'LOGIN_FAIL', request,
                           f"Deactivated login attempt: {username}")
        else:
            messages.error(request, "Invalid username or password.")
            log_action(None, 'LOGIN_FAIL', request, f"Failed login: {username}")

    return render(request, 'accounts/login.html', {'page_title': 'Login'})


@login_required
def logout_view(request):
    log_action(request.user, 'LOGOUT', request,
               f"Logged out: {request.user.username}")
    logout(request)
    messages.info(request, "You have been logged out safely.")
    return redirect('accounts:login')


# ─────────────────────────────────────────────────────────────────────
# FORCED PASSWORD CHANGE (first login)
# ─────────────────────────────────────────────────────────────────────

@login_required
def force_change_password_view(request):
    """
    Shown immediately after login if must_change_password=True.
    The user CANNOT navigate away until they change their password.
    """
    # If already changed, redirect appropriately
    if not request.user.must_change_password:
        return redirect(_redirect_after_login(request.user))

    if request.method == 'POST':
        new_password1 = request.POST.get('new_password1', '')
        new_password2 = request.POST.get('new_password2', '')

        if len(new_password1) < 8:
            messages.error(request, "Password must be at least 8 characters.")
        elif new_password1 != new_password2:
            messages.error(request, "Passwords do not match.")
        elif new_password1.lower() in ['password', '12345678', 'abicare123']:
            messages.error(request, "That password is too common. Please choose something unique.")
        else:
            user = request.user
            user.set_password(new_password1)
            user.must_change_password = False
            user.save()
            # Keep the user logged in after password change
            update_session_auth_hash(request, user)
            log_action(user, 'UPDATE', request,
                       f"Changed temporary password on first login: {user.username}")
            messages.success(request,
                "Password changed successfully. Welcome to AbiCare!")
            return redirect(_redirect_after_login(user))

    return render(request, 'accounts/force_change_password.html', {
        'page_title': 'Set Your Password',
    })


# ─────────────────────────────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────────────────────────────

@login_required
def profile_view(request):
    user = request.user

    # Block access if password change is forced
    if user.must_change_password:
        return redirect('accounts:force_change_password')

    if request.method == 'POST':
        user.first_name   = request.POST.get('first_name',   user.first_name).strip()
        user.last_name    = request.POST.get('last_name',    user.last_name).strip()
        user.email        = request.POST.get('email',        user.email).strip()
        user.phone_number = request.POST.get('phone_number', user.phone_number).strip()
        if 'profile_picture' in request.FILES:
            user.profile_picture = request.FILES['profile_picture']
        user.save()
        log_action(user, 'UPDATE', request, "Updated profile")
        messages.success(request, "Profile updated successfully.")
        return redirect('accounts:profile')

    return render(request, 'accounts/profile.html', {
        'page_title':   'My Profile',
        'profile_user': user,
    })


# ─────────────────────────────────────────────────────────────────────
# PATIENT PORTAL ACCOUNT CREATION (by staff)
# ─────────────────────────────────────────────────────────────────────

@login_required
def create_patient_account_view(request, hospital_number):
    """
    Staff creates a portal login for a patient.
    - Username = patient's hospital number (e.g. ABI-2024-00001)
    - Temporary password is set by staff
    - must_change_password = True so patient must change it on first login
    - Staff can optionally email the credentials to the patient
    - Staff can optionally print a credentials slip
    """
    from apps.patients.models import Patient
    patient = get_object_or_404(Patient, hospital_number=hospital_number)

    if patient.user_account:
        messages.warning(request,
            f"{patient.full_name} already has a portal account "
            f"(username: {patient.user_account.username}).")
        return redirect('patient_detail:detail', hospital_number=hospital_number)

    # Auto-generate a temporary password to pre-fill the form
    suggested_password = _generate_temp_password()

    if request.method == 'POST':
        temp_password = request.POST.get('password1', '').strip()
        send_email    = 'send_email' in request.POST
        print_slip    = 'print_slip' in request.POST

        if len(temp_password) < 8:
            messages.error(request, "Temporary password must be at least 8 characters.")
            return render(request, 'accounts/create_patient_account.html', {
                'patient': patient,
                'suggested_password': temp_password,
            })

        # Username = hospital number (patients always use this to log in)
        username = patient.hospital_number

        if User.objects.filter(username=username).exists():
            messages.error(request,
                f"A user account with username '{username}' already exists.")
            return redirect('patient_detail:detail', hospital_number=hospital_number)

        # Create the portal account
        portal_user = User.objects.create_user(
            username=username,
            password=temp_password,
            first_name=patient.first_name,
            last_name=patient.last_name,
            email=patient.email or '',
            role=User.PATIENT,
            must_change_password=True,   # FORCE change on first login
        )

        # Link to patient record
        patient.user_account = portal_user
        patient.save()

        # Send email if requested and patient has email
        if send_email and patient.email:
            try:
                send_mail(
                    subject=f"Your {settings.HOSPITAL_NAME} Patient Portal Login",
                    message=(
                        f"Dear {patient.full_name},\n\n"
                        f"Your patient portal account has been created at "
                        f"{settings.HOSPITAL_NAME}.\n\n"
                        f"LOGIN DETAILS\n"
                        f"Portal URL:  {request.build_absolute_uri('/portal/')}\n"
                        f"Username:    {username}\n"
                        f"Password:    {temp_password}\n\n"
                        f"IMPORTANT: You will be asked to change this password "
                        f"the first time you log in.\n\n"
                        f"If you did not request this account, please contact us "
                        f"immediately at {settings.HOSPITAL_PHONE}.\n\n"
                        f"— {settings.HOSPITAL_NAME}"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[patient.email],
                    fail_silently=True,
                )
                messages.success(request,
                    f"Portal account created and login details emailed to {patient.email}.")
            except Exception:
                messages.warning(request,
                    "Portal account created but email failed to send. "
                    "Please give login details to the patient manually.")
        else:
            messages.success(request,
                f"Portal account created for {patient.full_name}.")

        log_action(request.user, 'CREATE', request,
                   f"Created portal account for patient {hospital_number}")

        # Redirect to print slip if requested
        if print_slip:
            return redirect('accounts:print_patient_credentials',
                            hospital_number=hospital_number)

        return redirect('patient_detail:detail', hospital_number=hospital_number)

    return render(request, 'accounts/create_patient_account.html', {
        'page_title':         f"Create Portal Login — {patient.full_name}",
        'patient':            patient,
        'suggested_password': suggested_password,
    })


@login_required
def print_patient_credentials_view(request, hospital_number):
    """
    Printable slip showing the patient's username and temporary password.
    Staff hands this to the patient at the front desk.
    NOTE: We only show the temp password at print time — after this it
    is hashed in the database and staff cannot see it.
    """
    from apps.patients.models import Patient
    patient = get_object_or_404(Patient, hospital_number=hospital_number)

    if not patient.user_account:
        messages.error(request, "This patient does not have a portal account yet.")
        return redirect('patient_detail:detail', hospital_number=hospital_number)

    return render(request, 'accounts/print_credentials.html', {
        'patient':     patient,
        'username':    patient.hospital_number,
        'portal_url':  request.build_absolute_uri('/portal/'),
        'hospital':    settings.HOSPITAL_NAME,
        'hospital_phone': settings.HOSPITAL_PHONE,
        # We do NOT pass the password here — it was already hashed.
        # Staff must note it from the creation form. This slip only
        # shows the username and instructions.
    })


# ─────────────────────────────────────────────────────────────────────
# ADMIN: RESET PATIENT PASSWORD (without knowing old password)
# ─────────────────────────────────────────────────────────────────────

@login_required
def admin_reset_patient_password_view(request, hospital_number):
    """
    Admin or receptionist resets a patient's portal password.
    Generates a new temp password. Staff CANNOT see the current password.
    Sets must_change_password=True again so patient changes it on next login.
    """
    from apps.patients.models import Patient

    if not (request.user.is_admin_staff or request.user.is_receptionist):
        messages.error(request, "Permission denied.")
        return redirect('patients:dashboard')

    patient = get_object_or_404(Patient, hospital_number=hospital_number)

    if not patient.user_account:
        messages.error(request, "This patient does not have a portal account.")
        return redirect('patient_detail:detail', hospital_number=hospital_number)

    if request.method == 'POST':
        # Require staff to enter THEIR OWN password to confirm this action
        staff_password = request.POST.get('staff_password', '')
        confirmed = authenticate(
            request,
            username=request.user.username,
            password=staff_password
        )
        if confirmed is None:
            messages.error(request,
                "Your password was incorrect. Reset cancelled.")
            return redirect('patient_detail:detail', hospital_number=hospital_number)

        # Generate new temporary password
        new_temp = _generate_temp_password()

        portal_user = patient.user_account
        portal_user.set_password(new_temp)
        portal_user.must_change_password = True   # force change on next login
        portal_user.save()

        log_action(request.user, 'UPDATE', request,
                   f"Reset portal password for patient {hospital_number}")

        # Show the new temp password ONCE so staff can hand it to the patient
        messages.success(request,
            f"Password reset. New temporary password: {new_temp} — "
            f"Note this down and give it to the patient. "
            f"It will not be shown again.")

        return redirect('patient_detail:detail', hospital_number=hospital_number)

    return render(request, 'accounts/reset_patient_password.html', {
        'page_title': f"Reset Password — {patient.full_name}",
        'patient':    patient,
    })


# ─────────────────────────────────────────────────────────────────────
# STAFF ACCOUNT CREATION (by admin)
# ─────────────────────────────────────────────────────────────────────

@login_required
def create_staff_account_view(request):
    """
    Admin creates a new staff account (doctor, nurse, lab tech, receptionist).
    Sets a temporary password. Staff must change it on first login.
    """
    if not request.user.is_admin_staff:
        messages.error(request, "Only admins can create staff accounts.")
        return redirect('patients:dashboard')

    suggested_password = _generate_temp_password()

    if request.method == 'POST':
        first_name    = request.POST.get('first_name', '').strip()
        last_name     = request.POST.get('last_name',  '').strip()
        username      = request.POST.get('username',   '').strip()
        email         = request.POST.get('email',      '').strip()
        role          = request.POST.get('role',       '')
        department    = request.POST.get('department', '').strip()
        phone         = request.POST.get('phone_number','').strip()
        temp_password = request.POST.get('temp_password','').strip()
        send_email    = 'send_email' in request.POST

        # Validate
        errors = []
        if not first_name: errors.append("First name is required.")
        if not last_name:  errors.append("Last name is required.")
        if not username:   errors.append("Username is required.")
        if not role:       errors.append("Role is required.")
        if len(temp_password) < 8:
            errors.append("Temporary password must be at least 8 characters.")
        if User.objects.filter(username=username).exists():
            errors.append(f"Username '{username}' is already taken.")
        if email and User.objects.filter(email=email).exists():
            errors.append(f"Email '{email}' is already registered.")

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'accounts/create_staff_account.html', {
                'page_title':         'Create Staff Account',
                'suggested_password': temp_password or suggested_password,
                'role_choices':       _staff_role_choices(),
                'form_data':          request.POST,
            })

        # Create account
        staff_user = User.objects.create_user(
            username=username,
            password=temp_password,
            first_name=first_name,
            last_name=last_name,
            email=email,
            role=role,
            department=department,
            phone_number=phone,
            must_change_password=True,   # must change on first login
        )

        # Send welcome email if requested
        if send_email and email:
            try:
                send_mail(
                    subject=f"Your {settings.HOSPITAL_NAME} Staff Account",
                    message=(
                        f"Dear {first_name} {last_name},\n\n"
                        f"Your staff account at {settings.HOSPITAL_NAME} "
                        f"has been created.\n\n"
                        f"LOGIN DETAILS\n"
                        f"System URL:  {request.build_absolute_uri('/accounts/login/')}\n"
                        f"Username:    {username}\n"
                        f"Password:    {temp_password}\n"
                        f"Role:        {staff_user.get_role_display()}\n\n"
                        f"IMPORTANT: You must change this password on your first login.\n\n"
                        f"— {settings.HOSPITAL_NAME} Administration"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=True,
                )
            except Exception:
                pass

        log_action(request.user, 'CREATE', request,
                   f"Created staff account: {username} ({role})")
        messages.success(request,
            f"Staff account created for {first_name} {last_name}. "
            f"Username: {username}. "
            f"They must change their password on first login.")
        return redirect('accounts:staff_list')

    return render(request, 'accounts/create_staff_account.html', {
        'page_title':         'Create Staff Account',
        'suggested_password': suggested_password,
        'role_choices':       _staff_role_choices(),
        'form_data':          {},
    })


@login_required
def staff_list_view(request):
    """Admin view — list all staff accounts with their roles and status."""
    if not request.user.is_admin_staff:
        messages.error(request, "Only admins can view staff accounts.")
        return redirect('patients:dashboard')

    staff = User.objects.exclude(role=User.PATIENT).order_by('role', 'last_name')
    return render(request, 'accounts/staff_list.html', {
        'page_title': 'Staff Accounts',
        'staff':      staff,
    })


@login_required
def admin_reset_staff_password_view(request, pk):
    """
    Admin resets a staff member's password.
    Generates a new temp password. Sets must_change_password=True.
    """
    if not request.user.is_admin_staff:
        messages.error(request, "Permission denied.")
        return redirect('patients:dashboard')

    staff_user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        staff_password = request.POST.get('staff_password', '')
        confirmed = authenticate(
            request,
            username=request.user.username,
            password=staff_password
        )
        if confirmed is None:
            messages.error(request, "Your password was incorrect. Reset cancelled.")
            return redirect('accounts:staff_list')

        new_temp = _generate_temp_password()
        staff_user.set_password(new_temp)
        staff_user.must_change_password = True
        staff_user.save()

        # Email new temp password if staff has email
        if staff_user.email:
            try:
                send_mail(
                    subject=f"Your {settings.HOSPITAL_NAME} Password Has Been Reset",
                    message=(
                        f"Dear {staff_user.first_name},\n\n"
                        f"Your password has been reset by an administrator.\n\n"
                        f"New temporary password: {new_temp}\n\n"
                        f"You will be asked to change this on your next login.\n\n"
                        f"— {settings.HOSPITAL_NAME}"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[staff_user.email],
                    fail_silently=True,
                )
            except Exception:
                pass

        log_action(request.user, 'UPDATE', request,
                   f"Reset password for staff: {staff_user.username}")
        messages.success(request,
            f"Password reset for {staff_user.full_name}. "
            f"New temp password: {new_temp} — "
            f"Give this to the staff member or it was emailed to them.")
        return redirect('accounts:staff_list')

    return render(request, 'accounts/reset_staff_password.html', {
        'page_title': f"Reset Password — {staff_user.full_name}",
        'staff_user': staff_user,
    })


def _staff_role_choices():
    """Return role choices excluding PATIENT (staff only)."""
    return [
        (User.DOCTOR,       'Doctor'),
        (User.NURSE,        'Nurse'),
        (User.LAB_TECH,     'Laboratory Technician'),
        (User.RECEPTIONIST, 'Receptionist'),
        (User.ADMIN,        'Administrator'),
    ]


# ─────────────────────────────────────────────────────────────────────
# PASSWORD RESET (self-service with admin approval)
# ─────────────────────────────────────────────────────────────────────

def request_password_reset_view(request):
    """Step 1 — User requests a reset. No email sent until admin approves."""
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        user = None

        # Search by username, hospital number, or email
        try:
            user = User.objects.get(username=identifier, is_active=True)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email=identifier, is_active=True)
            except User.DoesNotExist:
                # Try hospital number for patients
                try:
                    from apps.patients.models import Patient
                    patient = Patient.objects.get(
                        hospital_number__iexact=identifier, is_active=True)
                    user = patient.user_account
                except Exception:
                    pass

        if user:
            recent = PasswordResetRequest.objects.filter(
                user=user,
                status='pending',
                requested_at__gte=timezone.now() - timedelta(hours=1)
            ).exists()
            if not recent:
                x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
                ip = (x_forwarded.split(',')[0]
                      if x_forwarded else request.META.get('REMOTE_ADDR'))
                PasswordResetRequest.objects.create(user=user, ip_address=ip)
                # Notify admins
                _notify_admins_of_reset_request(user)
                log_action(None, 'VIEW', request,
                           f"Password reset requested for: {user.username}")

        # Always same message — never reveal if account exists
        messages.success(request,
            "If an account was found, your request has been sent to the "
            "administrator. You will receive an email once approved.")
        return redirect('accounts:login')

    return render(request, 'accounts/request_reset.html', {
        'page_title': 'Forgot Password',
    })


def _notify_admins_of_reset_request(user):
    """Notify all admin users of a pending password reset request."""
    try:
        from apps.notifications.utils import send_notification
        admins = User.objects.filter(role=User.ADMIN, is_active=True)
        for admin in admins:
            send_notification(
                user=admin,
                notif_type='general',
                title=f"Password Reset Request — {user.get_full_name() or user.username}",
                message=(
                    f"{user.get_full_name() or user.username} has requested a "
                    f"password reset. Please review in Admin → Reset Requests."
                ),
                link='/accounts/admin/reset-requests/',
            )
    except Exception:
        pass


@login_required
def reset_requests_admin_view(request):
    """Admin sees all pending reset requests and approves or denies them."""
    if not request.user.is_admin_staff:
        messages.error(request, "Admins only.")
        return redirect('patients:dashboard')

    pending = PasswordResetRequest.objects.filter(
        status='pending').select_related('user')
    history = PasswordResetRequest.objects.exclude(
        status='pending').select_related('user', 'reviewed_by')[:30]

    return render(request, 'accounts/reset_requests.html', {
        'page_title': 'Password Reset Requests',
        'pending':    pending,
        'history':    history,
    })


@login_required
def review_reset_request_view(request, pk):
    if not request.user.is_admin_staff:
        messages.error(request, "Admins only.")
        return redirect('patients:dashboard')

    reset_req = get_object_or_404(PasswordResetRequest, pk=pk, status='pending')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            reset_req.status      = 'approved'
            reset_req.reviewed_by = request.user
            reset_req.reviewed_at = timezone.now()
            reset_req.expires_at  = timezone.now() + timedelta(hours=2)
            reset_req.save()
            _send_reset_email(request, reset_req)
            log_action(request.user, 'APPROVE', request,
                       f"Approved reset for {reset_req.user.username}")
            messages.success(request,
                f"Approved. Reset link emailed to {reset_req.user.email}.")
        elif action == 'deny':
            reset_req.status      = 'denied'
            reset_req.reviewed_by = request.user
            reset_req.reviewed_at = timezone.now()
            reset_req.save()
            log_action(request.user, 'DELETE', request,
                       f"Denied reset for {reset_req.user.username}")
            messages.info(request, "Request denied.")

    return redirect('accounts:reset_requests')


def _send_reset_email(request, reset_req):
    reset_url = request.build_absolute_uri(
        f'/accounts/reset/{reset_req.token}/')
    user = reset_req.user
    if not user.email:
        return
    try:
        send_mail(
            subject=f"[{settings.HOSPITAL_NAME}] Password Reset Approved",
            message=(
                f"Dear {user.get_full_name() or user.username},\n\n"
                f"Your password reset request has been approved.\n\n"
                f"Click the link below to set a new password "
                f"(expires in 2 hours):\n{reset_url}\n\n"
                f"If you did not request this, contact us immediately.\n\n"
                f"— {settings.HOSPITAL_NAME}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception:
        pass


def do_password_reset_view(request, token):
    reset_req = get_object_or_404(PasswordResetRequest, token=token)
    if not reset_req.is_valid:
        messages.error(request, "This reset link has expired or already been used.")
        return redirect('accounts:login')

    if request.method == 'POST':
        p1 = request.POST.get('password1', '')
        p2 = request.POST.get('password2', '')
        if len(p1) < 8:
            messages.error(request, "Password must be at least 8 characters.")
        elif p1 != p2:
            messages.error(request, "Passwords do not match.")
        else:
            user = reset_req.user
            user.set_password(p1)
            user.must_change_password = False
            user.save()
            reset_req.status = 'used'
            reset_req.save()
            log_action(user, 'UPDATE', request, "Password reset via approved link")
            messages.success(request, "Password updated. You can now log in.")
            return redirect('accounts:login')

    return render(request, 'accounts/do_reset.html', {
        'page_title': 'Set New Password',
        'token':      token,
        'user':       reset_req.user,
    })