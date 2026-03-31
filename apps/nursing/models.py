"""
AbiCare - Nursing Module Models
=================================
Covers:
- Shift management and handover
- Vitals tracking per patient per shift
- Medication administration records (MAR)
- Nursing notes (text + voice transcription)
- Materials / consumables used during shift
- Duty roster creation and distribution
"""

import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────
# DUTY ROSTER
# ─────────────────────────────────────────────────────────────────────

class DutyRoster(models.Model):
    """
    A published nurse duty schedule for a given period.
    Head nurse creates it, confirms it, then it is distributed
    via email/WhatsApp to all assigned nurses.
    """
    STATUS_CHOICES = [
        ('draft',     'Draft'),
        ('confirmed', 'Confirmed — Distributed'),
        ('archived',  'Archived'),
    ]
    WARD_CHOICES = [
        ('general_male',   'General Ward (Male)'),
        ('general_female', 'General Ward (Female)'),
        ('paediatric',     'Paediatric Ward'),
        ('maternity',      'Maternity Ward'),
        ('icu',            'ICU / Critical Care'),
        ('surgical',       'Surgical Ward'),
        ('medical',        'Medical Ward'),
        ('emergency',      'Emergency Ward'),
        ('all',            'All Wards'),
    ]

    title        = models.CharField(max_length=200,
                                    help_text="e.g. Week 3 July 2025 — Night Shift Schedule")
    ward         = models.CharField(max_length=20, choices=WARD_CHOICES, default='all')
    start_date   = models.DateField()
    end_date     = models.DateField()
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    notes        = models.TextField(blank=True,
                                    help_text="General instructions for this roster period")
    created_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                     related_name='created_rosters')
    confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='confirmed_rosters')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']
        verbose_name = 'Duty Roster'

    def __str__(self):
        return f"{self.title} ({self.start_date} — {self.end_date})"


class RosterEntry(models.Model):
    """One nurse's assignment for one day in a roster."""
    SHIFT_CHOICES = [
        ('morning',  'Morning  07:00 — 15:00'),
        ('afternoon','Afternoon 15:00 — 23:00'),
        ('night',   'Night    23:00 — 07:00'),
        ('day',     'Day      07:00 — 19:00'),
        ('off',     'Day Off'),
    ]

    roster       = models.ForeignKey(DutyRoster, on_delete=models.CASCADE,
                                     related_name='entries')
    nurse        = models.ForeignKey(User, on_delete=models.CASCADE,
                                     related_name='roster_entries',
                                     limit_choices_to={'role': 'nurse'})
    date         = models.DateField()
    shift        = models.CharField(max_length=10, choices=SHIFT_CHOICES)
    ward         = models.CharField(max_length=20, choices=DutyRoster.WARD_CHOICES,
                                    blank=True)
    notes        = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['date', 'shift']
        unique_together = [['roster', 'nurse', 'date']]
        verbose_name = 'Roster Entry'

    def __str__(self):
        return (f"{self.nurse.get_full_name()} — "
                f"{self.date} {self.get_shift_display()}")


# ─────────────────────────────────────────────────────────────────────
# SHIFT REPORT
# ─────────────────────────────────────────────────────────────────────

class ShiftReport(models.Model):
    """
    A nurse's complete shift report.
    Contains the handover summary, ward status, and links to
    vitals, MAR entries, notes, and materials used.
    """
    SHIFT_CHOICES = [
        ('morning',   'Morning  07:00–15:00'),
        ('afternoon', 'Afternoon 15:00–23:00'),
        ('night',     'Night    23:00–07:00'),
        ('day',       'Day      07:00–19:00'),
    ]

    report_id      = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    nurse          = models.ForeignKey(User, on_delete=models.CASCADE,
                                       related_name='shift_reports')
    shift          = models.CharField(max_length=10, choices=SHIFT_CHOICES)
    ward           = models.CharField(max_length=20, choices=DutyRoster.WARD_CHOICES,
                                      default='general_female')
    date           = models.DateField(default=timezone.now)
    shift_start    = models.DateTimeField(default=timezone.now)
    shift_end      = models.DateTimeField(null=True, blank=True)

    # Handover summary — written or transcribed from voice
    handover_summary    = models.TextField(blank=True,
        verbose_name="Handover Summary",
        help_text="Summary of ward status to hand over to the next shift")
    outstanding_tasks   = models.TextField(blank=True,
        verbose_name="Outstanding Tasks / Pending Actions")
    incidents           = models.TextField(blank=True,
        verbose_name="Incidents / Events This Shift")
    general_ward_notes  = models.TextField(blank=True,
        verbose_name="General Ward Notes")

    # Ward counts
    patients_admitted   = models.PositiveIntegerField(default=0)
    patients_discharged = models.PositiveIntegerField(default=0)
    patients_on_ward    = models.PositiveIntegerField(default=0)

    # Status
    is_submitted        = models.BooleanField(default=False)
    submitted_at        = models.DateTimeField(null=True, blank=True)
    reviewed_by         = models.ForeignKey(User, on_delete=models.SET_NULL,
                                             null=True, blank=True,
                                             related_name='reviewed_shift_reports')
    reviewed_at         = models.DateTimeField(null=True, blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-shift_start']
        verbose_name = 'Shift Report'

    def __str__(self):
        return (f"{self.nurse.get_full_name()} — "
                f"{self.get_shift_display()} {self.date}")

    @property
    def duration_hours(self):
        if self.shift_start and self.shift_end:
            delta = self.shift_end - self.shift_start
            return round(delta.total_seconds() / 3600, 1)
        return None


# ─────────────────────────────────────────────────────────────────────
# VITALS
# ─────────────────────────────────────────────────────────────────────

class VitalsRecord(models.Model):
    """
    Patient vitals recorded by a nurse during a shift.
    Multiple readings can be recorded per patient per shift.
    """
    CONSCIOUSNESS_CHOICES = [
        ('alert',    'Alert'),
        ('voice',    'Responds to Voice'),
        ('pain',     'Responds to Pain'),
        ('unresponsive', 'Unresponsive'),
    ]

    shift_report    = models.ForeignKey(ShiftReport, on_delete=models.CASCADE,
                                         related_name='vitals', null=True, blank=True)
    patient         = models.ForeignKey('patients.Patient', on_delete=models.CASCADE,
                                         related_name='vitals_records')
    recorded_by     = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    recorded_at     = models.DateTimeField(default=timezone.now)

    # Core vitals
    temperature         = models.DecimalField(max_digits=4, decimal_places=1,
                                              null=True, blank=True,
                                              verbose_name="Temperature (°C)")
    pulse_rate          = models.PositiveIntegerField(null=True, blank=True,
                                                      verbose_name="Pulse Rate (bpm)")
    respiratory_rate    = models.PositiveIntegerField(null=True, blank=True,
                                                      verbose_name="Respiratory Rate (breaths/min)")
    blood_pressure_sys  = models.PositiveIntegerField(null=True, blank=True,
                                                      verbose_name="Systolic BP (mmHg)")
    blood_pressure_dia  = models.PositiveIntegerField(null=True, blank=True,
                                                      verbose_name="Diastolic BP (mmHg)")
    oxygen_saturation   = models.DecimalField(max_digits=4, decimal_places=1,
                                              null=True, blank=True,
                                              verbose_name="SpO2 (%)")
    blood_glucose       = models.DecimalField(max_digits=5, decimal_places=1,
                                              null=True, blank=True,
                                              verbose_name="Blood Glucose (mmol/L)")
    weight_kg           = models.DecimalField(max_digits=5, decimal_places=1,
                                              null=True, blank=True,
                                              verbose_name="Weight (kg)")
    height_cm           = models.DecimalField(max_digits=5, decimal_places=1,
                                              null=True, blank=True,
                                              verbose_name="Height (cm)")
    pain_score          = models.PositiveIntegerField(null=True, blank=True,
                                                      verbose_name="Pain Score (0–10)")
    consciousness       = models.CharField(max_length=15, choices=CONSCIOUSNESS_CHOICES,
                                           blank=True)
    urine_output_ml     = models.PositiveIntegerField(null=True, blank=True,
                                                      verbose_name="Urine Output (ml)")
    notes               = models.TextField(blank=True,
                                           verbose_name="Vitals Notes / Observations")

    class Meta:
        ordering = ['-recorded_at']
        verbose_name = 'Vitals Record'

    def __str__(self):
        return (f"Vitals — {self.patient.full_name} "
                f"@ {self.recorded_at.strftime('%d %b %Y %H:%M')}")

    @property
    def blood_pressure(self):
        if self.blood_pressure_sys and self.blood_pressure_dia:
            return f"{self.blood_pressure_sys}/{self.blood_pressure_dia}"
        return None

    @property
    def is_critical(self):
        """Flag if any vital is outside normal range."""
        if self.temperature and (self.temperature < 35 or self.temperature > 39):
            return True
        if self.pulse_rate and (self.pulse_rate < 50 or self.pulse_rate > 120):
            return True
        if self.oxygen_saturation and self.oxygen_saturation < 92:
            return True
        if self.blood_pressure_sys and (self.blood_pressure_sys < 90 or self.blood_pressure_sys > 180):
            return True
        if self.pain_score and self.pain_score >= 8:
            return True
        return False


# ─────────────────────────────────────────────────────────────────────
# MEDICATION ADMINISTRATION RECORD (MAR)
# ─────────────────────────────────────────────────────────────────────

class MedicationAdminRecord(models.Model):
    """
    Records that a nurse administered a specific medication dose.
    Links to the medication schedule and the shift report.
    """
    STATUS_CHOICES = [
        ('given',    'Given'),
        ('withheld', 'Withheld'),
        ('refused',  'Patient Refused'),
        ('missed',   'Missed'),
        ('late',     'Given Late'),
    ]

    shift_report    = models.ForeignKey(ShiftReport, on_delete=models.CASCADE,
                                         related_name='mar_entries',
                                         null=True, blank=True)
    patient         = models.ForeignKey('patients.Patient', on_delete=models.CASCADE,
                                         related_name='mar_records')
    administered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                         related_name='administered_medications')
    medication_name = models.CharField(max_length=200)
    dosage          = models.CharField(max_length=100)
    route           = models.CharField(max_length=50, blank=True,
                                       verbose_name="Route (oral/IV/IM/SC)")
    scheduled_time  = models.DateTimeField()
    given_time      = models.DateTimeField(null=True, blank=True)
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='given')
    reason_withheld = models.TextField(blank=True,
                                       verbose_name="Reason if Withheld/Refused/Missed")
    notes           = models.TextField(blank=True)

    class Meta:
        ordering = ['-scheduled_time']
        verbose_name = 'Medication Administration Record'

    def __str__(self):
        return (f"{self.medication_name} — {self.patient.full_name} "
                f"— {self.get_status_display()}")


# ─────────────────────────────────────────────────────────────────────
# NURSING NOTES
# ─────────────────────────────────────────────────────────────────────

class NursingNote(models.Model):
    """
    A clinical note written or voice-transcribed by a nurse.
    Voice notes are transcribed in the browser using the Web Speech API
    (no server-side processing needed, no API cost).
    """
    NOTE_TYPE_CHOICES = [
        ('observation',   'Clinical Observation'),
        ('procedure',     'Procedure Performed'),
        ('communication', 'Communication / Family Update'),
        ('handover',      'Handover Note'),
        ('incident',      'Incident Report'),
        ('general',       'General Note'),
    ]

    shift_report  = models.ForeignKey(ShiftReport, on_delete=models.CASCADE,
                                       related_name='notes', null=True, blank=True)
    patient       = models.ForeignKey('patients.Patient', on_delete=models.CASCADE,
                                       related_name='nursing_notes')
    written_by    = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                       related_name='nursing_notes')
    note_type     = models.CharField(max_length=20, choices=NOTE_TYPE_CHOICES,
                                     default='observation')
    content       = models.TextField(verbose_name="Note Content")
    was_voice     = models.BooleanField(default=False,
                                        verbose_name="Transcribed from voice")
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)
    is_flagged    = models.BooleanField(default=False,
                                        verbose_name="Flagged for doctor review")

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Nursing Note'

    def __str__(self):
        return (f"{self.get_note_type_display()} — "
                f"{self.patient.full_name} by {self.written_by}")


# ─────────────────────────────────────────────────────────────────────
# MATERIALS / CONSUMABLES USED
# ─────────────────────────────────────────────────────────────────────

class MaterialUsed(models.Model):
    """
    Records consumables and materials used during a shift.
    Useful for stock tracking and billing.
    """
    CATEGORY_CHOICES = [
        ('dressing',      'Dressing / Wound Care'),
        ('cannula',       'IV Cannula / Lines'),
        ('syringe',       'Syringe / Needle'),
        ('gloves',        'Gloves / PPE'),
        ('catheter',      'Catheter / Tubing'),
        ('bandage',       'Bandage / Gauze'),
        ('medication',    'Medication (unit used)'),
        ('oxygen',        'Oxygen (litres)'),
        ('blood',         'Blood / Blood Products'),
        ('other',         'Other'),
    ]

    shift_report  = models.ForeignKey(ShiftReport, on_delete=models.CASCADE,
                                       related_name='materials', null=True, blank=True)
    patient       = models.ForeignKey('patients.Patient', on_delete=models.CASCADE,
                                       related_name='materials_used',
                                       null=True, blank=True)
    recorded_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    category      = models.CharField(max_length=15, choices=CATEGORY_CHOICES)
    item_name     = models.CharField(max_length=200, verbose_name="Item / Material Name")
    quantity      = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    unit          = models.CharField(max_length=30, blank=True,
                                     verbose_name="Unit (pieces/ml/L/boxes)")
    notes         = models.CharField(max_length=300, blank=True)
    recorded_at   = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-recorded_at']
        verbose_name = 'Material Used'
        verbose_name_plural = 'Materials Used'

    def __str__(self):
        return f"{self.item_name} x{self.quantity} — {self.get_category_display()}"

# Create your models here.
