from django.urls import path
from . import views

app_name = 'nursing'

urlpatterns = [
    # Dashboard
    path('',
         views.nursing_dashboard_view,
         name='dashboard'),

    # Shift reports
    path('shifts/',
         views.shift_report_list_view,
         name='shift_list'),
    path('shifts/start/',
         views.start_shift_report_view,
         name='start_shift'),
    path('shifts/<int:pk>/',
         views.shift_report_detail_view,
         name='shift_report_detail'),
    path('shifts/<int:pk>/submit/',
         views.submit_shift_report_view,
         name='submit_shift'),
    path('shifts/<int:pk>/handover/',
         views.handover_view,
         name='handover'),

    # AJAX save endpoints (POST only)
    path('shifts/<int:report_pk>/vitals/',
         views.add_vitals_view,
         name='add_vitals'),
    path('shifts/<int:report_pk>/note/',
         views.add_note_view,
         name='add_note'),
    path('shifts/<int:report_pk>/mar/',
         views.add_mar_view,
         name='add_mar'),
    path('shifts/<int:report_pk>/material/',
         views.add_material_view,
         name='add_material'),

    # Patient vitals quick view
    path('vitals/<str:hospital_number>/',
         views.patient_vitals_view,
         name='patient_vitals'),

    # Duty rosters
    path('rosters/',
         views.roster_list_view,
         name='roster_list'),
    path('rosters/create/',
         views.create_roster_view,
         name='create_roster'),
    path('rosters/<int:pk>/',
         views.roster_detail_view,
         name='roster_detail'),
    path('rosters/<int:roster_pk>/add-entry/',
         views.add_roster_entry_view,
         name='add_roster_entry'),
    path('rosters/<int:pk>/confirm/',
         views.confirm_and_distribute_roster_view,
         name='confirm_roster'),
]