from imp import cache_from_source
from os import path
from visual import settings
from panels.models import *
import numpy as np
import pandas as pd
import plotly
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from collections import defaultdict
from pycountry import countries
from datetime import timedelta, datetime
import re
import pickle
import random


class Plotter:

    def __init__(self, primary_color='#0d6efd'):
        self.primary_color = primary_color
        
        # self.domain = Trial.objects.filter(condition__name='Healthy')
        self.domain = Trial.objects.all()


    def build_map(self, cache=True):
        cache_file = path.join(settings.BASE_DIR, 'data/cache/plot/map.pkl')
        if path.exists(cache_file) and cache:
            last_modified = datetime.fromtimestamp(path.getmtime(cache_file))
            if last_modified.date() < Trial.objects.last().last_update:   # the cache file is outdated
                map_div, stat_countries, top_countries_div = self.build_map(cache=False)
            else:
                with open(cache_file, 'rb') as handle:
                    map_div, stat_countries, top_countries_div = pickle.load(handle)
        else:
            studies = pd.DataFrame(self.domain.values('countries__name', 'countries__alpha3')).value_counts()
            alpha3 = set()
            df = []
            for k, v in studies.items():
                if k[0] and k[1]:
                    alpha3.add(k[1])
                    df.append({'country': k[0], 'studies': v, 'iso_alpha': k[1]})

            stat_countries = len(df)

            for c in countries:             # fill missing countires to make map beautiful
                if c.alpha_3 == 'ATA':
                    continue
                if c.alpha_3 not in alpha3:
                    df.append({'country': c.name, 'studies': 0, 'iso_alpha': c.alpha_3})
                    
            df = pd.DataFrame(df)

            map = px.choropleth(df, locations='iso_alpha',
                        color='studies',
                        hover_name='country',
                        color_continuous_scale=[(0,'#ececec'), (0.15, "#63a2ff"), (1, self.primary_color)])

            map.update_traces(marker_line_color='white',
                                marker_line_width=0.5,)
            map.update_geos(fitbounds="locations", visible=False)

            map.update_layout(coloraxis_showscale=False, 
                            margin={"r":0,"t":0,"l":0,"b":0},
                            font_family="'Nunito', sans-serif",
                            geo=dict(
                                showframe=False,)
            )
            map_div = plotly.offline.plot(map, include_plotlyjs=False, output_type='div')

            df.sort_values('studies', inplace=True)
            top = go.Figure()
            top.add_trace(go.Bar(
                x=df['studies'][-15:],
                y=df['country'][-15:],
                marker_color='rgba(13, 109, 253, 0.3)',
                marker_line_color='rgba(13, 109, 253, 0.8)',
                marker_line_width=1,
                orientation='h',
            ))

            top.update_layout(coloraxis_showscale=False, 
                            # template='simple_white',
                            margin={"r":0,"t":58,"l":0,"b":0},
                            font_family="'Nunito', sans-serif",
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            xaxis={'title':'Count',},)
            top.update_xaxes(showgrid=False)
            top.update_yaxes(tickangle = 45, showgrid=False)
            top_countries_div = plotly.offline.plot(top, include_plotlyjs=False, output_type='div')

            with open(cache_file, 'wb') as handle:
                pickle.dump((map_div, stat_countries, top_countries_div), handle, protocol=pickle.HIGHEST_PROTOCOL)

        return map_div, stat_countries, top_countries_div


    def build_phases(self, cache=True):
        cache_file = path.join(settings.BASE_DIR, 'data/cache/plot/phase.pkl')
        if path.exists(cache_file) and cache:
            last_modified = datetime.fromtimestamp(path.getmtime(cache_file))
            if last_modified.date() < Trial.objects.last().last_update:   # the cache file is outdated
                phase_div = self.build_phases(cache=False)
            else:
                with open(cache_file, 'rb') as handle:
                    phase_div = pickle.load(handle)
        else:
            phases = self.domain.values_list('phase')

            phase_count = defaultdict(int)
            for p in phases:
                p = p[0]
                if p == '' or len(p) > 2:
                    phase_count['N'] += 1
                else:
                    phase_count[p] += 1

            df = pd.DataFrame([(k,v) for k,v in phase_count.items()], columns=['phase', 'count'])
            df = df[(df.phase != '') & (df.phase != 'Not Applicable')]
            df['phase'] = df['phase'].apply(lambda x: ''.join([b for a,b in Trial.PHASE_CHOICES if x==a]).replace(' | ','<br>'))
            df.sort_values(by=['phase'], inplace=True)

            phase = go.Figure()
            phase.add_trace(go.Bar(
                x=df['phase'],
                y=df['count'],
                marker_color='rgba(13, 109, 253, 0.2)',
                marker_line_color='rgba(13, 109, 253, 0.8)',
                marker_line_width=1,
            ))

            phase.update_layout(coloraxis_showscale=False, 
                            margin={"r":0,"t":24,"l":0,"b":0},
                            font_family="'Nunito', sans-serif",
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            xaxis={'title':'Count'},
                            yaxis={'showgrid':True,})
            phase.update_xaxes(showgrid=True)
            phase.update_yaxes(showgrid=True)
            phase_div = plotly.offline.plot(phase, include_plotlyjs=False, output_type='div')

            with open(cache_file, 'wb') as handle:
                pickle.dump(phase_div, handle, protocol=pickle.HIGHEST_PROTOCOL)

        return phase_div


    def build_status(self, cache=True):
        cache_file = path.join(settings.BASE_DIR, 'data/cache/plot/status.pkl')
        if path.exists(cache_file) and cache:
            last_modified = datetime.fromtimestamp(path.getmtime(cache_file))
            if last_modified.date() < Trial.objects.last().last_update:   # the cache file is outdated
                status_div = self.build_status(cache=False)
            else:
                with open(cache_file, 'rb') as handle:
                    status_div = pickle.load(handle)
        else:
            status = self.domain.values_list('status')

            status_count = defaultdict(int)
            for s in status:
                s = s[0]
                status_count[s] += 1

            df = pd.DataFrame([(k,v) for k,v in status_count.items()], columns=['Status', 'Count'])
            df['Status'] = df['Status'].apply(lambda x: ''.join([b for a,b in Trial.STATUS_CHOICES if x==a]))

            pie = px.pie(df, names='Status', values='Count', color_discrete_sequence=[
                    "#031633", "#052C65", "#084298", "#0A58CA", "#0D6EFD", "#3586FD", "#5E9EFE", "#86B7FE", "#AECFFE",
                    ][::-1],)
            pie.update_layout(coloraxis_showscale=False, 
                            margin={"r":24,"t":24,"l":24,"b":24},
                            font_family="'Nunito', sans-serif",)
            pie.update_traces(textposition='inside', textinfo='percent+label')
            pie.update(layout_showlegend=False)
            status_div = plotly.offline.plot(pie, include_plotlyjs=False, output_type='div')

            with open(cache_file, 'wb') as handle:
                pickle.dump(status_div, handle, protocol=pickle.HIGHEST_PROTOCOL)


        return status_div

    
    def build_top_conditions(self, cache=True):
        cache_file = path.join(settings.BASE_DIR, 'data/cache/plot/frequent_conditions.pkl')
        if path.exists(cache_file) and cache:
            last_modified = datetime.fromtimestamp(path.getmtime(cache_file))
            if last_modified.date() < Trial.objects.last().last_update:   # the cache file is outdated
                frequent_div = self.build_top_conditions(cache=False)
            else:
                with open(cache_file, 'rb') as handle:
                    frequent_div = pickle.load(handle)
        else:
            conditions = Condition.objects.values_list('name', flat=True).distinct()
            conditions = pd.Series(conditions)
            conditions = conditions.value_counts()
            frequent = conditions.iloc[:20]
            top = go.Figure()
            top.add_trace(go.Bar(
                y=frequent.index[::-1],
                x=frequent.values[::-1],
                marker_color='rgba(13, 109, 253, 0.3)',
                marker_line_color='rgba(13, 109, 253, 0.8)',
                marker_line_width=1,
                orientation='h',
            ))
            top.update_layout(coloraxis_showscale=False, 
                            # template='simple_white',
                            margin={"r":0,"t":58,"l":0,"b":0},
                            font_family="'Nunito', sans-serif",
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            xaxis={'title':'Count',},)
            top.update_xaxes(showgrid=False)
            top.update_yaxes(tickangle = 45, showgrid=False)
            frequent_div = plotly.offline.plot(top, include_plotlyjs=False, output_type='div')

            with open(cache_file, 'wb') as handle:
                    pickle.dump(frequent_div, handle, protocol=pickle.HIGHEST_PROTOCOL)

        return frequent_div


    def build_update_chart(self, now):
        start_date = now - timedelta(days=30)
        df_trials = pd.DataFrame.from_records(self.domain.filter(last_update__gt=start_date).values('last_update'))
        if len(df_trials) > 0:
            df_trials = df_trials['last_update'].value_counts()
        else:
            df_trials = pd.Series()

        # Adding days without value with value 0
        tmp_date = start_date
        while tmp_date < now:
            found = False
            for d in df_trials.index:
                if d == tmp_date.date():
                    found = True
            if not found:
                # df_trials.at[tmp_date.date()] = 0
                df_trials.at[tmp_date.date()] = np.random.randint(5, 30)       # for demo only
            tmp_date = tmp_date + timedelta(days=1)
        
        df_trials = pd.DataFrame({'date': df_trials.index, 'count': df_trials})
        df_trials.sort_values('date', inplace=True)
        df_trials['date'] = df_trials['date'].apply(lambda x: x.strftime('%d %b'))
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_trials['date'], 
                                y=df_trials['count'], 
                                fill='tozeroy',
                                line=dict(shape='spline', 
                                color=self.primary_color,
                                width=4,),
                                xperiodalignment="middle",))

        fig.update_layout(coloraxis_showscale=False, 
                        margin={"r":0,"t":0,"l":0,"b":0},
                        font_family="'Nunito', sans-serif",
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        hovermode='x unified',
                        hoverlabel=dict(bgcolor="white",))
        
        fig.update_yaxes(showgrid=True, gridcolor='#f9f9f9', gridwidth=1)
        fig.update_xaxes(showspikes=True, spikecolor="#aaa", tickangle = 40)

        if df_trials['count'].sum() == 0:
            fig.update_yaxes(range=[0, 100])

        recent_div = plotly.offline.plot(fig, include_plotlyjs=False, output_type='div')

        return recent_div



class TableFormatter():
    """
        This class converts the Django QuerySet objects to html tables
    """

    def __init__(self):
        pass


    def to_month_year(self, date):
        if date:
            return date.strftime('%b %Y')
        else:
            return ''

    
    def draw_trial_table(self, queryset):
        """
            Builds the table of Trials with thier information
        """
        trials = []
        for t in queryset:
            trials.append({
                'Drug Name' : ', '.join(set([re.sub(r',?\s*\(?\d+(\.\d+)?\s?([Mm][Gg]|milligrams?).*', '', a.name) for a in t.agent.all() if 'placebo' not in a.name.lower()])),
                'CADRO Mechanism Class' : ', '.join([c.name for c in t.cadro_moa_cat.all()]),
                'Mechanism of Action' : ', '.join([c.name for c in t.moa_subcat.all()]),
                'Therapeutic Purpose' : t.get_moa_class_display() if t.moa_class not in Trial.MOA_DMT else 'DMT',
                'Status' : t.get_status_display() + ' (<a href="/admin/panels/trial/' + str(t.pk) + '/change/">' + t.nct_id + '</a>)',
                'Sponsor' : ', '.join([s.name for s in t.sponsor.all()]),
                'Start Date' : self.to_month_year(t.start_date),
                'Estimated End Date' : self.to_month_year(t.end_date),
            })

        df = pd.DataFrame(trials)
        df.index = df.index + 1
        return df.to_html(escape=False)


    def draw_distribution(self, queryset):
        trials = []
        for t in queryset:
            trials.append({
                'Phase' : t.get_phase_display(),
                'Location' : t.get_location_display(),
            })

        df = pd.DataFrame(trials)
        df = pd.crosstab(df.Location, df.Phase)
        df['Total'] = df.sum(axis=1)
        percent = (df / df.sum(axis=0)) * 100
        percent = percent.round(0).astype(int)
        df = (df.astype(str) + ' (' + percent.astype(str) + '%)').reindex(['US ONLY', 'NON-US ONLY', 'BOTH US & NON-US'])
        return df.to_html()


    def draw_sponsor(self, queryset):
        """
            Although the name is sponsor the related field in the 
            database is calleds funders
        """
        trials = []
        for t in queryset:
            for f in t.funder.all():
                trials.append({
                    'Phase' : t.get_phase_display(),
                    'Sponsor': f.name,
                    'Repurposed' : t.repurposed,
                })

        df = pd.DataFrame(trials)
        replace = {
            'NIH' : 'Academic medical centers/NIH',
            'Academic' : 'Academic medical centers/NIH',
            'Industry' : 'Biopharma industry',
            'Public-Private Partnerships' : 'Public–private partnerships (PPP)',
            'U.S. Fed' : 'U.S. Fed',
            'Other' : 'Others',
        }
        df['Sponsor'] = df['Sponsor'].apply(lambda x: replace[x])

        df_final = pd.crosstab(df.Sponsor, df.Phase)
        df_final['All Phases'] = df_final.sum(axis=1)
        df_final['Repurposed agents'] = pd.crosstab(df.Sponsor, df.Repurposed)[True]

        percent = (df_final / df_final.sum(axis=0)) * 100
        percent = percent.round(0).astype(int)

        df_final = df_final.astype(str) + ' (' + percent.astype(str) + '%)'

        return df_final.to_html()


    def draw_participant(self, queryset):
        pass


    def draw_biomarkers(self, queryset):
        #TODO: Make it calucate real time rather than generating some random numbers
        rand_name = ['CSF amyloid', 'CSF tau', 'FDG-PET', 'vMRI', 'Plasma amyloid', 
                'Plasma Tau', 'Amyloid PET', 'Tau PET']
        trials = []
        for t in queryset:
            # for b in t.biomarker_outcome.all():
            trials.append({
                    'Phase' : t.get_phase_display(),
                    # 'Biomarker': b.name,
                    'Biomarker': random.choice(rand_name),
                    'Type': 'Outcome Measure',
                })
            for b in t.biomarker_entry.all():
                trials.append({
                        'Phase' : t.get_phase_display(),
                        'Biomarker': b.name,
                        # 'Biomarker': random.choice(rand_name),
                        'Type': 'Entry Criterion',
                    })

        df = pd.DataFrame(trials)
        df = pd.crosstab(index=[df['Type'], df['Biomarker']],
            columns=df['Phase'])

        return df.to_html()

    
    def pipeline_summary(self, queryset, year):
        trials = []
        for t in queryset:
            trials.append({
                'Phase' : t.get_phase_display(),
                'Type' : 'New Trials' if t.first_posted.year == year-1 else 'Pipeline ' + str(year-1),
            })

        df = pd.DataFrame(trials)
        df = pd.crosstab(df.Type, df.Phase)
        df['Total'] = df.sum(axis=1)

        return df.to_html()
    

    def agent_summary(self, queryset, year):
        trials = []

        types = [defaultdict(set), defaultdict(set)]    # new, pipeline

        for t in queryset:
            agents = t.agent.all()                                              \
                        .exclude(name__icontains='placebo')                     \
                        .filter(type__in=[Agent.DRUG, Agent.BIOLOGICAL])
        
            for a in agents:
                name = re.sub(r',?\s*\(?\d+(\.\d+)?\s?([Mm][Gg]|milligrams?).*', '', a.name)
                if t.first_posted.year == year-1:
                    types[0][t.get_phase_display()].add(name)
                else:
                    types[1][t.get_phase_display()].add(name)

        for k,v in types[0].items():
            types[0][k] = len(v)
            trials.append({
                'Phase' : k,
                'Agents Count' : len(v),
                'Type' : 'New Trials',
            })

        for k,v in types[1].items():
            types[1][k] = len(v)
            trials.append({
                'Phase' : k,
                'Agents Count' : len(v),
                'Type' : 'Pipeline ' + str(year-1),
            })

        df = pd.DataFrame(trials)

        df = df.groupby(['Type', 'Phase'])['Agents Count'].sum().unstack()
        df = df.assign(Total=df.sum(1)).stack().to_frame('Agents Count')

        # df = df.groupby(['Type', 'Phase'])['Agents Count'].sum().unstack(level=['Type','Phase'])
        # print(df)
        # df = df.assign(Total=df.sum(1)).stack(level='Type')
        # df = df.assign(Total=df.sum(1)).stack(level='Phase').to_frame('Agents Count')

        return df.to_html()


    def status_summary(self, queryset, year):
        trials = []
        for t in queryset:
            trials.append({
                'Status' : t.get_status_display(),
                'Type' : 'New Trials' if t.first_posted.year == year-1  else 'Pipeline '+str(year-1),
            })

        df = pd.DataFrame(trials)
        df = pd.crosstab(df.Type, df.Status)
        df['Total'] = df.sum(axis=1)

        return df.to_html()


def rotate(l, n):
    return l[n:] + l[:n]


def cache_plots():
    """
        This function should be called after updating or importing data
        in order to cache the charts for faster page loading
    """
    p = Plotter()
    _ = p.build_map()
    _ = p.build_status()
    _ = p.build_phases()
    # _ = p.build_update_chart()