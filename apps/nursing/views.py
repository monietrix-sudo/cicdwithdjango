"""
AbiCare - Nursing Module Views
================================
Features:
- Smart welcome based on duty roster (knows your shift)
- Shift reports with handover
- Vitals tracking
- Medication administration records
- Voice-transcribed nursing notes
- Materials used tracking
- Duty roster creation and email/WhatsApp distribution
- Quick review and deep dive views
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import json

from .models import (
    DutyRoster, RosterEntry, ShiftReport,
    VitalsRecord, MedicationAdminRecord, NursingNote, MaterialUsed
)
from apps.audit_logs.utils import log_action


def _nurse_required(view_func):
    """Allow only nurses, head nurses, and admins."""
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if request.user.role in ('nurse', 'admin') or request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        messages.error(request, "Nursing module access is for nurses and admins only.")
        return redirect('patients:dashboard')
    return wrapper


def _get_todays_shift_entry(user):
    """Return today's RosterEntry for this nurse if it exists."""
    today = timezone.now().date()
    return RosterEntry.objects.filter(
        nurse=user, date=today
    ).select_related('roster').first()


def _get_current_shift_label():
    """Return the current shift based on the hour."""
    hour = timezone.now().hour
    if 7 <= hour < 15:
        return 'morning'
    elif 15 <= hour < 23:
        return 'afternoon'
    else:
        return 'night'


# ─────────────────────────────────────────────────────────────────────
# NURSING DASHBOARD — Smart Welcome
# ─────────────────────────────────────────────────────────────────────

@login_required
@_nurse_required
def nursing_dashboard_view(request):
    """
    Smart welcome dashboard. Knows the nurse's shift from the roster.
    Shows today's quick stats, active patients, pending vitals, and notes to review.
    """
    today       = timezone.now().date()
    now         = timezone.now()
    nurse       = request.user
    shift_entry = _get_todays_shift_entry(nurse)
    current_shift = _get_current_shift_label()

    # Personalised greeting based on time
    hour = now.hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    # Today's open shift report
    todays_report = ShiftReport.objects.filter(
        nurse=nurse, date=today, is_submitted=False
    ).first()

    # Recent vitals by this nurse
    recent_vitals = VitalsRecord.objects.filter(
        recorded_by=nurse
    ).select_related('patient').order_by('-recorded_at')[:8]

    # Critical vitals
    critical_vitals = [v for v in recent_vitals if v.is_critical]

    # Unread flagged notes from previous shifts
    flagged_notes = NursingNote.objects.filter(
        is_flagged=True
    ).select_related('patient', 'written_by').order_by('-created_at')[:5]

    # Today's MAR entries by this nurse
    todays_mar = MedicationAdminRecord.objects.filter(
        administered_by=nurse,
        scheduled_time__date=today,
    ).select_related('patient').order_by('scheduled_time')[:10]

    # Pending medications (withheld/missed)
    pending_mar = todays_mar.filter(status__in=['withheld', 'missed', 'refused'])

    log_action(nurse, 'VIEW', request, "Nursing dashboard")

    return render(request, 'nursing/dashboard.html', {
        'page_title':     'Nursing Dashboard',
        'nurse':          nurse,
        'greeting':       greeting,
        'shift_entry':    shift_entry,
        'current_shift':  current_shift,
        'todays_report':  todays_report,
        'recent_vitals':  recent_vitals,
        'critical_vitals': critical_vitals,
        'flagged_notes':  flagged_notes,
        'todays_mar':     todays_mar,
        'pending_mar':    pending_mar,
        'today':          today,
        'now':            now,
    })


# ─────────────────────────────────────────────────────────────────────
# SHIFT REPORT
# ─────────────────────────────────────────────────────────────────────

@login_required
@_nurse_required
def shift_report_list_view(request):
    reports = ShiftReport.objects.filter(
        nurse=request.user
    ).order_by('-date', '-shift_start')[:30]
    return render(request, 'nursing/shift_report_list.html', {
        'page_title': 'My Shift Reports',
        'reports':    reports,
    })


@login_required
@_nurse_required
def start_shift_report_view(request):
    """Start a new shift report for today. Pre-fills from roster if available."""
    today       = timezone.now().date()
    shift_entry = _get_todays_shift_entry(request.user)
    current_shift = _get_current_shift_label()

    # Don't create duplicate open reports
    existing = ShiftReport.objects.filter(
        nurse=request.user, date=today,
        shift=shift_entry.shift if shift_entry else current_shift,
        is_submitted=False,
    ).first()
    if existing:
        return redirect('nursing:shift_report_detail', pk=existing.pk)

    if request.method == 'POST':
        report = ShiftReport.objects.create(
            nurse=request.user,
            shift=request.POST.get('shift', current_shift),
            ward=request.POST.get('ward', ''),
            date=today,
            shift_start=timezone.now(),
            patients_on_ward=int(request.POST.get('patients_on_ward', 0) or 0),
            general_ward_notes=request.POST.get('general_ward_notes', '').strip(),
        )
        log_action(request.user, 'CREATE', request,
                   f"Started shift report #{report.pk}")
        messages.success(request,
            f"Shift started. Add vitals, notes, and MAR entries below.")
        return redirect('nursing:shift_report_detail', pk=report.pk)

    return render(request, 'nursing/start_shift.html', {
        'page_title':     'Start Shift Report',
        'shift_entry':    shift_entry,
        'current_shift':  current_shift,
        'shift_choices':  ShiftReport.SHIFT_CHOICES,
        'ward_choices':   DutyRoster.WARD_CHOICES,
        'today':          today,
    })


@login_required
@_nurse_required
def shift_report_detail_view(request, pk):
    """
    The main shift working view.
    Shows quick summary + tabs for Vitals, MAR, Notes, Materials.
    Supports quick review (summary) and deep dive (full detail).
    """
    report  = get_object_or_404(ShiftReport, pk=pk)
    patient_qs = request.GET.get('patient', '')
    mode    = request.GET.get('mode', 'quick')  # quick or deep

    # Prefetch all related data in as few queries as possible
    vitals    = report.vitals.select_related('patient', 'recorded_by').order_by('-recorded_at')
    mar       = report.mar_entries.select_related('patient', 'administered_by').order_by('scheduled_time')
    notes     = report.notes.select_related('patient', 'written_by').order_by('-created_at')
    materials = report.materials.select_related('patient', 'recorded_by').order_by('-recorded_at')

    # Patient filter
    if patient_qs:
        vitals    = vitals.filter(patient__hospital_number=patient_qs)
        mar       = mar.filter(patient__hospital_number=patient_qs)
        notes     = notes.filter(patient__hospital_number=patient_qs)
        materials = materials.filter(patient__hospital_number=patient_qs)

    # Critical vitals count for quick review badge
    critical_count = sum(1 for v in vitals if v.is_critical)

    tabs = [
        ('vitals',    'Vitals',     'fa-heartbeat'),
        ('notes',     'Notes',      'fa-sticky-note'),
        ('mar',       'Medications','fa-pills'),
        ('materials', 'Materials',  'fa-box'),
    ]
    log_action(request.user, 'VIEW', request, f"Shift report #{pk} [{mode} mode]")

    return render(request, 'nursing/shift_report_detail.html', {
        'page_title':     f"Shift Report — {report.get_shift_display()} {report.date}",
        'report':         report,
        'vitals':         vitals,
        'mar':            mar,
        'notes':          notes,
        'materials':      materials,
        'critical_count': critical_count,
        'mode':           mode,
        'patient_filter': patient_qs,
        'mar_status_choices': MedicationAdminRecord.STATUS_CHOICES,
        'note_type_choices':  NursingNote.NOTE_TYPE_CHOICES,
        'tabs':               tabs,
        'material_categories': MaterialUsed.CATEGORY_CHOICES,
        'route_choices':  ['Oral', 'IV', 'IM', 'SC', 'PR', 'Topical', 'Inhalation'],
    })


@login_required
@_nurse_required
def submit_shift_report_view(request, pk):
    """Mark shift report as submitted (handed over)."""
    report = get_object_or_404(ShiftReport, pk=pk, nurse=request.user)
    if request.method == 'POST':
        report.handover_summary  = request.POST.get('handover_summary', '').strip()
        report.outstanding_tasks = request.POST.get('outstanding_tasks', '').strip()
        report.incidents         = request.POST.get('incidents', '').strip()
        report.patients_admitted    = int(request.POST.get('patients_admitted', 0) or 0)
        report.patients_discharged  = int(request.POST.get('patients_discharged', 0) or 0)
        report.patients_on_ward     = int(request.POST.get('patients_on_ward', 0) or 0)
        report.is_submitted  = True
        report.submitted_at  = timezone.now()
        report.shift_end     = timezone.now()
        report.save()
        log_action(request.user, 'UPDATE', request,
                   f"Submitted shift report #{pk}")
        messages.success(request,
            "Shift report submitted and handed over. Good rest!")
        return redirect('nursing:dashboard')
    return redirect('nursing:shift_report_detail', pk=pk)


@login_required
@_nurse_required
def handover_view(request, pk):
    """Quick handover summary for reading the incoming shift report."""
    report    = get_object_or_404(ShiftReport, pk=pk)
    vitals    = report.vitals.select_related('patient').order_by('-recorded_at')
    critical  = [v for v in vitals if v.is_critical]
    notes     = report.notes.filter(is_flagged=True).select_related('patient')
    return render(request, 'nursing/handover.html', {
        'page_title': f"Handover — {report.get_shift_display()} {report.date}",
        'report':     report,
        'critical':   critical,
        'flagged_notes': notes,
        'all_vitals': vitals[:10],
        'mar_issues': report.mar_entries.filter(
            status__in=['withheld', 'missed', 'refused']
        ).select_related('patient'),
        'materials':  report.materials.select_related('patient'),
    })


# ─────────────────────────────────────────────────────────────────────
# VITALS — AJAX save
# ─────────────────────────────────────────────────────────────────────

@login_required
@_nurse_required
def add_vitals_view(request, report_pk):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST only'}, status=405)

    report  = get_object_or_404(ShiftReport, pk=report_pk)
    p = request.POST

    def _int(key):
        try: return int(p.get(key) or 0) or None
        except: return None

    def _dec(key):
        try: return float(p.get(key) or 0) or None
        except: return None

    patient_hn = p.get('patient_hospital_number', '').strip()
    if not patient_hn:
        return JsonResponse({'ok': False, 'error': 'Patient hospital number required'}, status=400)

    from apps.patients.models import Patient
    patient = get_object_or_404(Patient, hospital_number=patient_hn, is_active=True)

    vitals = VitalsRecord.objects.create(
        shift_report=report,
        patient=patient,
        recorded_by=request.user,
        temperature=_dec('temperature'),
        pulse_rate=_int('pulse_rate'),
        respiratory_rate=_int('respiratory_rate'),
        blood_pressure_sys=_int('blood_pressure_sys'),
        blood_pressure_dia=_int('blood_pressure_dia'),
        oxygen_saturation=_dec('oxygen_saturation'),
        blood_glucose=_dec('blood_glucose'),
        weight_kg=_dec('weight_kg'),
        pain_score=_int('pain_score'),
        consciousness=p.get('consciousness', ''),
        urine_output_ml=_int('urine_output_ml'),
        notes=p.get('notes', '').strip(),
    )

    return JsonResponse({
        'ok':         True,
        'vitals_pk':  vitals.pk,
        'patient':    patient.full_name,
        'is_critical': vitals.is_critical,
        'bp':         vitals.blood_pressure,
        'recorded_at': vitals.recorded_at.strftime('%H:%M'),
    })


# ─────────────────────────────────────────────────────────────────────
# NURSING NOTE — AJAX save (supports voice transcription)
# ─────────────────────────────────────────────────────────────────────

@login_required
@_nurse_required
def add_note_view(request, report_pk):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    report     = get_object_or_404(ShiftReport, pk=report_pk)
    p          = request.POST
    patient_hn = p.get('patient_hospital_number', '').strip()
    content    = p.get('content', '').strip()

    if not content:
        return JsonResponse({'ok': False, 'error': 'Note content is required'}, status=400)
    if not patient_hn:
        return JsonResponse({'ok': False, 'error': 'Patient required'}, status=400)

    from apps.patients.models import Patient
    patient = get_object_or_404(Patient, hospital_number=patient_hn, is_active=True)

    note = NursingNote.objects.create(
        shift_report=report,
        patient=patient,
        written_by=request.user,
        note_type=p.get('note_type', 'observation'),
        content=content,
        was_voice=p.get('was_voice', 'false').lower() == 'true',
        is_flagged=p.get('is_flagged', 'false').lower() == 'true',
    )

    return JsonResponse({
        'ok':       True,
        'note_pk':  note.pk,
        'patient':  patient.full_name,
        'type':     note.get_note_type_display(),
        'was_voice': note.was_voice,
        'flagged':  note.is_flagged,
        'time':     note.created_at.strftime('%H:%M'),
        'content_preview': content[:80] + ('…' if len(content) > 80 else ''),
    })


# ─────────────────────────────────────────────────────────────────────
# MAR — AJAX save
# ─────────────────────────────────────────────────────────────────────

@login_required
@_nurse_required
def add_mar_view(request, report_pk):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    report     = get_object_or_404(ShiftReport, pk=report_pk)
    p          = request.POST
    patient_hn = p.get('patient_hospital_number', '').strip()

    from apps.patients.models import Patient
    patient = get_object_or_404(Patient, hospital_number=patient_hn, is_active=True)

    from datetime import datetime
    sched_raw = p.get('scheduled_time', '')
    try:
        sched = timezone.make_aware(
            datetime.strptime(sched_raw, '%Y-%m-%dT%H:%M')
        )
    except (ValueError, TypeError):
        sched = timezone.now()

    given_raw = p.get('given_time', '')
    given = None
    if given_raw:
        try:
            given = timezone.make_aware(datetime.strptime(given_raw, '%Y-%m-%dT%H:%M'))
        except:
            given = timezone.now()

    mar = MedicationAdminRecord.objects.create(
        shift_report=report,
        patient=patient,
        administered_by=request.user,
        medication_name=p.get('medication_name', '').strip(),
        dosage=p.get('dosage', '').strip(),
        route=p.get('route', '').strip(),
        scheduled_time=sched,
        given_time=given,
        status=p.get('status', 'given'),
        reason_withheld=p.get('reason_withheld', '').strip(),
        notes=p.get('notes', '').strip(),
    )

    return JsonResponse({
        'ok':      True,
        'mar_pk':  mar.pk,
        'patient': patient.full_name,
        'drug':    mar.medication_name,
        'status':  mar.get_status_display(),
        'time':    mar.scheduled_time.strftime('%H:%M'),
    })


# ─────────────────────────────────────────────────────────────────────
# MATERIAL — AJAX save
# ─────────────────────────────────────────────────────────────────────

@login_required
@_nurse_required
def add_material_view(request, report_pk):
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    report  = get_object_or_404(ShiftReport, pk=report_pk)
    p       = request.POST
    patient_hn = p.get('patient_hospital_number', '').strip()

    patient = None
    if patient_hn:
        from apps.patients.models import Patient
        try:
            patient = Patient.objects.get(hospital_number=patient_hn, is_active=True)
        except Patient.DoesNotExist:
            pass

    material = MaterialUsed.objects.create(
        shift_report=report,
        patient=patient,
        recorded_by=request.user,
        category=p.get('category', 'other'),
        item_name=p.get('item_name', '').strip(),
        quantity=float(p.get('quantity', 1) or 1),
        unit=p.get('unit', '').strip(),
        notes=p.get('notes', '').strip(),
    )

    return JsonResponse({
        'ok':         True,
        'material_pk': material.pk,
        'item':       material.item_name,
        'quantity':   str(material.quantity),
        'unit':       material.unit,
        'patient':    patient.full_name if patient else 'Ward (general)',
    })


# ─────────────────────────────────────────────────────────────────────
# PATIENT VITALS QUICK VIEW (standalone, not tied to a shift)
# ─────────────────────────────────────────────────────────────────────

@login_required
@_nurse_required
def patient_vitals_view(request, hospital_number):
    """Quick vitals history for one patient."""
    from apps.patients.models import Patient
    patient = get_object_or_404(Patient, hospital_number=hospital_number)
    vitals  = VitalsRecord.objects.filter(
        patient=patient
    ).select_related('recorded_by').order_by('-recorded_at')[:50]

    return render(request, 'nursing/patient_vitals.html', {
        'page_title': f"Vitals — {patient.full_name}",
        'patient':    patient,
        'vitals':     vitals,
    })


# ─────────────────────────────────────────────────────────────────────
# DUTY ROSTER
# ─────────────────────────────────────────────────────────────────────

@login_required
@_nurse_required
def roster_list_view(request):
    rosters = DutyRoster.objects.all().prefetch_related(
        'entries__nurse'
    ).order_by('-start_date')[:20]
    return render(request, 'nursing/roster_list.html', {
        'page_title': 'Duty Rosters',
        'rosters':    rosters,
    })


@login_required
@_nurse_required
def roster_detail_view(request, pk):
    roster  = get_object_or_404(DutyRoster, pk=pk)
    entries = roster.entries.select_related('nurse').order_by('date', 'nurse__last_name')

    # Group entries by date for display
    from itertools import groupby
    from operator import attrgetter
    grouped = {}
    for entry in entries:
        grouped.setdefault(entry.date, []).append(entry)

    return render(request, 'nursing/roster_detail.html', {
        'page_title': roster.title,
        'roster':     roster,
        'grouped':    grouped,
        'entries':    entries,
    })


@login_required
@_nurse_required
def create_roster_view(request):
    """Create a new duty roster."""
    from apps.accounts.models import User
    nurses = User.objects.filter(role='nurse', is_active=True).order_by('last_name')

    if request.method == 'POST':
        roster = DutyRoster.objects.create(
            title=request.POST.get('title', '').strip(),
            ward=request.POST.get('ward', 'all'),
            start_date=request.POST.get('start_date'),
            end_date=request.POST.get('end_date'),
            notes=request.POST.get('notes', '').strip(),
            created_by=request.user,
        )
        log_action(request.user, 'CREATE', request,
                   f"Created duty roster: {roster.title}")
        messages.success(request,
            f"Roster '{roster.title}' created. Add nurse assignments below.")
        return redirect('nursing:roster_detail', pk=roster.pk)

    return render(request, 'nursing/create_roster.html', {
        'page_title':  'Create Duty Roster',
        'nurses':      nurses,
        'ward_choices': DutyRoster.WARD_CHOICES,
    })


@login_required
@_nurse_required
def add_roster_entry_view(request, roster_pk):
    """Add a nurse assignment to a roster."""
    roster = get_object_or_404(DutyRoster, pk=roster_pk)
    if request.method == 'POST':
        from apps.accounts.models import User
        nurse_id = request.POST.get('nurse_id')
        try:
            nurse = User.objects.get(pk=nurse_id, role='nurse')
        except User.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Nurse not found'}, status=400)

        import datetime
        date_str = request.POST.get('date', '')
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError:
            return JsonResponse({'ok': False, 'error': 'Invalid date'}, status=400)

        entry, created = RosterEntry.objects.update_or_create(
            roster=roster, nurse=nurse, date=date,
            defaults={
                'shift': request.POST.get('shift', 'morning'),
                'ward':  request.POST.get('ward', ''),
                'notes': request.POST.get('notes', '').strip(),
            }
        )
        return JsonResponse({
            'ok':    True,
            'nurse': nurse.get_full_name(),
            'date':  str(date),
            'shift': entry.get_shift_display(),
        })
    return JsonResponse({'ok': False}, status=405)


@login_required
@_nurse_required
def confirm_and_distribute_roster_view(request, pk):
    """
    Head nurse confirms the roster.
    Sends it to each assigned nurse via email and optionally WhatsApp.
    """
    roster  = get_object_or_404(DutyRoster, pk=pk)
    entries = roster.entries.select_related('nurse').order_by('nurse__last_name', 'date')

    if request.method == 'POST':
        roster.status       = 'confirmed'
        roster.confirmed_by = request.user
        roster.confirmed_at = timezone.now()
        roster.save()

        sent_count = 0
        failed = []

        # Group entries per nurse
        nurse_entries = {}
        for entry in entries:
            nurse_entries.setdefault(entry.nurse, []).append(entry)

        for nurse, shifts in nurse_entries.items():
            _send_roster_to_nurse(request, nurse, roster, shifts)
            sent_count += 1

        log_action(request.user, 'APPROVE', request,
                   f"Confirmed and distributed roster: {roster.title}")
        messages.success(request,
            f"Roster confirmed and sent to {sent_count} nurses.")
        return redirect('nursing:roster_detail', pk=pk)

    return render(request, 'nursing/confirm_roster.html', {
        'page_title': f"Confirm Roster — {roster.title}",
        'roster':     roster,
        'entries':    entries,
    })


def _send_roster_to_nurse(request, nurse, roster, shifts):
    """Send duty roster to a nurse via email and optionally WhatsApp."""
    from django.core.mail import send_mail
    from django.conf import settings

    # Build the schedule text
    schedule_lines = [
        f"DUTY ROSTER — {roster.title}",
        f"Period: {roster.start_date} to {roster.end_date}",
        f"Ward: {roster.get_ward_display()}",
        "",
        f"Dear {nurse.first_name},",
        "Your shift schedule is as follows:",
        "",
    ]
    for entry in sorted(shifts, key=lambda e: e.date):
        if entry.shift == 'off':
            schedule_lines.append(f"  {entry.date.strftime('%a %d %b')}  —  Day Off")
        else:
            schedule_lines.append(
                f"  {entry.date.strftime('%a %d %b')}  —  "
                f"{entry.get_shift_display()}"
                + (f"  ({entry.get_ward_display()})" if entry.ward else "")
            )

    if roster.notes:
        schedule_lines += ["", "Notes from Head Nurse:", roster.notes]

    schedule_lines += [
        "",
        f"— {settings.HOSPITAL_NAME} Nursing Administration",
    ]
    message = "\n".join(schedule_lines)

    # Email
    if nurse.email:
        try:
            send_mail(
                subject=f"[{settings.HOSPITAL_NAME}] Your Duty Roster — {roster.title}",
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[nurse.email],
                fail_silently=True,
            )
        except Exception:
            pass

    # WhatsApp via Twilio
    try:
        from apps.notifications.utils import send_notification
        send_notification(
            user=nurse,
            notif_type='general',
            title=f"Duty Roster: {roster.title}",
            message=f"Your roster has been confirmed. {len(shifts)} shifts assigned. Check your email or the portal for details.",
            link=f"/nursing/rosters/{roster.pk}/",
        )
    except Exception:
        pass

# Create your views here.
