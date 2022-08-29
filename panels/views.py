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
    return render(request, 'panels/index.html', extra_context)