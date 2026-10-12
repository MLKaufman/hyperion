from django.urls import path
from portal import views, accounts

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.sign_in, name='login'),
    path('logout/', views.sign_out, name='logout'),
    path('password/', views.password_change, name='password_change'),
    path('admin/login/', views.sign_in),
    path('admin/', accounts.accounts, name='accounts'),
    path('admin/accounts/<uuid:pk>/', accounts.account_edit, name='account_edit'),
    path('admin/publication/<str:kind>/<uuid:pk>/', accounts.publication_update, name='publication_update'),
    path('admin/publication/<str:kind>/bulk/', accounts.publication_bulk, name='publication_bulk'),
    path('health/', views.health),
    path('refresh/', views.refresh, name='refresh'),
    path('projects/<uuid:pk>/', views.project_view, name='project'),
    path('projects/<uuid:pk>/download/', views.download_project, name='download_project'),
    path('deliverables/<uuid:pk>/launch/', views.launch, name='launch'),
    path('deliverables/<uuid:pk>/download/', views.download_zip, name='download_zip'),
    path('deliverables/<uuid:pk>/files/<path:path>', views.download_file, name='download_file'),
    path('content/launch/', views.redeem),
    path('content/<uuid:pk>/<path:path>', views.content),
]
