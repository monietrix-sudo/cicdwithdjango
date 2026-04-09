"""
AbiCare - Medical Records Views
==================================
Supports: upload, view, soft-delete, version history, record sharing.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, StreamingHttpResponse, Http404
from django.utils import timezone
from datetime import timedelta
import mimetypes
import os

from .models import MedicalRecord, RecordVersion, RecordShare
from apps.patients.models import Patient
from apps.appointments.models import Appointment
from apps.audit_logs.utils import log_action


def _detect_file_type(filename):
    name = filename.lower()
    if any(name.endswith(e) for e in ['.jpg','.jpeg','.png','.gif','.webp']):
        return 'image'
    elif name.endswith('.pdf'):
        return 'pdf'
    elif any(name.endswith(e) for e in ['.mp4','.webm','.ogg','.mov']):
        return 'video'
    return 'document'


@login_required
def upload_record_view(request, hospital_number):
    patient      = get_object_or_404(Patient, hospital_number=hospital_number)
    appointments = Appointment.objects.filter(
        patient=patient
    ).order_by('-appointment_date')[:10]

    if request.method == 'POST':
        title       = request.POST.get('title', '').strip()
        record_type = request.POST.get('record_type', 'consultation')
        body        = request.POST.get('body', '').strip()
        visible      = 'is_visible_to_patient' in request.POST
        downloadable = 'is_downloadable' in request.POST
        appt_id     = request.POST.get('appointment_id')
        upload_mode = request.POST.get('upload_mode', 'text')  # text | image | pdf

        if not title:
            messages.error(request, "A title is required.")
            return redirect('records:upload', hospital_number=hospital_number)

        # ── Validate file size and type ───────────────────────────────
        file     = request.FILES.get('attached_file')
        max_size = 50 * 1024 * 1024  # 50 MB

        if file:
            if file.size > max_size:
                messages.error(request,
                    f"File too large ({file.size // 1024 // 1024} MB). Maximum is 50 MB.")
                return redirect('records:upload', hospital_number=hospital_number)

            fname = file.name.lower()
            if upload_mode == 'pdf' and not fname.endswith('.pdf'):
                messages.error(request,
                    "PDF mode selected but the uploaded file is not a PDF.")
                return redirect('records:upload', hospital_number=hospital_number)

            if upload_mode == 'image' and not any(
                fname.endswith(e) for e in ['.jpg','.jpeg','.png','.gif','.webp']
            ):
                messages.error(request,
                    "Image mode selected but the file is not a recognised image format.")
                return redirect('records:upload', hospital_number=hospital_number)

        # ── Create the record ─────────────────────────────────────────
        record = MedicalRecord(
            patient=patient,
            record_type=record_type,
            title=title,
            body=body,
            is_visible_to_patient=visible,
            is_downloadable=downloadable,
            uploaded_by=request.user,
        )
        if file:
            record.attached_file = file
        if appt_id:
            try:
                record.appointment_id = int(appt_id)
            except (ValueError, TypeError):
                pass

        record.save()

        # ── Auto-run OCR on PDF if requested ─────────────────────────
        auto_ocr = request.POST.get('auto_ocr') == '1'
        if auto_ocr and file and record.file_type in ('pdf', 'image'):
            try:
                extracted = _run_ocr(record)
                if extracted.strip():
                    record.body = (body + '\n\n' + extracted.strip()).strip()
                    record.save()
                    messages.info(request,
                        f"Text extracted from file automatically "
                        f"({len(extracted)} characters). Review below.")
            except ImportError:
                messages.warning(request,
                    "OCR is not installed on this server — text was not extracted. "
                    "Ask your administrator to install pytesseract.")
            except Exception as e:
                messages.warning(request, f"OCR failed: {e}")

        log_action(request.user, 'CREATE', request,
                   f"Uploaded {upload_mode} record '{title}' for {hospital_number}")
        messages.success(request,
            f"'{title}' saved successfully.")
        return redirect('records:detail', pk=record.pk)

    return render(request, 'records/upload_record.html', {
        'page_title':   'Upload Medical Record',
        'patient':      patient,
        'appointments': appointments,
        'record_types': MedicalRecord.RECORD_TYPE_CHOICES,
    })


@login_required
def record_detail_view(request, pk):
    record = get_object_or_404(MedicalRecord, pk=pk, is_deleted=False)

    if request.user.is_patient_user:
        if not hasattr(request.user, 'patient_profile') or \
           request.user.patient_profile != record.patient or \
           not record.is_visible_to_patient:
            messages.error(request, "Access denied.")
            return redirect('patients:dashboard')

    shares   = RecordShare.objects.filter(record=record).order_by('-shared_at')
    versions = RecordVersion.objects.filter(record=record)
    log_action(request.user, 'VIEW', request, f"Viewed record #{pk}: {record.title}")

    # ── Download permission ───────────────────────────────────────────
    # Mirrors the logic in download_record_file_view so the button only
    # appears when the download would actually succeed.
    user = request.user
    can_download = False
    if record.attached_file:
        if user.is_superuser or user.is_admin_staff:
            can_download = True
        elif user.role == 'doctor' and record.uploaded_by == user:
            can_download = True
        elif user.is_patient_user:
            if (hasattr(user, 'patient_profile')
                    and user.patient_profile == record.patient
                    and record.is_visible_to_patient
                    and record.is_downloadable):
                can_download = True
        elif record.is_downloadable:
            can_download = True

    return render(request, 'records/record_detail.html', {
        'page_title':   record.title,
        'record':       record,
        'shares':       shares,
        'versions':     versions,
        'can_download': can_download,
    })


@login_required
def edit_record_view(request, pk):
    """Edit a record — saves a version snapshot before updating."""
    record = get_object_or_404(MedicalRecord, pk=pk, is_deleted=False)

    if not (request.user.is_admin_staff or request.user.is_doctor or
            request.user == record.uploaded_by):
        messages.error(request, "You don't have permission to edit this record.")
        return redirect('records:detail', pk=pk)

    if request.method == 'POST':
        change_note = request.POST.get('change_note', '').strip()

        # Save current state as a version snapshot BEFORE making changes
        RecordVersion.objects.create(
            record=record,
            version_num=record.version_number,
            title=record.title,
            body=record.body,
            record_type=record.record_type,
            is_visible_to_patient=record.is_visible_to_patient,
            edited_by=request.user,
            change_note=change_note or "Edited",
        )

        # Apply changes
        record.title       = request.POST.get('title', record.title).strip()
        record.body        = request.POST.get('body', record.body).strip()
        record.record_type = request.POST.get('record_type', record.record_type)
        record.is_visible_to_patient = 'is_visible_to_patient' in request.POST
        record.is_downloadable       = 'is_downloadable' in request.POST
        record.version_number += 1

        if 'attached_file' in request.FILES:
            record.attached_file = request.FILES['attached_file']

        record.save()
        log_action(request.user, 'UPDATE', request,
                   f"Edited record #{pk} (now v{record.version_number}): {change_note}")
        messages.success(request, f"Record updated. Version {record.version_number} saved.")
        return redirect('records:detail', pk=pk)

    return render(request, 'records/edit_record.html', {
        'page_title':   f"Edit: {record.title}",
        'record':       record,
        'record_types': MedicalRecord.RECORD_TYPE_CHOICES,
    })


@login_required
def version_history_view(request, pk):
    """Show all historical versions of a record."""
    record   = get_object_or_404(MedicalRecord, pk=pk, is_deleted=False)
    versions = RecordVersion.objects.filter(record=record)

    return render(request, 'records/version_history.html', {
        'page_title': f"History — {record.title}",
        'record':     record,
        'versions':   versions,
    })


@login_required
def restore_version_view(request, pk, version_num):
    """Restore a record to a specific previous version."""
    record  = get_object_or_404(MedicalRecord, pk=pk, is_deleted=False)
    version = get_object_or_404(RecordVersion, record=record, version_num=version_num)

    if not (request.user.is_admin_staff or request.user.is_doctor):
        messages.error(request, "Only doctors and admins can restore versions.")
        return redirect('records:history', pk=pk)

    if request.method == 'POST':
        # Save current state first
        RecordVersion.objects.create(
            record=record,
            version_num=record.version_number,
            title=record.title,
            body=record.body,
            record_type=record.record_type,
            is_visible_to_patient=record.is_visible_to_patient,
            edited_by=request.user,
            change_note=f"Restored to version {version_num}",
        )
        # Apply the old version
        record.title                  = version.title
        record.body                   = version.body
        record.record_type            = version.record_type
        record.is_visible_to_patient  = version.is_visible_to_patient
        record.version_number        += 1
        record.save()

        log_action(request.user, 'UPDATE', request,
                   f"Restored record #{pk} to v{version_num}")
        messages.success(request, f"Record restored to version {version_num}.")
        return redirect('records:detail', pk=pk)

    return render(request, 'records/restore_confirm.html', {
        'record':  record,
        'version': version,
    })


@login_required
def share_record_view(request, pk):
    """Create a secure share link for an external hospital."""
    record = get_object_or_404(MedicalRecord, pk=pk, is_deleted=False)

    if not (request.user.is_admin_staff or request.user.is_doctor):
        messages.error(request, "Only doctors and admins can share records.")
        return redirect('records:detail', pk=pk)

    if request.method == 'POST':
        from django.core.mail import send_mail
        from django.conf import settings

        recipient_name  = request.POST.get('recipient_name', '').strip()
        recipient_email = request.POST.get('recipient_email', '').strip()
        purpose         = request.POST.get('purpose', '').strip()
        hours           = int(request.POST.get('expires_hours', 48))

        if not recipient_name:
            messages.error(request, "Recipient name is required.")
            return redirect('records:share', pk=pk)

        share = RecordShare.objects.create(
            record=record,
            patient=record.patient,
            recipient_name=recipient_name,
            recipient_email=recipient_email,
            purpose=purpose,
            shared_by=request.user,
            expires_at=timezone.now() + timedelta(hours=hours),
        )

        share_url = request.build_absolute_uri(f'/records/shared/{share.token}/')

        # Send email if address provided
        if recipient_email:
            try:
                send_mail(
                    subject=f"Medical Record Shared — {settings.HOSPITAL_NAME}",
                    message=(
                        f"Dear {recipient_name},\n\n"
                        f"A medical record has been shared with you by "
                        f"Dr. {request.user.get_full_name()} from {settings.HOSPITAL_NAME}.\n\n"
                        f"Patient: {record.patient.full_name}\n"
                        f"Record: {record.title}\n"
                        f"Purpose: {purpose or 'Referral'}\n\n"
                        f"Access the record here (expires in {hours} hours):\n{share_url}\n\n"
                        f"This link will expire on {share.expires_at.strftime('%B %d, %Y at %H:%M')}.\n"
                        f"Do not share this link with anyone else.\n\n"
                        f"— {settings.HOSPITAL_NAME}"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[recipient_email],
                    fail_silently=True,
                )
                messages.success(request,
                    f"Record shared. Link sent to {recipient_email}. Expires in {hours} hours.")
            except Exception:
                messages.success(request,
                    f"Share link created (email failed to send). Copy the link manually.")
        else:
            messages.success(request, f"Share link created. Expires in {hours} hours.")

        log_action(request.user, 'APPROVE', request,
                   f"Shared record #{pk} with {recipient_name} ({recipient_email})")
        return redirect('records:detail', pk=pk)

    return render(request, 'records/share_record.html', {
        'page_title': f"Share Record — {record.title}",
        'record':     record,
    })


def shared_record_view(request, token):
    """Public view — no login required. Validates token and shows record."""
    share = get_object_or_404(RecordShare, token=token)

    if share.is_revoked:
        return render(request, 'records/share_expired.html',
                      {'reason': 'This link has been revoked.'})
    if share.is_expired:
        return render(request, 'records/share_expired.html',
                      {'reason': 'This link has expired.'})

    # Log access
    share.access_count += 1
    share.accessed_at   = timezone.now()
    share.save()

    return render(request, 'records/shared_record_view.html', {
        'share':  share,
        'record': share.record,
    })


@login_required
def revoke_share_view(request, share_pk):
    share = get_object_or_404(RecordShare, pk=share_pk)
    if not (request.user.is_admin_staff or request.user == share.shared_by):
        messages.error(request, "Permission denied.")
        return redirect('records:detail', pk=share.record_id)
    share.is_revoked = True
    share.save()
    log_action(request.user, 'REVOKE', request, f"Revoked share #{share_pk}")
    messages.success(request, "Share link revoked.")
    return redirect('records:detail', pk=share.record_id)


@login_required
def delete_record_view(request, pk):
    record = get_object_or_404(MedicalRecord, pk=pk)
    if request.method == 'POST':
        record.soft_delete(request.user)
        log_action(request.user, 'DELETE', request, f"Archived record #{pk}: {record.title}")
        messages.success(request, "Record archived.")
        return redirect('patient_detail:detail', hospital_number=record.patient.hospital_number)
    return redirect('records:detail', pk=pk)


@login_required
def records_list_view(request):
    record_type_filter = request.GET.get('record_type', '')
    records = MedicalRecord.objects.filter(is_deleted=False).select_related('patient','uploaded_by')
    if record_type_filter:
        records = records.filter(record_type=record_type_filter)
    return render(request, 'records/records_list.html', {
        'page_title':  'Medical Records',
        'records':     records[:100],
        'record_types': MedicalRecord.RECORD_TYPE_CHOICES,
        'type_filter': record_type_filter,
    })


# ─────────────────────────────────────────────────────────────────────
# OCR — Extract text from uploaded scanned PDF or image
# ─────────────────────────────────────────────────────────────────────
@login_required
def ocr_extract_view(request, pk):
    """
    Run OCR on a record's attached file and populate the body field.
    Supports: scanned PDFs and images (JPG/PNG/GIF/WEBP).
    Uses Tesseract (free, local, no API limits).
    """
    record = get_object_or_404(MedicalRecord, pk=pk, is_deleted=False)

    if not record.attached_file:
        messages.error(request, "No file attached to this record.")
        return redirect('records:detail', pk=pk)

    if not (request.user.is_admin_staff or request.user.is_doctor or
            request.user.is_nurse or request.user == record.uploaded_by):
        messages.error(request, "Permission denied.")
        return redirect('records:detail', pk=pk)

    try:
        extracted = _run_ocr(record)
        if extracted.strip():
            # Save a version snapshot before overwriting
            RecordVersion.objects.create(
                record=record,
                version_num=record.version_number,
                title=record.title,
                body=record.body,
                record_type=record.record_type,
                is_visible_to_patient=record.is_visible_to_patient,
                edited_by=request.user,
                change_note="OCR text extraction",
            )
            record.body = extracted.strip()
            record.version_number += 1
            record.save()
            log_action(request.user, 'UPDATE', request,
                       f"OCR extracted {len(extracted)} chars from record #{pk}")
            messages.success(request,
                f"Text extracted successfully ({len(extracted)} characters). "
                f"Review and edit as needed.")
        else:
            messages.warning(request,
                "OCR ran but found no readable text. "
                "The document may be a non-text image or low quality scan.")
    except ImportError:
        messages.error(request,
            "OCR requires pytesseract and Tesseract to be installed. "
            "Run: pip install pytesseract Pillow pdf2image "
            "and install Tesseract from https://tesseract-ocr.github.io/")
    except Exception as e:
        messages.error(request, f"OCR failed: {str(e)}")

    return redirect('records:detail', pk=pk)


def _run_ocr(record):
    """
    Extract text from a file using Tesseract OCR.
    Handles both images and PDFs.
    """
    import pytesseract
    from PIL import Image
    import os

    file_path = record.attached_file.path
    file_type = record.file_type

    if file_type == 'image':
        img  = Image.open(file_path)
        text = pytesseract.image_to_string(img)
        return text

    elif file_type == 'pdf':
        # Convert PDF pages to images then OCR each page
        from pdf2image import convert_from_path
        pages = convert_from_path(file_path, dpi=200)
        text_parts = []
        for i, page in enumerate(pages):
            page_text = pytesseract.image_to_string(page)
            if page_text.strip():
                text_parts.append(f"--- Page {i+1} ---\n{page_text}")
        return '\n\n'.join(text_parts)

    else:
        raise ValueError(f"OCR is only supported for images and PDFs, not '{file_type}'.")


@login_required
def ocr_guide_view(request):
    """Explains how to install and use OCR scanning in AbiCare."""
    file_type_status = [
        ('Scanned PDF (e.g. referral letter)',     'fa-file-pdf',   True),
        ('Photo / Image (JPG, PNG)',               'fa-image',      True),
        ('Typed Word document (.docx)',            'fa-file-word',  False),
        ('Plain text file (.txt)',                 'fa-file-alt',   False),
        ('Excel spreadsheet',                     'fa-file-excel', False),
        ('Already-digital PDF (not scanned)',     'fa-file-pdf',   False),
    ]
    return render(request, 'records/ocr_guide.html', {
        'page_title':       'OCR Scanning Setup Guide',
        'file_type_status': file_type_status,
    })


# ─────────────────────────────────────────────────────────────────────────────
# FILE DOWNLOAD VIEW — permission-controlled
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def download_record_file_view(request, pk):
    """
    Download the attached file from a medical record.

    Permission rules:
      - Admin and superuser: always allowed
      - Doctor who uploaded the record: always allowed
      - Other staff (nurses, receptionists, lab techs): allowed only if is_downloadable=True
      - Patient: allowed only if record is_visible_to_patient=True AND is_downloadable=True

    The file is served as an attachment (forces browser download dialog).
    For object storage backends (S3/R2/Azure), the user is redirected to a
    time-limited signed URL — no file bytes pass through Django.
    For local storage, Django streams the file directly.
    """
    record = get_object_or_404(MedicalRecord, pk=pk, is_deleted=False)

    # ── Permission check ──────────────────────────────────────────────
    user = request.user

    # No file attached at all
    if not record.attached_file:
        messages.error(request, "This record has no attached file.")
        return redirect('records:detail', pk=pk)

    # Determine if this user may download
    can_download = False

    if user.is_superuser or user.is_admin_staff:
        can_download = True

    elif user.role == 'doctor' and record.uploaded_by == user:
        can_download = True   # uploader always can download their own

    elif user.is_patient_user:
        # Patient: needs both flags
        if (hasattr(user, 'patient_profile')
                and user.patient_profile == record.patient
                and record.is_visible_to_patient
                and record.is_downloadable):
            can_download = True

    elif record.is_downloadable:
        # Any other logged-in staff: needs is_downloadable flag
        can_download = True

    if not can_download:
        messages.error(
            request,
            "You do not have permission to download this file. "
            "Contact the doctor or administrator to enable downloads for this record."
        )
        return redirect('records:detail', pk=pk)

    # ── Serve the file ────────────────────────────────────────────────
    log_action(user, 'DOWNLOAD', request,
               f"Downloaded file from record #{pk} — {record.title}")

    storage = record.attached_file.storage

    # Object storage (S3/R2/Azure): generate a signed URL and redirect.
    # The file bytes go directly from the bucket to the user's browser —
    # they never pass through Django, so no memory pressure.
    if hasattr(storage, 'url') and not _is_local_storage(storage):
        try:
            signed_url = record.attached_file.url
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(signed_url)
        except Exception as e:
            messages.error(request, f"Could not generate download link: {e}")
            return redirect('records:detail', pk=pk)

    # Local storage: stream the file through Django
    try:
        file_path = record.attached_file.path
    except NotImplementedError:
        # Some backends don't support .path — redirect to URL instead
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(record.attached_file.url)

    if not os.path.exists(file_path):
        messages.error(request,
            "The file could not be found on the server. "
            "It may have been moved or deleted.")
        return redirect('records:detail', pk=pk)

    # Detect content type
    content_type, _encoding = mimetypes.guess_type(file_path)
    content_type = content_type or 'application/octet-stream'

    # Stream the file in chunks — safe for large PDFs
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    def file_iterator(path, chunk_size=65536):
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    response = StreamingHttpResponse(
        file_iterator(file_path),
        content_type=content_type,
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Content-Length']      = file_size
    response['X-Content-Type-Options'] = 'nosniff'   # security header
    return response


def _is_local_storage(storage):
    """True if the storage backend is local disk (not S3/Azure/etc.)."""
    from django.core.files.storage import FileSystemStorage
    return isinstance(storage, FileSystemStorage)