import time
from datetime import datetime, date
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.main import ChangeList
from panels.api import serializers
from panels.models import *
from panels.api.serializers import TrialSerializer
from panels.utils.plot.charts import Plotter, TableFormatter


plotter = Plotter()
table_formatter = TableFormatter()


def index(request, extra_context=None):
    print('Starting...')
    if extra_context is None:
        extra_context = {}
     
    extra_context['page_name'] = 'index'
    now = datetime.now()

    start =time.time()
    a = time.time()
    map_div, stat_countries, top_countries_div = plotter.build_map()
    extra_context['map'] = map_div
    extra_context['top_countries'] = top_countries_div
    print('Building map -> {:.3f}s'.format(time.time() - a))
    a = time.time()

    phase_div = plotter.build_phases()
    extra_context['phases'] = phase_div
    print('Building phases -> {:.3f}s'.format(time.time() - a))
    a = time.time()    

    status_div = plotter.build_status()
    extra_context['status'] = status_div
    print('Building status -> {:.3f}s'.format(time.time() - a))
    a = time.time()

    # recent_update_div = plotter.build_update_chart(now)
    # extra_context['recent_update'] = recent_update_div

    extra_context['stat_countries'] = stat_countries
    print('Building updates -> {:.3f}s'.format(time.time() - a))

    extra_context['stat_agents'] = '{:,}'.format(Agent.objects.all().count())
    extra_context['stat_drugs'] = '{:,}'.format(Agent.objects.filter(type=Agent.DRUG).count())
    extra_context['stat_trials'] = '{:,}'.format(Trial.objects.all().count())
    extra_context['current_year'] = now.year
    extra_context['drug_id'] = Agent.DRUG
    extra_context['stat_conditions'] = '{:,}'.format(Condition.objects.all().count())
    
    print('Total time -> {:.3f}'.format(time.time() - start))
    return render(request, 'panels/index.html', extra_context)


def change_list(request, extra_context=None):
    if extra_context is None:
        extra_context = {}

    extra_context['page_name'] = 'change_list'
    cl = ChangeList(request, model=Trial, 
        list_display=("__str__",),
        list_display_links=None,
        list_filter=None,
        date_hierarchy=None,
        search_fields=None,
        list_select_related=None,
        list_per_page=40,
        list_max_show_all=50,
        list_editable=None,
        model_admin=None,
        sortable_by=None,
        search_help_text=None,
        )
    extra_context['cl'] = cl

    return render(request, 'admin/change_list.html', extra_context)