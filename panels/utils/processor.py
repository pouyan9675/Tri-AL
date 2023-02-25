"""
    This module is responsible to do all calculations & processing
    on downloaded trials to find the other fields and data related
    to Alzheimer's diseases
"""
from posixpath import join

from pandas.core.arrays.sparse import dtype
from panels.utils import downloader, tools, customize
from panels.models import *
from panels.utils.comparator import *
from visual import settings
from ast import literal_eval
import pandas as pd
import numpy as np
import re
import time
import threading
from datetime import datetime

from tqdm import tqdm

# important columns from input (downloaded CSV from ClinicalTrials)
# that are used for output and calculating other fields (MMSE and etc.)
INPUT_COLUMNS = [ "Phases",
                    "Interventions",
                    "NCT Number",
                    "Status",
                    "Outcome Measures",
                    "Sponsor/Collaborators",
                    "Enrollment",
                    "Funded Bys",
                    "Start Date",
                    "Primary Completion Date",
                    "Completion Date",
                    "First Posted",
                    "Last Update Posted",
                    "Locations",
                    "Conditions",
                    ]


DATE_COLUMNS = ['FirstPosted',
                    'StartDate',
                    'CompletionDate',
                    'PrimaryCompletionDate',
                    'LastUpdatePostDate',]


# Threading variables
PARALLEL_DOWNLOAD = 20
s = threading.Semaphore(value=PARALLEL_DOWNLOAD)


def generate_data(csv_name):
    """
        Generates the data that should be inserted into the database
        for further usage. Does the followings procedure:

            1. Load downloaded CSV file
            2. Clean data
            3. Build other fields based on available data

        - Parameters
        ============================
        + csv_name :     String of downloaded csv file name

        - Return
        ============================
        + pd.DataFrame : Generated data from CSV, similar to spreadsheet
    """
    data = pd.read_csv(settings.BASE_DIR + '/data/' + csv_name)
    data = clean_data(data)
    data = download_columns(data)
    data = build_columns(data)
    data = fill_null(data)
    return data


def clean_data(data):
    """
        Removing irrelevant data from the dataframe

        - Parameters
        ============================
        + data:         Pandas dataframe

        - Return
        ============================
        + pd.DataFrame : Cleaned dataframe without irrelevant data
    """

    # required filters and data cleaning can be done here!

    return data
    

def parallel_get_trial(nct_id, trials):
    done = False
    while not done:
        try:
            t = downloader.get_trial(nct_id)
            if t:
                trials.append(t)
                done = True
                s.release()
        except Exception as e:
            print(e)
            print('Failed to retrieve:', nct_id)
            time.sleep(0.5)


def download_columns(data: pd.DataFrame) -> pd.DataFrame:
    trials = []
    threads = [None] * PARALLEL_DOWNLOAD

    for nct_id in tqdm(data['NCT Number']):
        s.acquire()
        t = threading.Thread(target=parallel_get_trial, args=(nct_id, trials))

        assigned = False
        while not assigned:
            for slot in range(PARALLEL_DOWNLOAD):           # move to find an empty slot
                if threads[slot] is None or not threads[slot].is_alive():
                    threads[slot] = t
                    assigned = True
                    break

        t.start()
    
    for th in threads:
        if th:
            th.join()


    additional = pd.DataFrame.from_dict(trials)
    data.set_index('NCT Number', inplace=True)
    data = additional.join(data, on='NCTID', rsuffix='_old')
    return data


def build_columns(data: pd.DataFrame) -> pd.DataFrame:
    """
        Build the columns that are not present in the clinicaltrials.gov database explicitly.
        Performing calculations that need other rows as well (such as mean, std, etc.)
    """

    for func in customize.get_functions():              # applying user defined fucntions
        data[func.column] = data.apply(func, axis=1)

    # selection = data['Date'].apply(lambda x: tools.read_date(x['Completion']) is not None and tools.read_date(x['Start']) is not None) 
    selection = data['Date'].apply(lambda x: x['Completion'] and x['Start']).isna()
    data.loc[selection, 'StudyDuration'] = data.loc[selection, 'Date'].apply(lambda x: (tools.read_date(x['Completion']) - tools.read_date(x['Start'])).days if x['Completion'] and x['Start'] else None)
    valid = data[data['Enrollment'].notna() & data['ArmsNumber'].notna() & data['ArmsNumber'] != 0]
    data['PerArm'] = (valid['Enrollment'].astype(int) / valid['ArmsNumber'].astype(int))
    data['PerArm'] = data['PerArm'].fillna(0)
    data['NumSites'] = data['Locations'].apply(len)
    data['Phase'] = data['Phase'].fillna('N').apply(lambda x: re.sub(r'\s|\||Phase|/', '', x.replace('N/A', 'N')))

    return data


def text_preprocess(text):
    """
        Preprocess and normalize given text

        - Parameters
        ============================
        + text:         Sentence or paragraph that needs to be normalized

        - Return
        ============================
        + string :      Normalized text
    """
    text = str(text)
    text = text.strip()
    text = re.sub(r'\n+\s+\d+\. ', '. ', text)
    text = re.sub(r'\n+\s+- ', '. ', text)    
    
    text = text.replace('\n', ' ')  \
                .replace(' - ', ' ')\
                .replace('..', '.') \
                .replace(':.', '.') \
                .replace(',.', ',')
    
    # preprocess for MMSE
    text = text.replace('−', '-') \
                .replace('greater than', '>') \
                .replace('less than', '<') \
                .replace('≤', '<=') \
                .replace('≥', '>=')
    
    if re.search(r'<=\d+', text):
        text = re.sub('<=', '<= ', text)
        
    if re.search(r'>=\d+', text):
        text = re.sub('>=', '>= ', text)
    
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'[\.:]*\|+', '. ', text)
    return text


def extract_treatment_duration(text, time_unit='d'):
    """
        Finding treatment duration for an span of text in number
        of time unit

        - Parameters
        ============================
        + text:         Span of text mentioning treatment duration
        + time_unit:    The unit of extracted time. (d : days
                                                     w : weeks
                                                     m : months
                                                     y : years
                                                    )

        - Return
        ============================
        + int:          Treatment duration in time units
    """
    if isinstance(text, set):
        text = ' '.join(text)

    text = text.replace(', ', ' ')  \
                .replace('. ', ' ') \
                .replace('-', ' ') \
                .lower()            \
                .strip()

    time = re.findall(r'\d+ months?|\d+ weeks?|\d+ days?|\d+ years?', text)
    duration = 0
    if len(time) == 1:     # skipping time frames with more than one mentioned time
        t = time[0].lower().split()
        duration = int(t[0])
        if t[1][0] == 'w':      # to days
            duration *= 7
        elif t[1][0] == 'm':
            duration *= 31
        elif t[1][0] == 'y':
            duration *= 365

    # convert to asked unit from days
    unit = 1
    if time_unit == 'w':
        unit = 7
    elif time_unit == 'm':
        unit = 31
    elif time_unit == 'y':
        unit = 365

    return duration / unit


def fill_null(df):
    """
        Fill out every where that is null with None value
    """
    return df.where(pd.notnull(df), None)


def data_mapper(row: dict) -> Trial:
    """
        Maps a row to single model object

        - Parameters
        ============================
        + row:         A single row of a dataframe

        - Return
        ============================
        + models.Trial : An object of trial class from models
    """
    t = Trial(
        nct_id = row['NCTID'],
        status = row['Status'][0],
        phase  = row['Phase'],
        design_primary_purpose = Trial.get_char(Trial.PURPOSE_CHOICES, row['StudyDesign']['PrimaryPurpose']),
        funder_type = row['Sponsors']['Lead']['Type'].split('_')[-1][0] if row['Sponsors']['Lead'] and row['Sponsors']['Lead']['Type'] else None,
        protocol = row['Protocol'],
        title = row['Title'],
        first_posted = tools.read_date(row['Date']['FirstPosted']),
        start_date = tools.read_date(row['Date']['Start']),
        first_start_date =  tools.read_date(row['Date']['Start']),
        primary_completion = tools.read_date(row['Date']['PrimaryCompletion']),
        first_primary_completion = tools.read_date(row['Date']['PrimaryCompletion']),
        end_date =  tools.read_date(row['Date']['Completion']),
        first_end_date = tools.read_date(row['Date']['Completion']),
        last_update = tools.read_date(row['Date']['LastUpdate']),
        study_duration = row['StudyDuration'],
        enroll_number = row['Enrollment'],
        arms_number = row['ArmsNumber'],
        per_arm = row['PerArm'],
        primary_outcome = row['Outcome']['Primary'],
        secondary_outcome = row['Outcome']['Secondary'],
        other_outcome = row['Outcome']['Other'],
        eligibility_criteria = row['Criteria'],
        num_sites = len(row['Locations']),
        brief_summary = row[ 'Summary']['Brief'],
        description = row['Summary']['Detailed'],
        location_str = row['LocationsString'],
        min_age = re.search(r'\d+', row['Age']['Min']).group() if row['Age']['Min'] and re.search(r'\d+', row['Age']['Min']) else None,
        max_age = re.search(r'\d+', row['Age']['Max']).group() if row['Age']['Max'] and re.search(r'\d+', row['Age']['Max']) else None,
    )

    if len(row['Countries']) == 1 and 'United States' in row['Countries']:
        t.location = Trial.US
    elif len(row['Countries']) > 1 and 'United States' in row['Countries']:
        t.location = Trial.BOTH
    else:
        t.location = Trial.NONUS

    t.save()

    for agent in row['Agents']:
        if agent['Name'] and agent['Type']:
            try:
                ag = Agent.objects.get(name=agent['Name'], type=Agent.get_type_choice(agent['Type']))
            except Agent.DoesNotExist:
                ag = Agent(name=agent['Name'], type=Agent.get_type_choice(agent['Type']))
                ag.save()
            t.agent.add(ag)     


    for c in row['Conditions']:
        try:
            c = Condition.objects.get(name=c)
            t.condition.add(c)
        except Condition.DoesNotExist:
            obj = Condition(name=c)
            obj.save()
            t.condition.add(obj)
    
    for c in row['Countries']:
        try:
            country = Country.objects.get(name=c)
        except Country.DoesNotExist:
            country = Country(name=c)
            country.save()
        t.countries.add(country)

    for s in row['Sponsors']['All']:
        try:
            sponsor = Sponsor.objects.get(name=s['Name'])
        except Sponsor.DoesNotExist:
            sponsor = Sponsor(name=s['Name'])
            sponsor.save()
        t.sponsor.add(sponsor)

    return t


def data_updater(row: dict) -> Trial:
    """
        Updating existing data

        - Parameters
        ============================
        + row:         A single row of a dataframe

        - Return
        ============================
        + models.Trial : An object of trial class from models
    """

    comp = TrialComparator()
    t = comp.update_database(row)

    t.save()

    return t


def build_objects(df: pd.DataFrame) -> tuple[list, list]:
    """
        Build a objects and insert them into the database if they are not exist
        and update the existing ones

        - Parameters
        ============================
        + df:         A dataframe that willing to build objects from

        - Return
        ============================
        + list : A list of primary keys of objects that have been created or updated
    """
    updated_pk = []
    new_pk = []

    exists = df['NCTID'].apply(lambda x: Trial.objects.filter(nct_id=x).exists())

    objs = df[~exists].apply(data_mapper, axis=1)       # build not exisiting ones
    if len(objs) > 0:
        for o in objs:
            new_pk.append(o.pk)

    objs = df[exists].apply(data_updater, axis=1)       # updating exsiting ones
    if len(objs) > 0:
        for o in objs:
            updated_pk.append(o.pk)

    return new_pk, updated_pk

    
    


    