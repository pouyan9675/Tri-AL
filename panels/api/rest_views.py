import json
import pandas as pd
from io import BytesIO
from collections import defaultdict
from pycountry import countries
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.exceptions import server_error
from panels.models import *
from panels.utils.pipeline import Pipeline
from panels.utils.pipeline import export_pipeline
from panels.api.serializers import *


@csrf_exempt
def all_trials(request):
    """
        Using this api function the client will be able to get all trials 
        with their properties. This function will be triggered by GET request.
    """
    trials = Trial.objects.all()

    if request.method == 'GET':
        serializer = TrialSerializer(trials, many=True)
        return JsonResponse(serializer.data, safe=False)


@csrf_exempt
def get_nct(request, nct_id):
    """
        An api function to get a specific trial by its NCT id and send it
        through Json format.

        Parameters
        ===================
        + nct_id : The string of NCT number
    """

    try:
        trial = Trial.objects.get(nct_id=nct_id)

    except Trial.DoesNotExist:
        return HttpResponse(status=404)

    if request.method == 'GET':
        serializer = TrialSerializer(trial)
        return JsonResponse(serializer.data)


@csrf_exempt
def filter_trial(request):
    """
        An API to apply different pre defined filters and choose trials
        with declared filter and send it as Json to client. This function
        will be triggered by a POST request.

        Parameters
        ===================
        + request : The request object of Django contaning all filters
    """

    m2m = {'cadro_moa_cat'      :   MoaCadro,
            'moa_subcat'        :   MoaCategory,
            'geography'         :   Geography,
            'subject_charac'    :   SubjectCharacteristic, 
            'biomarker'         :   Biomarker,
            'sponsor'           :   Sponser,
    }

    date = ['start_date', 'primary_completion']

    single = ['phase', 'status', 'location', 'moa_class', 
            'repurposed',
    ]

    if request.method == 'POST':

        if len(request.body) == 0:
            return HttpResponse("You have to send the data by JSON", status=400)

        try:
            data = json.loads(request.body)
            filters = {}

            for k,v in data.items():
                if not isinstance(v, list):
                    continue
                elif len(v) < 1:
                    continue

                if ('0' not in v and 0 not in v) and ('XX' not in v) and k.lower() in single:
                    filters[k.lower()+'__in'] = v
                elif k.lower() in date:
                    filters[k.lower()+'__range'] = v
                elif k.lower() in m2m.keys():
                    ids = []
                    for e in v:
                        try:
                            ids.append(m2m[k.lower()].objects.get(name=e).pk)
                        except m2m[k.lower()].DoesNotExist:
                            continue
                    filters[k.lower()+'__in'] = ids

            trials = Trial.objects.exclude(moa_class__isnull=True).filter(**filters)
            # TODO: remove private records

        except:
            return HttpResponse("Invalid JSON Format", status=400)
        
        serializer = TrialSerializer(trials, many=True)
        return JsonResponse(serializer.data, safe=False)



@csrf_exempt
def filter_agent(request, agent_name):
    """
        An API to find and send the trials that contains a specific agent (drug)

        Parameters
        ===================
        + agent_name : A string of agent name
    """
    if request.method == 'GET':
        
        try:
            a_id = Agent.objects.get(name=agent_name)
        except:
            return HttpResponse("Agent not found", status=404)
        
        trials = Trial.objects.filter(agent=a_id)
        
        serializer = TrialSerializer(trials, many=True)
        return JsonResponse(serializer.data, safe=False)



@csrf_exempt
def get_phase(request, phases):
    """
        An api function in order to get all trials by declared phases.
        For example in order to get trials with phase of Phase 1 or 
        Phase 1|Phase 2 or Phase 2|Phase 3, we can send the the following
        string through GET request.
        Phases: 1&12&23

        Parameters
        ===================
        + phases : A list of phases separated with &         
    """
    try:
        trials = None
        phases = phases.split('&')
        for p in phases:
            print(p)
            t = Trial.objects.filter(phase=p)
            if trials:
                trials = trials | t
            else:
                trials = t
    except Trial.DoesNotExist:
        return HttpResponse(status=404)

    if request.method == 'GET':
        trials = trials.distinct()
        serializer = TrialSerializer(trials, many=True)
        return JsonResponse(serializer.data, safe=False)


@csrf_exempt
def get_countries(request):
    studies = defaultdict(int)
    locations = Trial.objects.values_list('location_str')
    for l in locations:
        l = l[0]
        l = [x for x in l.split('\n') if x != '']
        tmp = set()
        for site in l:
            site = site.split(',')
            if 'republic of' in site[-1].strip().lower():
                tmp.add(','.join(site[-2:]).strip())
            elif 'Taiwan' == site[-1].strip():
                tmp.add('Taiwan, Province of China')
            elif 'Czech Republic' == site[-1]:
                tmp.add('Czechia')
            else:
                tmp.add(site[-1].strip())

        for country in tmp:
            studies[country] += 1

    response = {
        'Countries': dict(studies),
        'Total' : sum([s for s in studies.values()]),
        }
    

    return JsonResponse(response)


@csrf_exempt
def biomarker_excel(request):
    """
        Makes an excel file containing NCT ID and outcome measure
        along with its biomarkers.    
    """
    data = Trial.objects.all()

    serializer = BiomarkerExcelSerializer(data, many=True)

    df = pd.DataFrame(serializer.data)
    df['biomarker_outcome'] = df['biomarker_outcome'].apply(lambda x: [dict(b) for b in x])
    df['biomarker_entry'] = df['biomarker_entry'].apply(lambda x: [dict(b) for b in x])

    memory = BytesIO()
    df.to_excel(memory)
    memory.seek(0,0)

    return HttpResponse(memory, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@csrf_exempt
def pipeline_excel(request, year):
    """
        Makes an excel file containing given year pipeline   
    """
    # pipeline = Pipeline(year=year)

    # serializer = PipeLineSerializer(pipeline.all_trials(), many=True)

    # df = pd.DataFrame(serializer.data)

    excel = export_pipeline(year)

    memory = BytesIO()
    excel.to_excel(memory)
    memory.seek(0,0)

    response = HttpResponse(memory, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=Pipeline-%s.xlsx' % (year)
    return response


@csrf_exempt
def get_publications(request, page=1):
    """
        Returns the publications as JSON format orderd by year and alphabetic order
    """
    if request.method == 'GET':
        publications = Publication.objects.all().order_by('-year','title')
        paginator = Paginator(publications, 8)
        if page > paginator.num_pages:
            return HttpResponse("Invalid page number", status=404)
        serializer = PublicationSerializer(paginator.page(page), many=True)
        result = {
            'meta': {'current_page' : page, 'max_page' : paginator.num_pages},
            'result' : serializer.data,
        }
        return JsonResponse(result, safe=False)