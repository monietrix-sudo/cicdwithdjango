"""
AbiCare - Patient Portal Views
================================
Patients log in and see ONLY their own data.
Every view here has strict object-level checks.
No patient can access another patient's data — ever.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone

from apps.audit_logs.utils import log_action


def _get_patient_or_deny(request):
    """
    Helper — gets the Patient record linked to the logged-in patient user.
    If the user is not a patient OR has no linked patient record,
    they are denied. Returns (patient, None) or (None, redirect_response).
    """
    if not request.user.is_patient_user:
        messages.error(request, "Access denied.")
        return None, redirect('patients:dashboard')

    if request.user.must_change_password:
        return None, redirect('accounts:force_change_password')

    if not hasattr(request.user, 'patient_profile'):
        messages.error(request,
            "No patient record is linked to your account. "
            "Please contact reception.")
        return None, redirect('accounts:login')

    patient = request.user.patient_profile
    if not patient.is_active:
        messages.error(request, "Your patient record is inactive. Contact the hospital.")
        return None, redirect('accounts:login')

    return patient, None


@login_required
def portal_dashboard_view(request):
    """
    Patient's home page — shows a summary of all their data in one place.
    """
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    from apps.lab_results.models import LabResult
    from apps.medications.models import MedicationSchedule, MedicationDose
    from apps.appointments.models import Appointment
    from apps.records.models import MedicalRecord

    today = timezone.now().date()
    now   = timezone.now()

    # Released lab results (visible to patient)
    lab_results = LabResult.objects.filter(
        patient=patient, status='released'
    ).order_by('-ordered_at')[:5]

    # Active medications
    active_meds = MedicationSchedule.objects.filter(
        patient=patient,
        is_active=True,
        end_date__gte=today,
    ).order_by('drug_name')

    # Overdue doses today
    overdue_doses = MedicationDose.objects.filter(
        schedule__patient=patient,
        schedule__is_active=True,
        scheduled_datetime__date=today,
        scheduled_datetime__lte=now,
        taken=False,
    ).count()

    # Upcoming appointments
    upcoming_appointments = Appointment.objects.filter(
        patient=patient,
        appointment_date__gte=today,
        status__in=['scheduled', 'confirmed'],
    ).order_by('appointment_date', 'appointment_time')[:3]

    # Visible medical records
    recent_records = MedicalRecord.objects.filter(
        patient=patient,
        is_deleted=False,
        is_visible_to_patient=True,
    ).order_by('-uploaded_at')[:5]

    log_action(request.user, 'VIEW', request, "Patient viewed portal dashboard")

    return render(request, 'portal/dashboard.html', {
        'page_title':            'My Health Portal',
        'patient':               patient,
        'lab_results':           lab_results,
        'active_meds':           active_meds,
        'overdue_doses':         overdue_doses,
        'upcoming_appointments': upcoming_appointments,
        'recent_records':        recent_records,
        'today':                 today,
    })


@login_required
def portal_profile_view(request):
    """Patient views their own profile — read only."""
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    log_action(request.user, 'VIEW', request, "Patient viewed own profile")

    profile_rows_personal = [
        ('Hospital Number',    patient.hospital_number),
        ('Full Name',          patient.full_name),
        ('Date of Birth',      patient.date_of_birth.strftime('%d %B %Y') if patient.date_of_birth else ''),
        ('Age',                f'{patient.age} years' if patient.age else ''),
        ('Gender',             patient.get_gender_display()),
        ('Marital Status',     patient.get_marital_status_display() if patient.marital_status else ''),
        ('Religion',           patient.get_religion_display() if patient.religion else ''),
        ('Occupation',         patient.occupation),
        ('Phone Number',       patient.phone_number),
        ('Alt. Phone',         patient.alt_phone_number),
        ('Email',              patient.email),
        ('Address',            patient.address),
        ('City / State',       f'{patient.city}, {patient.state}'.strip(', ') if patient.city or patient.state else ''),
        ('Hometown',           patient.hometown),
        ('State of Origin',    patient.state_of_origin),
        ('Nationality',        patient.nationality),
    ]
    profile_rows_medical = [
        ('Blood Group',        patient.blood_group),
        ('Genotype',           patient.genotype),
        ('Allergies',          patient.allergies),
        ('Chronic Conditions', patient.chronic_conditions),
        ('Disabilities',       patient.disabilities),
        ('Insurance Provider', patient.insurance_provider),
        ('NHIS Number',        patient.nhis_number),
        ('Next of Kin',        patient.nok_name),
        ('NOK Relationship',   patient.get_nok_relationship_display() if patient.nok_relationship else ''),
        ('NOK Phone',          patient.nok_phone),
        ('Assigned Doctor',    f'Dr. {patient.assigned_doctor.get_full_name()}' if patient.assigned_doctor else ''),
    ]

    return render(request, 'portal/profile.html', {
        'page_title':            'My Profile',
        'patient':               patient,
        'profile_rows_personal': profile_rows_personal,
        'profile_rows_medical':  profile_rows_medical,
    })


@login_required
def portal_lab_results_view(request):
    """Patient sees only their released lab results."""
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    from apps.lab_results.models import LabResult
    results = LabResult.objects.filter(
        patient=patient,
        status='released',
    ).order_by('-ordered_at')

    log_action(request.user, 'VIEW', request, "Patient viewed lab results")
    return render(request, 'portal/lab_results.html', {
        'page_title': 'My Lab Results',
        'results':    results,
        'patient':    patient,
    })


@login_required
def portal_lab_result_detail_view(request, pk):
    """Patient views one released lab result."""
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    from apps.lab_results.models import LabResult
    # get_object_or_404 + patient check = only their own results
    result = get_object_or_404(
        LabResult, pk=pk, patient=patient, status='released'
    )
    log_action(request.user, 'VIEW', request, f"Patient viewed lab result #{pk}")
    return render(request, 'portal/lab_result_detail.html', {
        'page_title': f"Result — {result.template.name if result.template else 'Lab Result'}",
        'result':     result,
        'patient':    patient,
    })


@login_required
def portal_medications_view(request):
    """Patient sees their medication timetable and can tick doses."""
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    from apps.medications.models import MedicationSchedule, MedicationDose

    today = timezone.now().date()
    now   = timezone.now()

    active_schedules = MedicationSchedule.objects.filter(
        patient=patient,
        is_active=True,
        end_date__gte=today,
    ).prefetch_related('doses').order_by('drug_name')

    # Today's doses for the timetable
    todays_doses = MedicationDose.objects.filter(
        schedule__patient=patient,
        schedule__is_active=True,
        scheduled_datetime__date=today,
    ).select_related('schedule').order_by('scheduled_datetime')

    log_action(request.user, 'VIEW', request, "Patient viewed medications")
    return render(request, 'portal/medications.html', {
        'page_title':       'My Medications',
        'active_schedules': active_schedules,
        'todays_doses':     todays_doses,
        'patient':          patient,
        'today':            today,
        'now':              now,
    })


@login_required
def portal_tick_dose_view(request, dose_pk):
    """Patient marks a dose as taken."""
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    from apps.medications.models import MedicationDose
    dose = get_object_or_404(
        MedicationDose,
        pk=dose_pk,
        schedule__patient=patient,    # only their own doses
        taken=False,
    )
    dose.taken    = True
    dose.taken_at = timezone.now()
    dose.save()
    log_action(request.user, 'UPDATE', request, f"Patient ticked dose #{dose_pk}")
    messages.success(request, f"Dose marked as taken.")
    return redirect('portal:medications')


@login_required
def portal_appointments_view(request):
    """Patient sees their upcoming appointments."""
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    from apps.appointments.models import Appointment
    today = timezone.now().date()

    upcoming = Appointment.objects.filter(
        patient=patient,
        appointment_date__gte=today,
        status__in=['scheduled', 'confirmed'],
    ).order_by('appointment_date', 'appointment_time')

    past = Appointment.objects.filter(
        patient=patient,
        appointment_date__lt=today,
    ).order_by('-appointment_date')[:10]

    log_action(request.user, 'VIEW', request, "Patient viewed appointments")
    return render(request, 'portal/appointments.html', {
        'page_title': 'My Appointments',
        'upcoming':   upcoming,
        'past':       past,
        'patient':    patient,
    })


@login_required
def portal_records_view(request):
    """Patient sees only records marked visible to them."""
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    from apps.records.models import MedicalRecord
    records = MedicalRecord.objects.filter(
        patient=patient,
        is_deleted=False,
        is_visible_to_patient=True,
    ).order_by('-uploaded_at')

    log_action(request.user, 'VIEW', request, "Patient viewed medical records")
    return render(request, 'portal/records.html', {
        'page_title': 'My Medical Records',
        'records':    records,
        'patient':    patient,
    })


@login_required
def portal_record_detail_view(request, pk):
    """Patient views one of their visible records."""
    patient, deny = _get_patient_or_deny(request)
    if deny:
        return deny

    from apps.records.models import MedicalRecord
    record = get_object_or_404(
        MedicalRecord,
        pk=pk,
        patient=patient,
        is_deleted=False,
        is_visible_to_patient=True,
    )
    log_action(request.user, 'VIEW', request, f"Patient viewed record #{pk}")
    return render(request, 'portal/record_detail.html', {
        'page_title': record.title,
        'record':     record,
        'patient':    patient,
    })