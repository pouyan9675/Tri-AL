from django.urls import path, include
from django.contrib import admin
from panels import views
from panels.admin import my_site


admin.site.site_header = "Tri-AL: VisuAL ClinicAL TriALs"
admin.site.site_title = 'Tri-AL Admin Page'
admin.site.index_title = 'Tri-AL administration'


urlpatterns = [
    path('', views.index, name='index'),
    path('api/', include('panels.api.urls')),
    path('admin/', my_site.urls),
]