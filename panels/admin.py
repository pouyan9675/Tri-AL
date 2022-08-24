from base64 import decode
from secrets import choice
from attr import attr
from django import forms
from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from django.template.response import HttpResponse
from django.utils.html import mark_safe
from django.urls import path
from django.core.paginator import Paginator
from pytest import param
from simple_history.admin import SimpleHistoryAdmin
from django.shortcuts import render, redirect
from sqlalchemy import desc

from panels.models import *
from panels.forms import AdvancedSearchForm, TrialForm
from panels.utils.pipeline import Pipeline
from panels.utils.notification import notification
from django.contrib.admin import widgets
from panels.widgets import DateRangePicker, AutocompleteSelectMultiple

import pandas as pd
from daterangefilter.filters import DateRangeFilter
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from .utils.plot.charts import Plotter, TableFormatter


STRING_CAPPING_LENGHT = 47
PAGE_ROWS = 25


class MyAdminSite(admin.sites.AdminSite):

    def __init__(self, *args, **kwargs):
        super(MyAdminSite, self).__init__(*args, **kwargs)

        self.plotter = Plotter()
        self.table_formatter = TableFormatter()


    def get_urls(self):
        urls = super(MyAdminSite, self).get_urls()
        custom_urls = [
            path('newsletter/', self.admin_view(self.newsletter), name="newsletter"),
            path('newsletter/save', self.admin_view(self.newsletter_save), name="news_publish"),
            path('advanced/', self.admin_view(self.advanced_search), name="advanced_search"),
            path('ajax/search/', self.ajax_search, name="ajax_search"),
        ]
        return custom_urls + urls


    def pipeline_view(self, request):
        request.current_app = self.name

        year = 2022

        context = {}

        pipeline = Pipeline(year=year)

        context['page_name'] = 'pipeline'
        context['is_nav_sidebar_enabled'] = True
        context['available_apps'] = self.get_app_list(request)

        context['status_summary'] = self.table_formatter.status_summary(pipeline.all_trials_no_filter(), year)
        context['trials_summary'] = self.table_formatter.pipeline_summary(pipeline.all_trials(), year)
        context['agents_summary'] = self.table_formatter.agent_summary(pipeline.all_trials(), year)

        phase3, phase3_dmt = pipeline.phase_MoA(phase_n=3)
        context['phase3moa'] = self.plotter.build_phase_dmt(phase3, phase3_dmt, 3)
        phase2, phase2_dmt = pipeline.phase_MoA(phase_n=2)
        context['phase2moa'] = self.plotter.build_phase_dmt(phase2, phase2_dmt, 2)

        context['phase3agents'] = self.table_formatter.draw_trial_table(pipeline.get_agent_phase(3))
        context['phase2agents'] = self.table_formatter.draw_trial_table(pipeline.get_agent_phase(2))
        context['phase1agents'] = self.table_formatter.draw_trial_table(pipeline.get_agent_phase(1))
        context['stemcell_trials'] = self.table_formatter.draw_trial_table(pipeline.get_stem_cells())

        context['location'] = self.table_formatter.draw_distribution(pipeline.all_trials())
        context['sponsor'] = self.table_formatter.draw_sponsor(pipeline.all_trials())
        context['biomarkers'] = self.table_formatter.draw_biomarkers(pipeline.get_dmt_phase23())
        context['participants'] = self.table_formatter.draw_participant(pipeline.all_trials())
        context['dmt_cadro'] = self.plotter.dmt_cadro_bar(pipeline.all_dmt())



        pipeline_trials = pipeline.all_trials()
        context['current_year'] = year
        context['stat_new_trials'] = pipeline_trials.filter(first_posted__year=year-1).count()

        context['pipeline_new'] = context['stat_new_trials']
        context['pipeline_last'] = pipeline_trials.count() - context['pipeline_new']

        context['pipeline_total'] = pipeline_trials.count()
        context['pipeline_completed'] = pipeline.all_trials_no_filter().filter(first_posted__year__lt=year, status='C').count()
        context['pipeline_ongoing'] = pipeline_trials.filter(status__in=['A','E','N','R']).count()
        context['pipeline_current_completed'] = Trial.objects.filter(last_update__year=year-1)          \
                                                        .exclude(first_posted__year=year-1)             \
                                                        .filter(status='C')                           \
                                                        .count()

        return HttpResponse(render(request, 'admin/pipeline.html', context))



    def newsletter(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}

        context = {
            **self.each_context(request),
            'page_name': 'newsletter',
            **(extra_context or {}),
        }
        return HttpResponse(render(request, 'admin/newsletter.html', context))


    def newsletter_save(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}


        if request.method == 'POST':
            post = request.POST
            content = post.get('newslettercontent', None)
            text = post.get('textcontent', None)

            if post.get("action","") == 'publish':
                try:
                    notif = notification.NewsletterNotification()
                    context = {
                        'content' : content,
                    }
                    with notif:
                        notif.broadcast(context)
                    n = Newsletter(content=content,
                    text=text,
                    is_published=True,
                    posted_on=date.today(),)
                    n.save()

                    extra_context['type'] = 'success'
                    extra_context['message'] = 'News published successfully!'
                    context = {
                        **self.each_context(request),
                        **(extra_context or {}),
                    }
                    return self.message(request, context)

                except:
                    extra_context['type'] = 'error'
                    extra_context['message'] = 'Publishing message has been failed!'
                    context = {
                        **self.each_context(request),
                        **(extra_context or {}),
                    }
                    return self.message(request, context)
            

            elif post.get("action","") == 'draft':
                n = Newsletter(content=content,
                    text=text,
                    is_published=False,)
                n.save()
                
                extra_context['type'] = 'success'
                extra_context['message'] = 'News drafted successfully!'
                context = {
                    **self.each_context(request),
                    **(extra_context or {}),
                }
                return self.message(request, context)
            else:
                return redirect('/')
        else:
            return redirect('/')


    def message(self, request, extra_context=None):
        return HttpResponse(render(request, 'admin/message.html', extra_context))


    def advanced_search(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}

        request.current_app = self.name


        extra_context['start_date_widget'] = DateRangePicker().render('start-date', None, {})
        extra_context['first_posted_widget'] = DateRangePicker().render('first-posted', None, {})
        extra_context['last_update_widget'] = DateRangePicker().render('last-update', None, {})
        extra_context['end_date_widget'] = DateRangePicker().render('end-date', None, {})
        extra_context['media'] = DateRangePicker().media

        extra_context['agent_widget'] = self._build_m2m_autocomplete(Agent, Trial.agent, 'agent', extra_context)
        # extra_context['agent_type_widget'] = self._build_m2m_autocomplete(Agent, Agent.name, 'agent_type', extra_context)
        extra_context['biomarker_widget'] = self._build_m2m_autocomplete(Biomarker, Trial.biomarker, 'biomarker', extra_context)

        extra_context['status_widget'] = forms.CheckboxSelectMultiple({}, Trial.STATUS_CHOICES).render('status', None)
        extra_context['phase_widget'] = forms.CheckboxSelectMultiple({}, Trial.PHASE_CHOICES).render('phase', None)


        context = {
            **self.each_context(request),
            'page_name': 'advanced',
            **(extra_context or {}),
        }
        return HttpResponse(render(request, 'admin/advanced_search.html', context))


    # TODO: move the function to rest api part to get data as JSON use it here to return views
    def ajax_search(self, request, extra_context=None):

        date = ['start_date', 'primary_completion', 'end_date', 'last_update']

        if request.method == 'GET':
            params = dict(request.GET)
            del params['csrfmiddlewaretoken']
            page_num = params.pop('page')[0] if 'page' in params else 1

            filters = {}
            for k,v in params.items():
                if not k.endswith('[]'):
                    v = [v]

                k = k.replace('-','_').replace('[]','')

                if k in date:
                    if v and len(v) > 0:
                        v = [d.strip() for d in v[0].split('-')]
                        v = [datetime.strptime(d, '%m/%d/%Y').strftime('%Y-%m-%d') for d in v]
                        filters[k+'__range'] = v
                else:
                    filters[k+'__in'] = v


            results = Trial.objects.filter(**filters).order_by('-nct_id')

            paginator = Paginator(results, 20)
            page = paginator.get_page(page_num)
            context = {
                **self.each_context(request),
                'page' : page,
                'paginator' : paginator,
                **(extra_context or {}),
            }
            print(page.number)
            return HttpResponse(render(request, 'admin/panels/trial/advanced_search_result.html', context))
        else:
            return HttpResponse(status=400)



    def _build_m2m_autocomplete(self, model, m2m_field, field_name, 
            context, can_add_related=False):
        """
            A function that build autocomplete widget and renders it to place it in the page.

            Parameters
            ================
            + model:        Class of the model for example: models.Agent
            + m2m_field:    A link to ManyToMany relation for the parnet class (Trial.agent)
            + field_name:   A string representing field name
        """
        field = forms.ModelMultipleChoiceField(model.objects.all())
        choices = forms.models.ModelChoiceIterator(field)
        ac = AutocompleteSelectMultiple(m2m_field.field, self, choices=choices)
        w = widgets.RelatedFieldWidgetWrapper(ac, m2m_field.rel, self, can_add_related=can_add_related)
        if 'media' not in context:
            context['media'] = w.media
        else:
            context['media'] += w.media

        return w.render(field_name, [])



class TrialAdmin(SimpleHistoryAdmin):
    filter_horizontal = []

    list_display = ('nct_id', 'agents', 'custom_status', 'custom_phase', 'last_update',)
    sortable_by = ('last_update', 'phase')

    list_filter = (('first_posted', DateRangeFilter),
                    ('end_date', DateRangeFilter),
                    'agent__type',
                    'phase', 
                    'status', 
                    'last_update',)

    search_fields = ('nct_id', 'agent__name', 'location_str', 'title',)

    autocomplete_fields = (
        'agent',
        'condition',
        'biomarker', 
        'sponsor',
        )

    list_per_page = PAGE_ROWS

    ordering = ('-last_update',)

    history_list_display = ['custom_status', 'phase']

    # actions = ('set_status_complete', )
    # date_hierarchy = 'first_posted'

    fieldsets = (

        ('General Info', {
            'fields': ('nct_id', 
                        'status', 
                        'phase', 
                        'agent', 
                        'condition'
                        'title', 
                        'protocol',
                        'repurposed',
                        ),
            }),

        ('Outcomes', {
            'fields': ('primary_outcome',
                        'secondary_outcome',
                        'other_outcome',
                        'treatment_duration',
                        'treatment_weeks',
                        'treatment_days',
                        )
        }),

        ('Criteria', {
            'fields': ('eligibility_criteria',
                        )
        }),

        ('Enrollment', {
            'fields': ('enroll_number',
                        'arms_number',
                        'per_arm',)
        }),


        ('Subject Characteristics', {
            'fields': (
                ('min_age','max_age')
            ),
        }),

        ('Biomarkers', {
            'fields': ('biomarker',
                    ),
        }),

        ('Sponsors', {
            'fields': ('sponsor',
                        'funder_type',
                        ),
        }),

        ('Location', {
            # 'classes' : ('collapse',),
            'fields': ('location',
                        'location_str',
                        'num_sites',
                        ),
        }),

        ('Dates & Duration', {
            # 'classes': ('collapse',),
            'fields': ('first_posted', 
                        ('start_date', 'first_start_date'),
                        ('end_date','first_end_date'), 
                        ('primary_completion', 'first_primary_completion'), 
                        'last_update',
                        'study_duration',
                        'exposure_duration',
                        ),
        }), 

    )

    exclude = (
            'history', 
            'mmse_sent', 
            'amyloid_sent', 
            'condition', 
            'reviewed',
            'moa_list',
            'list_charac',
            'list_biomarkers',
        )

    form = TrialForm
    

    @admin.display(description='Status')
    def custom_status(self, obj):
        if obj.status in ['A', 'E', 'N', 'R']:
            st = 'en'
        elif obj.status == 'C':
            st = 'com'
        elif obj.status in ['S', 'T', 'W']:
            st = 'dis'
        else:
            st = 'unk'

        return mark_safe('<span><div class="status-text status-{}">'.format(st) 
                + obj.get_status_display() + '</div></span>')


    @admin.display(description='Phase')
    def custom_phase(self, obj):
        return obj.get_phase_display()


    @admin.display(description='Agents')
    def agents(self, obj):
        txt = []
        for agent in obj.agent.all():
            if 'placebo' not in agent.name.lower():
                txt.append(agent.name + ' (<span class="agent-type">' + agent.get_type_display() + '</span>)')
            
        return mark_safe(', '.join(txt))



class AgentAdmin(admin.ModelAdmin):

    list_display = ('name', 'type')

    list_filter = ('type',)

    search_fields = ('name', )

    list_per_page = PAGE_ROWS


class BiomarkerAdmin(admin.ModelAdmin):

    list_display = ('name', 'type')

    list_filter = ('type',)

    search_fields = ('name', )

    list_per_page = PAGE_ROWS

    actions = ('set_outcome', 'set_entry', 'duplicate_as_other')
    
    def set_outcome(self, request, queryset):
        count = queryset.update(type='O')
        self.message_user(request, '{} biomarkers have been updated successfully.'.format(count))

    def set_entry(self, request, queryset):
        count = queryset.update(type='E')
        self.message_user(request, '{} biomarkers have been updated successfully.'.format(count))

    def duplicate_as_other(self, request, queryset):
        count = queryset.count()
        for b in queryset:
            b.pk = None
            if b.type == 'E':
                b.type = 'O'
            elif b.type == 'O':
                b.type = 'E'
            b.save()

        self.message_user(request, '{} biomarkers have been duplicated successfully.'.format(count))


class NameAdmin(admin.ModelAdmin):
    search_fields = ('name',)


class SubscriberAdmin(admin.ModelAdmin):
    list_display = ('name', 'email')


class NewsletterAdmin(admin.ModelAdmin):
    list_display = ('capped_text', 'last_edited', 'is_published')

    @admin.display(description='Text')
    def capped_text(self, obj):
        if len(obj.text) > 50:
            return obj.text[:50] + '...'
        else:
            return obj.text


class PublicationAdmin(admin.ModelAdmin):
    list_display = ('title', 'biblo', 'year')

    @admin.display(description='Text')
    def capped_biblo(self, obj):
        if len(obj.biblo) > 50:
            return obj.biblo[:50] + '...'
        else:
            return obj.biblo


class HideAdmin(admin.ModelAdmin):
    search_fields = ('name',)

    def get_model_perms(self, request):
        return {}   # hide it in admin page


class AdvancedSearchAdmin(admin.ModelAdmin):

    form = AdvancedSearchForm

    fields = (
        'agent',
        'biomarker',
        'sponsor',
        )

    autocomplete_fields = (
        'agent',
        'biomarker',
        'sponsor',
        )




my_site = MyAdminSite(name='myadmin')
my_site.site_header = "Tri-AL: Visual Clinical Trials"


my_site.register(Trial, TrialAdmin)
my_site.register(Agent, AgentAdmin)
my_site.register(Biomarker, BiomarkerAdmin)
my_site.register(Subscriber, SubscriberAdmin)
my_site.register(Newsletter, NewsletterAdmin)
my_site.register(Sponsor, HideAdmin)
my_site.register(Condition, HideAdmin)

my_site.register(User, UserAdmin)