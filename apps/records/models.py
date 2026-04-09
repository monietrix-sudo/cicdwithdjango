"""
AbiCare - Medical Records Models
===================================
Supports:
- Version history on every edit (RecordVersion snapshots)
- Secure sharing with external hospitals (RecordShare with expiring token)
- Soft delete, file type detection
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()


def record_file_path(instance, filename):
    return (
        f"records/patient_{instance.patient.hospital_number}/"
        f"{timezone.now().strftime('%Y')}/{filename}"
    )


class MedicalRecord(models.Model):

    RECORD_TYPE_CHOICES = [
        ('consultation', 'Consultation Note'),
        ('diagnosis',    'Diagnosis'),
        ('prescription', 'Prescription'),
        ('referral',     'Referral Letter'),
        ('discharge',    'Discharge Summary'),
        ('imaging',      'Imaging Report'),
        ('surgical',     'Surgical Report'),
        ('nursing',      'Nursing Note'),
        ('other',        'Other'),
    ]

    patient     = models.ForeignKey('patients.Patient', on_delete=models.CASCADE, related_name='medical_records')
    record_type = models.CharField(max_length=20, choices=RECORD_TYPE_CHOICES, default='consultation')
    title       = models.CharField(max_length=300)
    body        = models.TextField(blank=True)

    attached_file = models.FileField(upload_to=record_file_path, null=True, blank=True)
    file_type     = models.CharField(max_length=20, blank=True)

    is_visible_to_patient  = models.BooleanField(default=False)
    is_downloadable        = models.BooleanField(
        default=False,
        verbose_name="Allow file download",
        help_text=(
            "If ticked, authorised users can download the attached file. "
            "Admin and the uploading doctor can always download regardless of this setting."
        )
    )

    # Soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='deleted_records')

    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                    related_name='uploaded_records')
    appointment = models.ForeignKey('appointments.Appointment', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='records')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    # Track version number for display
    version_number = models.PositiveIntegerField(default=1)

    def save(self, *args, **kwargs):
        if self.attached_file:
            name = self.attached_file.name.lower()
            if any(name.endswith(e) for e in ['.jpg','.jpeg','.png','.gif','.webp']):
                self.file_type = 'image'
            elif name.endswith('.pdf'):
                self.file_type = 'pdf'
            elif any(name.endswith(e) for e in ['.mp4','.webm','.ogg','.mov']):
                self.file_type = 'video'
            else:
                self.file_type = 'document'
        super().save(*args, **kwargs)

    def soft_delete(self, user):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save()

    def __str__(self):
        return f"[{self.get_record_type_display()}] {self.title} — {self.patient.hospital_number}"

    class Meta:
        verbose_name        = "Medical Record"
        verbose_name_plural = "Medical Records"
        ordering = ['-uploaded_at']


class RecordVersion(models.Model):
    """
    Snapshot of a MedicalRecord every time it is edited.
    Allows full version history and restoration.
    """
    record      = models.ForeignKey(MedicalRecord, on_delete=models.CASCADE, related_name='versions')
    version_num = models.PositiveIntegerField()

    # Snapshot of content at this version
    title       = models.CharField(max_length=300)
    body        = models.TextField(blank=True)
    record_type = models.CharField(max_length=20)
    is_visible_to_patient = models.BooleanField(default=False)

    # Who made the change and when
    edited_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                    related_name='record_versions')
    edited_at   = models.DateTimeField(auto_now_add=True)
    change_note = models.CharField(max_length=300, blank=True,
                                   help_text="Brief description of what changed.")

    class Meta:
        ordering = ['-version_num']
        verbose_name        = "Record Version"
        verbose_name_plural = "Record Versions"

    def __str__(self):
        return f"v{self.version_num} of Record #{self.record_id} by {self.edited_by}"


class RecordShare(models.Model):
    """
    Secure time-limited share link for sending records to external hospitals.
    No login required — access is via a unique token that expires in 48 hours.
    """
    token       = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    record      = models.ForeignKey(MedicalRecord, on_delete=models.CASCADE, related_name='shares')
    patient     = models.ForeignKey('patients.Patient', on_delete=models.CASCADE)

    # Referral target
    recipient_name    = models.CharField(max_length=200, help_text="Receiving hospital or doctor name")
    recipient_email   = models.EmailField(blank=True)
    purpose           = models.CharField(max_length=300, blank=True, help_text="Reason for sharing")

    shared_by   = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                                    related_name='shared_records')
    shared_at   = models.DateTimeField(auto_now_add=True)
    expires_at  = models.DateTimeField()
    is_revoked  = models.BooleanField(default=False)
    accessed_at = models.DateTimeField(null=True, blank=True)
    access_count= models.PositiveIntegerField(default=0)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_revoked and not self.is_expired

    def __str__(self):
        return f"Share of Record #{self.record_id} → {self.recipient_name} (expires {self.expires_at:%Y-%m-%d %H:%M})"

    class Meta:
        ordering = ['-shared_at']
        verbose_name        = "Record Share"
        verbose_name_plural = "Record Shares"