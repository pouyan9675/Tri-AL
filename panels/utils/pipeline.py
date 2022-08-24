import pandas as pd
from plotly import plot
from datetime import datetime, date
from difflib import SequenceMatcher
from django.db.models import Exists
import ast
import re
import os

from panels.models import *
from panels.utils.plot.charts import Plotter
from visual import settings


class Pipeline():
    def __init__(self, year=datetime.now().year):
        self.year = year - 1

        self._all_trials = self._get_all_trials()
        self._trials = self._remove_irrelevant(self._all_trials)


    def _postprocess(func):
        def wrapper(*args, **kwargs):
            query = func(*args, **kwargs)
            for t in query:
                if t.phase:
                    t.phase = t.phase[-1]
            return query
        return wrapper


    def _remove_irrelevant(self, query):
        query = query.exclude(status__in=['S','T','C','U','W'])
        return query


    def _get_all_trials(self):
        """
            Applies filters to database to retrieve all related trials 
            to given year pipeline. This is a private function, so stop
            using it outside of the class. Instead call all_trials() to 
            get all trials.

            - Return
            ============================
            + queryset (models.Trial): A queryset of Trials related for 
                                    given year pipeline
        """
        self.last_pipe = pd.read_excel(settings.BASE_DIR + '/data/pipeline/' + str(self.year) + '.xlsx')
        pipe = Trial.objects.filter(nct_id__in=self.last_pipe['NCT #'])                                     \
                            .distinct()
        new = Trial.objects.filter(first_posted__range=[date(self.year,1,4), date(self.year+1,1,4)],
                                    agent__type__in=[Agent.DRUG, Agent.BIOLOGICAL])   \
                            .distinct()

        exclusions = [
            'NCT04926272',
        ]
        for t in new:
            elg = set()
            for a in t.agent.all():
                if a.type == Agent.BIOLOGICAL or a.type == Agent.DRUG:
                    elg.add(a.name.lower())
            if ('placebo' in elg and len(elg) == 1) or len(elg) == 0:
                exclusions.append(t.nct_id)

        new = new.exclude(nct_id__in=exclusions)

        pipeline = (pipe | new).distinct()       # union two querysets

        return pipeline


    @_postprocess
    def all_trials(self):
        """
            This function returns all trials for a pipeline
            with filter on status
        """
        return self._trials


    def all_trials_no_filter(self):
        """
            This function returns all trials for a pipeline
            without applying any filter on status or preprocessing
            on phase field
        """
        return self._all_trials


    def phase_MoA(self, phase_n):
        """
            Return Mechanisms of action of agents in given Phase as a Pie Chart
        """
        phase = self._trials.filter(phase=phase_n)                      \
                            .exclude(moa_class__isnull=True)            \
                            .exclude(moa_class=Trial.STEM_CELL)         \
                            .distinct()
        phase_dmt = phase.filter(moa_class__in=Trial.MOA_DMT).distinct()
        
        return phase, phase_dmt


    @_postprocess
    def all_dmt(self):
        return self._trials.filter(moa_class__in=Trial.MOA_DMT).distinct()


    @_postprocess
    def get_agent_phase(self, phase):
        """
            Filter the pipeline agents based on the Phase
        """
        return self._trials.filter(phase__startswith=phase).exclude(moa_class=Trial.STEM_CELL).distinct()


    @_postprocess
    def get_stem_cells(self):
        """
            Filter the pipeline stem cell therapy trials
        """
        return self._trials.filter(moa_class=Trial.STEM_CELL).distinct()


    @_postprocess
    def get_dmt_phase23(self):
        """
            Get all DMT agents within Phase2 and Phase3
        """
        return self.all_dmt().exclude(phase__startswith='1').distinct()




def export_pipeline(year):
    columns = [
        'nct_id',
        'phase',
        'status',
        'protocol',
        'title',
        'first_posted',
        'start_date',
        'first_start_date',
        'end_date',
        'first_end_date',
        'primary_completion',
        'first_primary_completion',
        'last_update',
        'study_duration',
        'exposure_duration',
        'treatment_duration',
        'treatment_weeks',
        'treatment_days',
        'recruitment_period',
        'enroll_number',
        'arms_number',
        'per_arm',
        'location',
        'num_sites',
        'primary_outcome',
        'secondary_outcome',
        'other_outcome',
        'eligibility_criteria',
        'num_sites',
        'mmse',
        'mmse_sent',
        # 'list_charac',
        'list_biomarkers',
        'amyloid',
        'amyloid_sent',
        'moa_list',
        'moa_class',
        'thera_purpose',
        'figs_cat',
        'repurposed',
    ]

    devices = {
            "NCT04823819",
            "NCT04754152",
            "NCT04908358",
            # "NCT04842734",
            "NCT04913454",
            "NCT04866979",
            "NCT04404153",
            # "NCT04902703",
            "NCT04855643",
            "NCT05032482",
            "NCT05077826",
            "NCT04817891",
            # "NCT04550975",
            "NCT02438202",
            # "NCT04828434",
            # "NCT05122598",
            # "NCT05027789",
            # "NCT04855630",
            # "NCT04555616",
            "NCT04073628",
            # "NCT04948450",
            "NCT05078944",
            # "NCT05007353",
            # "NCT04937452",
            "NCT03880240",
            "NCT03484143",
            "NCT04042922",
            "NCT03328195",
            "NCT04055376",
            "NCT05015478",
            "NCT04574921",
            "NCT05016219",
            "NCT04785053",
            "NCT04783350",
            "NCT03657745",
            "NCT03920826",
            "NCT04913454",
            "NCT04122001",
            "NCT04784416",
    }

    exclusions = {
        "NCT04710550",
        "NCT04710550",
        "NCT04715750",
        "NCT04786223",
        "NCT04831281",
        "NCT04840979",
        "NCT04871074",
        "NCT04926272",
        "NCT04937452",
        "NCT05164536",
        "NCT05077501",
        "NCT05077631",
        "NCT04784416",
        "NCT04754152",      # Device
        "NCT05078944",      # Device
    }

    inclusions = [
            'NCT04251182',
        ]

    dataframe = pd.read_excel(settings.BASE_DIR + '/data/pipeline/' + str(year-1) + '.xlsx')
    pipe = pd.DataFrame(list(Trial.objects.filter(nct_id__in=dataframe['NCT #'])
                                        .exclude(nct_id__in=exclusions)
                                        # .exclude(status__in=['C','T','U','S','W'])
                                        .exclude(moa_class__in=['s','c'])
                                        .distinct()
                                        .values(*columns)))

    dataframe['Start Date (Actual)'] = pd.to_datetime(dataframe['Start Date (Actual)'], unit='s', format='%Y-%m-%d')

    pipe['phase'] = pipe['phase'].apply(lambda x: Trial.get_display(Trial.PHASE_CHOICES, str(x)).replace(' | ', '|'))
    pipe['status'] = pipe['status'].apply(lambda x: Trial.get_display(Trial.STATUS_CHOICES, x))
    pipe = annotate_changes(dataframe.copy(), pipe)

    new = Trial.objects.filter(first_posted__range=[date(year-1,1,4), date(year,1,4)],         # TODO: Changed end date from 1/4 to 1/26
                                agent__type__in=[Agent.DRUG, Agent.BIOLOGICAL])         \
                    .exclude(nct_id__in=exclusions)                                     \
                    .exclude(moa_class__in=['s','c'])                                   \
                    .distinct()  

    additional = Trial.objects.filter(nct_id__in=inclusions).distinct()
    new = new | additional                                                     
                        
    new = pd.DataFrame(list(new.values(*columns)))
    new['phase'] = new['phase'].apply(lambda x: Trial.get_display(Trial.PHASE_CHOICES, str(x)).replace(' | ', '|'))
    new['status'] = new['status'].apply(lambda x: Trial.get_display(Trial.STATUS_CHOICES, x))

    # pipe = pipe.append(new).sort_values('nct_id')
    pipe = pd.concat([pipe,new], sort=False).drop_duplicates(subset='nct_id').sort_values('nct_id')
    pipe.reset_index(drop=True, inplace=True)
    pipe = pipe.sort_values('nct_id')
    pipe = pipe.drop_duplicates()

    pipe['amyloid'] = pipe['amyloid'].apply(lambda x: ', '.join(ast.literal_eval(x)) if x and x != '[]' else '')
    # pipe['repurposed'] = pipe['nct_id'].apply(lambda x: check_repur(x, dataframe.copy().set_index('NCT #', drop=True)))
    pipe['mmse'] = pipe['mmse'].apply(clean_mmse).astype(str)
    pipe['MoA'] = pipe['nct_id'].apply(lambda x: add_moa_category(x, dataframe.copy().set_index('NCT #', drop=True)))
    pipe['MoA CADRO'] = pipe['nct_id'].apply(add_cadro)
    # pipe['moa_class'] = pipe['moa_class'].apply(lambda x: x if x != 's' else 'Stem Cell')
    pipe['Drug'] = pipe['nct_id'].apply(add_drug)
    pipe['Geography'] = pipe['nct_id'].apply(add_geo)
    pipe['Sponsor'] = pipe['nct_id'].apply(add_sponsor)
    pipe['Subject Charac'] = pipe['nct_id'].apply(lambda x: add_subj(x, dataframe.copy().set_index('NCT #', drop=True)))
    pipe['Biomarkers for Outcomes'] = pipe['nct_id'].apply(add_outcome_bio)
    pipe['repurposed'] = pipe['repurposed'].apply(lambda x: 'Yes' if x else 'No')
    pipe['url'] = 'https://clinicaltrials.gov/ct2/show/' + pipe['nct_id']

    pipe.reset_index(drop=True, inplace=True)

    pipe.rename(columns={
        'mmse'  : 'MMSE',
        'nct_id'  : 'NCT #',
        'phase'  : 'Phase',
        'status'  : 'Status',
        'repurposed'  : 'Repurposed',
        'amyloid'   : 'Amyloid PET, or CSF or either as entry criterion (or others)',
        'thera_purpose' : 'Therapeutic Purpose',
        'exposure_duration'  : 'Primary End Date - Start Date',
        'first_posted'  : 'First Posted',
        'start_date'  : 'Start Date',
        'end_date'  : 'End Date',
        'primary_completion'  : 'Primary Completion',
        'last_update'  : 'Last Update',
        'enroll_number'  : 'Enrollment',
        'num_sites'  : '# of Sites',
        'study_duration'  : 'Study Duration',
        'Subject Charac'  : 'Subject Characteristics',
        'treatment_duration'  : 'Treatment Duration',
        'treatment_weeks'   : 'in Weeks',
        'treatment_days'    : 'in Days',
        'arms_number'  : '# of Arms',
        'protocol'  : 'Protocol #',
        'title'  : 'Trial Title',
        'moa_class'  : 'MOA Class (1 Sx-cognition, 2 Sx-behavior, 3 DMT small molecules, 4 DMT Biologics (mabs, vaccines, gene therapy, growth factors, plasma)',
        'MoA CADRO'  : 'CADRO MOA Category (use the red lined ones per Dr.C): A. Amyloid; B. Tau; C. ApoE, Lipids and Lipoprotein Receptors; D. Neurotransmitter Receptors; E. Neurogenesis; F. Inflammation (including Infection/Immunity); G. Oxidative Stress; H. Cell Death (put neuroprotective agents here); I. Proteostasis/Proteinopathies;  J. Metabolism and Bioenergetics; K. Vascular Factors; L. Growth Factors and Hormones; M. Synaptic Plasticity/Neuroprotection; N. Gut-Brain Axis; O. Circadian rhythm; P. Environmental factors; Q. Epigenetic regulators; R. Multi-target; S. Unknown Target; T. Other',
        'location'  : 'Location(1. North America (US & Canada); 2. Non-North America; 3. Both)',
        'Geography'  : 'Geography (1 North America, 2 South America/Mexico, 3 Western Europe/Israel, 4 Eastern Europe/Russia, 5 Asia (not Japan), 6 Japan, 7 South Africa/Australia/ New Zealand)',
    }, inplace=True)

    styled = pipe.style.applymap(color_df)
    # styled.to_excel('~/Desktop/pipeline.xlsx', engine='openpyxl')
    # pipe.to_csv('~/Desktop/pipeline.csv')

    return styled


def check_repur(id_, df):
    pass


def add_moa_category(id_, df):
    # chars = 'abcdefghijklmnopqrst'
    t = Trial.objects.get(nct_id=id_)
    # cat = [chars[c.pk] for c in t.moa_subcat.all()]
    if t.moa_subcat.all().count() == 0:
        if id_ in df.index:
            return str(df.loc[id_]['List MoA'])
        else:
            return ''
    else:
        cat = [c.name for c in t.moa_subcat.all()]
        return '; '.join(cat)


def add_cadro(id_):
    chars = 'abcdefghijklmnopqrst'.upper()
    t = Trial.objects.get(nct_id=id_)
    cadro = [chars[c.pk-1] if c.pk < 20 else c.name for c in t.cadro_moa_cat.all()]
    # cadro = [c.name for c in t.cadro_moa_cat.all()]
    return '; '.join(cadro)


def add_drug(id_):
    t = Trial.objects.get(nct_id=id_)
    # drugs = [a.name for a in t.agent.all() if a.type == Agent.DRUG and 'placebo' not in a.name.lower()]
    drugs = [a.name for a in t.agent.all() if 'placebo' not in a.name.lower()]
    return ' | '.join(drugs)


def add_geo(id_):
    t = Trial.objects.get(nct_id=id_)
    geo = [str(g.pk) for g in t.geography.all()]
    return ', '.join(geo)


def add_outcome_bio(id_):
    t = Trial.objects.get(nct_id=id_)
    bio = {
            "CSF Amyloid"      : '1',
            "CSF tau"          : '2',
            "FDG-PET"          : '3',
            "vMRI"             : '4',
            "Plasma Amyloid"   : '5',
            "Plasma Tau"       : '6',
            "Amyloid PET"      : '7',
            "Tau PET"          : '8',
        }
    biomarkers = [bio[b.name] for b in t.biomarker_outcome.all()]
    return ', '.join(biomarkers)


def add_sponsor(id_):
    t = Trial.objects.get(nct_id=id_)
    spo = [s.name for s in t.sponsor.all()]
    return ' | '.join(spo)


def add_subj(id_, dataframe):
    t = Trial.objects.get(nct_id=id_)
    if t.subject_charac.all().count() == 0:
        return t.list_charac
    else:
        sub = [s.name for s in t.subject_charac.all()]
        return '; '.join(sub)



def clean_mmse(sent):
    mmse = set()
    if sent:
        for s in sent.split(' | '):
            valid = True
            for number in re.findall('[0-9]+', s):
                if not (int(number) < 31 and int(number) > 0):
                    valid = False
                    break
            if valid:
                mmse.add(s)

    return str(' | '.join(mmse))


def annotate_changes(past, new):

    fields = {
        'phase' :               'Phase',
        'status':               'Status',
        'enroll_number':        'Enrollment',
        'arms_number':          '# of Arms',
    }

    date_fields = {
        'end_date':             'Est. End Date (or Actual End Date for Completed trials)',
        'start_date':           'Start Date (Actual)',
        'primary_completion':   'Primary Completion Date (or Actual Primary Completion Date for Completed trials)',
    }

    ids_ = past['NCT #']

    df1 = past.set_index('NCT #', drop=True)
    df2 = new.set_index('nct_id', drop=True)

    for i in ids_:
        if i not in df2.index.values:
            print(i)
            continue

        for k,v in fields.items():
            if df2.loc[i,k] != df1.loc[i,v]:
                df2.loc[i,k] = ' ' + str(df2.loc[i,k])

        for k,v in date_fields.items():
            if df2.loc[i,k] != df1.loc[i,v].date():
                df2.loc[i,k] = ' ' + str(df2.loc[i,k])

    df2['nct_id'] = df2.index

    return df2


def remove_annotation(cell):
    return cell[1:] if cell[0]==' ' else cell


def color_df(cell):
    cell = str(cell)
    if len(cell) > 0 and str(cell)[0]==' ':
        return 'background-color: %s' % 'yellow' 
    else:
        return ''