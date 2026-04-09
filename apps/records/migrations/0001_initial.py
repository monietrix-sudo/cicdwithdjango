"""
AbiCare Records — Initial Migration
Creates: MedicalRecord, RecordVersion, RecordShare
Includes is_downloadable field added in the last session.
"""
import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def record_file_path_placeholder(instance, filename):
    return f"records/{filename}"


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('patients', '__first__'),
        ('appointments', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        migrations.CreateModel(
            name='MedicalRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('record_type', models.CharField(
                    choices=[
                        ('consultation', 'Consultation Note'),
                        ('diagnosis',    'Diagnosis'),
                        ('prescription', 'Prescription'),
                        ('referral',     'Referral Letter'),
                        ('discharge',    'Discharge Summary'),
                        ('imaging',      'Imaging Report'),
                        ('surgical',     'Surgical Report'),
                        ('nursing',      'Nursing Note'),
                        ('other',        'Other'),
                    ],
                    default='consultation', max_length=20
                )),
                ('title',         models.CharField(max_length=300)),
                ('body',          models.TextField(blank=True)),
                ('attached_file', models.FileField(
                    blank=True, null=True,
                    upload_to='records/'  # actual callable in model.save()
                )),
                ('file_type',     models.CharField(blank=True, max_length=20)),
                ('is_visible_to_patient', models.BooleanField(default=False)),
                ('is_downloadable', models.BooleanField(
                    default=False,
                    verbose_name='Allow file download',
                    help_text=(
                        'If ticked, authorised users can download the attached file. '
                        'Admin and the uploading doctor can always download.'
                    )
                )),
                ('is_deleted', models.BooleanField(default=False)),
                ('deleted_at',   models.DateTimeField(blank=True, null=True)),
                ('uploaded_at',  models.DateTimeField(auto_now_add=True)),
                ('updated_at',   models.DateTimeField(auto_now=True)),
                ('version_number', models.PositiveIntegerField(default=1)),
                ('appointment', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='records',
                    to='appointments.appointment'
                )),
                ('deleted_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='deleted_records',
                    to=settings.AUTH_USER_MODEL
                )),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='medical_records',
                    to='patients.patient'
                )),
                ('uploaded_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='uploaded_records',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'verbose_name':        'Medical Record',
                'verbose_name_plural': 'Medical Records',
                'ordering':            ['-uploaded_at'],
            },
        ),

        migrations.CreateModel(
            name='RecordVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('version_num',             models.PositiveIntegerField()),
                ('title',                   models.CharField(max_length=300)),
                ('body',                    models.TextField(blank=True)),
                ('record_type',             models.CharField(max_length=20)),
                ('is_visible_to_patient',   models.BooleanField(default=False)),
                ('edited_at',               models.DateTimeField(auto_now_add=True)),
                ('change_note',             models.CharField(blank=True, max_length=300)),
                ('edited_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='record_versions',
                    to=settings.AUTH_USER_MODEL
                )),
                ('record', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='versions',
                    to='records.medicalrecord'
                )),
            ],
            options={
                'verbose_name':        'Record Version',
                'verbose_name_plural': 'Record Versions',
                'ordering':            ['-version_num'],
            },
        ),

        migrations.CreateModel(
            name='RecordShare',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('token',          models.UUIDField(default=uuid.uuid4, unique=True,
                                                    editable=False)),
                ('recipient_name', models.CharField(max_length=200)),
                ('recipient_email', models.EmailField(blank=True)),
                ('purpose',        models.CharField(blank=True, max_length=300)),
                ('shared_at',      models.DateTimeField(auto_now_add=True)),
                ('expires_at',     models.DateTimeField()),
                ('is_revoked',     models.BooleanField(default=False)),
                ('accessed_at',    models.DateTimeField(blank=True, null=True)),
                ('access_count',   models.PositiveIntegerField(default=0)),
                ('patient', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='patients.patient'
                )),
                ('record', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='shares',
                    to='records.medicalrecord'
                )),
                ('shared_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='shared_records',
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'verbose_name':        'Record Share',
                'verbose_name_plural': 'Record Shares',
                'ordering':            ['-shared_at'],
            },
        ),
    ]
