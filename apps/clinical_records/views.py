"""
AbiCare - Clinical Records Views
====================================
Access control:
- Doctor, Nurse, Admin: full access
- Receptionist, Lab Tech: DENIED
- Patient: only records explicitly approved by doctor
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone

from .models import PatientEncounter, Diagnosis, Operation
from apps.patients.models import Patient
from apps.audit_logs.utils import log_action

ALLOWED_STAFF_ROLES = ['admin', 'doctor', 'nurse']


def _check_access(request):
    """Returns True if user can access clinical records."""
    user = request.user
    if user.is_superuser or user.role in ALLOWED_STAFF_ROLES:
        return True
    return False


@login_required
def patient_records_view(request, hospital_number):
    """Main records view for a patient — all encounters inline."""
    patient = get_object_or_404(Patient, hospital_number=hospital_number)

    # Patient portal access
    if request.user.is_patient_user:
        if not hasattr(request.user, 'patient_profile') or \
           request.user.patient_profile != patient:
            messages.error(request, "Access denied.")
            return redirect('portal:dashboard')
        # Patients only see approved records
        encounters = PatientEncounter.objects.filter(
            patient=patient, approved_for_patient=True
        ).prefetch_related('diagnoses', 'operations')
        log_action(request.user, 'VIEW', request,
                   f"Patient viewed own clinical records: {hospital_number}")
        return render(request, 'clinical_records/patient_view.html', {
            'page_title': 'My Medical Records',
            'patient':    patient,
            'encounters': encounters,
        })

    # Staff access check
    if not _check_access(request):
        messages.error(request,
            "Access denied. Only doctors, nurses, and administrators can view clinical records.")
        return redirect('patients:dashboard')

    encounters = PatientEncounter.objects.filter(
        patient=patient
    ).prefetch_related('diagnoses', 'operations').order_by('-encounter_date')

    log_action(request.user, 'VIEW', request,
               f"Viewed clinical records for {hospital_number}")
    return render(request, 'clinical_records/patient_records.html', {
        'page_title': f"Clinical Records — {patient.full_name}",
        'patient':    patient,
        'encounters': encounters,
    })


@login_required
def add_encounter_view(request, hospital_number):
    if not _check_access(request):
        messages.error(request, "Access denied.")
        return redirect('patients:dashboard')

    patient = get_object_or_404(Patient, hospital_number=hospital_number)
    from apps.accounts.models import User
    doctors = User.objects.filter(role='doctor', is_active=True)

    if request.method == 'POST':
        enc = PatientEncounter(
            patient=patient,
            encounter_type=request.POST.get('encounter_type', 'outpatient'),
            encounter_date=request.POST.get('encounter_date') or timezone.now().date(),
            presenting_complaint=request.POST.get('presenting_complaint', '').strip(),
            history_of_illness=request.POST.get('history_of_illness', '').strip(),
            examination_findings=request.POST.get('examination_findings', '').strip(),
            treatment_plan=request.POST.get('treatment_plan', '').strip(),
            doctors_report=request.POST.get('doctors_report', '').strip(),
            ward_admitted=request.POST.get('ward_admitted', ''),
            bed_number=request.POST.get('bed_number', '').strip(),
            billing_code=request.POST.get('billing_code', '').strip(),
            discharge_date=request.POST.get('discharge_date') or None,
            discharge_summary=request.POST.get('discharge_summary', '').strip(),
            consultant_name_text=request.POST.get('consultant_name_text', '').strip(),
            referring_doctor=request.POST.get('referring_doctor', '').strip(),
            created_by=request.user,
        )
        consultant_id = request.POST.get('consultant_id')
        if consultant_id:
            enc.consultant_id = int(consultant_id)

        status_map = {
            'inpatient': 'active',
            'outpatient': 'outpatient',
            'emergency': 'active',
            'day_case': 'active',
            'review': 'outpatient',
        }
        enc.status = status_map.get(enc.encounter_type, 'outpatient')
        enc.save()

        log_action(request.user, 'CREATE', request,
                   f"Added {enc.get_encounter_type_display()} encounter for {hospital_number}")
        messages.success(request,
            f"{enc.get_encounter_type_display()} record created. "
            f"You can now add diagnoses and operations.")
        return redirect('clinical_records:encounter_detail', pk=enc.pk)

    return render(request, 'clinical_records/add_encounter.html', {
        'page_title':       f"Add Clinical Record — {patient.full_name}",
        'patient':          patient,
        'doctors':          doctors,
        'encounter_types':  PatientEncounter.ENCOUNTER_TYPE_CHOICES,
        'ward_choices':     PatientEncounter.WARD_CHOICES,
        'today':            timezone.now().date(),
    })


@login_required
def encounter_detail_view(request, pk):
    encounter = get_object_or_404(PatientEncounter, pk=pk)

    if request.user.is_patient_user:
        if not hasattr(request.user, 'patient_profile') or \
           request.user.patient_profile != encounter.patient or \
           not encounter.approved_for_patient:
            messages.error(request, "This record is not available.")
            return redirect('portal:dashboard')
    elif not _check_access(request):
        messages.error(request, "Access denied.")
        return redirect('patients:dashboard')

    log_action(request.user, 'VIEW', request, f"Viewed encounter #{pk}")
    return render(request, 'clinical_records/encounter_detail.html', {
        'page_title':   f"Record — {encounter.patient.full_name}",
        'encounter':    encounter,
        'diagnoses':    encounter.diagnoses.all(),
        'operations':   encounter.operations.all(),
        'diag_types':   Diagnosis.DIAGNOSIS_TYPE_CHOICES,
        'op_types':     Operation.OPERATION_TYPE_CHOICES,
        'today':        timezone.now().date(),
    })


@login_required
def edit_encounter_view(request, pk):
    if not _check_access(request):
        messages.error(request, "Access denied.")
        return redirect('patients:dashboard')

    encounter = get_object_or_404(PatientEncounter, pk=pk)
    from apps.accounts.models import User
    doctors = User.objects.filter(role='doctor', is_active=True)

    if request.method == 'POST':
        encounter.presenting_complaint  = request.POST.get('presenting_complaint', '').strip()
        encounter.history_of_illness    = request.POST.get('history_of_illness', '').strip()
        encounter.examination_findings  = request.POST.get('examination_findings', '').strip()
        encounter.treatment_plan        = request.POST.get('treatment_plan', '').strip()
        encounter.doctors_report        = request.POST.get('doctors_report', '').strip()
        encounter.discharge_summary     = request.POST.get('discharge_summary', '').strip()
        encounter.billing_code          = request.POST.get('billing_code', '').strip()
        discharge_date = request.POST.get('discharge_date')
        if discharge_date:
            encounter.discharge_date = discharge_date
            encounter.status         = 'discharged'
        consultant_id = request.POST.get('consultant_id')
        if consultant_id:
            encounter.consultant_id = int(consultant_id)
        encounter.save()
        log_action(request.user, 'UPDATE', request, f"Edited encounter #{pk}")
        messages.success(request, "Record updated.")
        return redirect('clinical_records:encounter_detail', pk=pk)

    return render(request, 'clinical_records/edit_encounter.html', {
        'page_title': 'Edit Clinical Record',
        'encounter':  encounter,
        'doctors':    doctors,
        'ward_choices': PatientEncounter.WARD_CHOICES,
    })


@login_required
def add_diagnosis_view(request, pk):
    if not (request.user.is_admin_staff or request.user.is_doctor):
        messages.error(request, "Only doctors and admins can add diagnoses.")
        return redirect('patients:dashboard')

    encounter = get_object_or_404(PatientEncounter, pk=pk)
    if request.method == 'POST':
        Diagnosis.objects.create(
            encounter=encounter,
            diagnosis_date=request.POST.get('diagnosis_date') or timezone.now().date(),
            diagnosis_code=request.POST.get('diagnosis_code', '').strip(),
            diagnosis_name=request.POST.get('diagnosis_name', '').strip(),
            diagnosis_type=request.POST.get('diagnosis_type', 'primary'),
            notes=request.POST.get('notes', '').strip(),
            diagnosed_by=request.user,
        )
        log_action(request.user, 'CREATE', request,
                   f"Added diagnosis to encounter #{pk}")
        messages.success(request, "Diagnosis added.")
    return redirect('clinical_records:encounter_detail', pk=pk)


@login_required
def add_operation_view(request, pk):
    if not (request.user.is_admin_staff or request.user.is_doctor):
        messages.error(request, "Only doctors and admins can add operations.")
        return redirect('patients:dashboard')

    encounter = get_object_or_404(PatientEncounter, pk=pk)
    if request.method == 'POST':
        from apps.accounts.models import User
        surgeon_id = request.POST.get('surgeon_id')
        op = Operation(
            encounter=encounter,
            operation_date=request.POST.get('operation_date') or timezone.now().date(),
            operation_type=request.POST.get('operation_type', 'minor'),
            operation_name=request.POST.get('operation_name', '').strip(),
            operation_code=request.POST.get('operation_code', '').strip(),
            anaesthesia_type=request.POST.get('anaesthesia_type', '').strip(),
            notes=request.POST.get('notes', '').strip(),
            doctors_remark=request.POST.get('doctors_remark', '').strip(),
            complications=request.POST.get('complications', '').strip(),
            outcome=request.POST.get('outcome', 'successful'),
            surgeon_text=request.POST.get('surgeon_text', '').strip(),
        )
        if surgeon_id:
            op.surgeon_id = int(surgeon_id)
        duration = request.POST.get('duration_minutes')
        if duration:
            op.duration_minutes = int(duration)
        op.save()
        log_action(request.user, 'CREATE', request,
                   f"Added operation to encounter #{pk}")
        messages.success(request, "Operation record added.")
    return redirect('clinical_records:encounter_detail', pk=pk)


@login_required
def approve_for_patient_view(request, pk):
    """Doctor approves a record for patient portal visibility."""
    if not (request.user.is_admin_staff or request.user.is_doctor):
        messages.error(request, "Only doctors and admins can approve records for patients.")
        return redirect('patients:dashboard')

    encounter = get_object_or_404(PatientEncounter, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action', 'approve')
        if action == 'approve':
            encounter.approved_for_patient = True
            encounter.approved_by          = request.user
            encounter.approved_at          = timezone.now()
            encounter.save()

            # Notify patient if they have a portal account
            if encounter.patient.user_account:
                from apps.notifications.utils import send_notification
                send_notification(
                    user=encounter.patient.user_account,
                    notif_type='general',
                    title="Medical Record Now Available",
                    message=(
                        f"A medical record from {encounter.encounter_date.strftime('%B %d, %Y')} "
                        f"has been approved for you to view in your portal."
                    ),
                    link=f'/portal/records/',
                )

            log_action(request.user, 'APPROVE', request,
                       f"Approved encounter #{pk} for patient portal")
            messages.success(request,
                "Record approved — patient can now see it in their portal.")
        else:
            encounter.approved_for_patient = False
            encounter.approved_by          = None
            encounter.approved_at          = None
            encounter.save()
            log_action(request.user, 'REVOKE', request,
                       f"Revoked patient portal access for encounter #{pk}")
            messages.info(request, "Patient portal access revoked for this record.")

    return redirect('clinical_records:encounter_detail', pk=pk)


@login_required
def delete_diagnosis_view(request, pk):
    if not (request.user.is_admin_staff or request.user.is_doctor):
        messages.error(request, "Only doctors and admins can delete diagnoses.")
        return redirect('patients:dashboard')
    diagnosis = get_object_or_404(Diagnosis, pk=pk)
    encounter_pk = diagnosis.encounter_id
    if request.method == 'POST':
        diagnosis.delete()
        messages.success(request, "Diagnosis removed.")
    return redirect('clinical_records:encounter_detail', pk=encounter_pk)
# Create your views here.
