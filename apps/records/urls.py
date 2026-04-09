from django.urls import path
from . import views
app_name = 'records'
urlpatterns = [
    path('',                                    views.records_list_view,       name='list'),
    path('upload/<str:hospital_number>/',       views.upload_record_view,      name='upload'),
    path('<int:pk>/',                           views.record_detail_view,       name='detail'),
    path('<int:pk>/edit/',                      views.edit_record_view,         name='edit'),
    path('<int:pk>/delete/',                    views.delete_record_view,       name='delete'),
    path('<int:pk>/history/',                   views.version_history_view,     name='history'),
    path('<int:pk>/restore/<int:version_num>/', views.restore_version_view,     name='restore'),
    path('<int:pk>/share/',                     views.share_record_view,        name='share'),
    path('shared/<uuid:token>/',                views.shared_record_view,       name='shared'),
    path('share/<int:share_pk>/revoke/',        views.revoke_share_view,        name='revoke_share'),
    path('ocr-guide/', views.ocr_guide_view, name='ocr_guide'),
    path('<int:pk>/ocr/',                        views.ocr_extract_view,         name='ocr'),
    path('<int:pk>/download/',                   views.download_record_file_view, name='download'),
]
