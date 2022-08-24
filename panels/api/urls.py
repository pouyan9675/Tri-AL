from django.urls import path
from panels import views
from panels.api import rest_views

urlpatterns = [
    path('/', views.index, name='index'),
    path('all/', rest_views.all_trials, name='all_trials'),
    
    path('trial/nct/<nct_id>', rest_views.get_nct, name='get_nct'),
    path('trial/phase/<phases>', rest_views.get_phase, name='get_phase'),
    path('trial/filter/', rest_views.filter_trial, name='filter_trial'),
    path('trial/biomarker/excel', rest_views.biomarker_excel, name='biomarker_excel'),
    path('trial/map/', rest_views.get_countries, name='get_countries'),
    path('pipeline/<int:year>', rest_views.pipeline_excel, name='pipeline_excel'),
    path('agent/filter/<agent_name>', rest_views.filter_agent, name='filter_agent'),
    path('publication/', rest_views.get_publications, name='get_publications'),
    path('publication/<int:page>', rest_views.get_publications, name='get_publications'),
]