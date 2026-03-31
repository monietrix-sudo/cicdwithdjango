from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.views.generic import RedirectView


def robots_txt(request):
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")


urlpatterns = [
    path('robots.txt', robots_txt, name='robots_txt'),
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/dashboard/', permanent=False)),
    path('accounts/',     include('apps.accounts.urls',     namespace='accounts')),
    path('dashboard/',    include('apps.patients.urls',     namespace='patients')),
    path('patients/',     include('apps.patients.urls_patient', namespace='patient_detail')),
    path('appointments/', include('apps.appointments.urls', namespace='appointments')),
    path('lab-results/',  include('apps.lab_results.urls',  namespace='lab_results')),
    path('medications/',  include('apps.medications.urls',  namespace='medications')),
    path('teleconsult/',  include('apps.teleconsult.urls',  namespace='teleconsult')),
    path('records/',      include('apps.records.urls',      namespace='records')),
    path('audit/',        include('apps.audit_logs.urls',   namespace='audit_logs')),
    path('notifications/',include('apps.notifications.urls',namespace='notifications')),
    path('queue/',        include('apps.queue.urls',        namespace='queue')),
    path('portal/',         include('apps.portal.urls',        namespace='portal')),
    path('clinical/',       include('apps.clinical_records.urls', namespace='clinical_records')),
    path('billing/',        include('apps.billing.urls',        namespace='billing')),
    path('',                include('apps.role_portals.urls',   namespace='role_portals')),
    path('families/',     include('apps.families.urls',     namespace='families')),
    path('nursing/',     include('apps.nursing.urls',     namespace='nursing')),
    path('imports/',      include('apps.imports.urls',      namespace='imports')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

admin.site.site_header = f"{settings.HOSPITAL_NAME} Administration"
admin.site.site_title  = f"{settings.HOSPITAL_NAME} Admin"
admin.site.index_title = "Hospital Management Dashboard"
