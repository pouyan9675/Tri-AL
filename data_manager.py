#!/usr/bin/env python
from itertools import count
import os
import re
from sqlalchemy import column
from tqdm import tqdm
import django
from django.forms.models import model_to_dict
from django.db.models import Count
import argparse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "visual.settings")
django.setup()

import pandas as pd
import numpy as np
from IPython import embed
from visual import settings
from datetime import datetime, date
from panels.models import *
from panels.utils.parser import XMLParser
from panels.utils import downloader, processor, tools
from panels.utils.pipeline import export_pipeline
from panels.utils.notification.notification import notify_update


parser = argparse.ArgumentParser(description='Process and manages data into the database for further use.')
actions = ('cleanfill', 'removejunk', 'import', 'update', 'manual', 'terminal', 'pipeline', 'export')
parser.add_argument('action', help='Actions to perform on database.', choices=actions)
parser.add_argument('--input', '-i', help='Input file or directory.')


def fill_data():
    """
        Downloads all data from the http://clinicaltrials.gov/ and 
        process them to save in database.

        - Return
        ============================
        + list : A list of primary keys of the objects that have inserted or updated
    """
    downloader.download_trials(f_name='alz-data')       # get from server
    data = processor.generate_data('alz-data.csv')      # building dataframe from downloaded file
    pks = processor.build_objects(data)                # builds and insert data and return generated data
    


def clear_data():
    """
        Clears the data from database
    """
    Trial.objects.all().delete()


def download_update(f_name='update'):
    """
        Downloads the latest updates from the last updated trial and now
    """
    today = datetime.today().strftime('%m/%d/%Y')
    if Trial.objects.all().count() > 0:
        last_update = Trial.objects.order_by('-last_update')[0].last_update
        last_update = last_update.strftime('%m/%d/%Y')
    else:
        last_update = None

    downloader.download_trials(start_date=last_update, 
                                end_date=today, 
                                f_name=f_name)        


def update_data(csv_name):
    """
        Updates the databaset using given csv file

        - Parameters
        ============================
        + csv_name :    String of downloaded csv file name (including .csv) 

        - Return
        ============================
        + list : A list of primary keys of updated or created trials in the database
    """
    if len(open(settings.BASE_DIR+'/data/'+csv_name, 'r').readlines()) == 1:       # no update posted
        return [], []

    data = processor.generate_data(csv_name)
    new_pk, updated_pk = processor.build_objects(data)
    

    counts = Trial.objects.filter(pk__in=new_pk+updated_pk).values('last_update')   \
        .order_by('last_update')                                                     \
        .annotate(num=Count('last_update'))
    
    for c in counts:
        log = UpdatesLog(udpate_date=c['last_update'], update_counts=c['num'])
        log.save()

    return new_pk, updated_pk


def remove_junk():
    Trial.objects.filter(status='Completed').delete()
    Trial.objects.filter(status='Terminated').delete()
    Trial.objects.filter(status='Suspended').delete()
    Trial.objects.filter(status='Unknown status').delete()
    Trial.objects.filter(status='Withdrawn').delete()


def _import(input_dir: str) -> dict:
    """
        Import XML trials downloaded from ClinicalTrials.gov and builds a
        list of structured data.
    """
    total = 0
    for root, dirs, files in os.walk(input_dir):
        for file in files:
            if file.split('.')[-1] == 'xml':
                total += 1

    existing = set([t[0] for t in Trial.objects.values_list('nct_id')])
    trials = {}
    with tqdm(total=total) as pbar:
        for root, dirs, files in os.walk(input_dir):
            for file in files:
                if file.split('.')[-1] == 'xml':
                    if file.split('.')[0] in existing:
                        continue
                    with open(os.path.join(root, file)) as xml:
                        xml_parser = XMLParser(xml.read())
                        data = xml_parser.data
                        # df = tools.trial_to_dataframe(data)
                        # data = processor.build_columns(data)
                        # processor.build_objects(data)
                        # TODO: Make it more efficient by having all trials as a single dataframe and write all at the same time (bulk update)
                        processor.data_mapper()
                        tools.create_object(data)
                    pbar.update(1)

    return trials        


def clear_fill():
    clear_data()
    fill_data()


def make_pipeline():
    styled = export_pipeline(2022)
    styled.to_excel('pipe.xlsx')


def manual(input_):
    # from lxml import etree as etree_lxml
    # total = 0
    # for root, dirs, files in os.walk(input_):
    #     for file in files:
    #         if file.split('.')[-1] == 'xml':
    #             total += 1
    
    # records = []
    # with tqdm(total=total) as pbar:
    #     for root, dirs, files in os.walk(input_):
    #         for file in files:
    #             if file.split('.')[-1] == 'xml':
    #                 with open(os.path.join(root, file), 'rb') as xml:
    #                     xml_as_bytes = xml.read()
    #                     tree = etree_lxml.fromstring(xml_as_bytes)
    #                     records.append({
    #                         'nct_id' : tree.find('.//nct_id').text,
    #                         'min_age' : tree.find('.//minimum_age').text if tree.find('.//minimum_age') is not None else None,
    #                         'max_age' : tree.find('.//maximum_age').text if tree.find('.//maximum_age') is not None else None,
    #                     })
    #                     # t = Trial.objects.get(nct_id=tree.find('.//nct_id').text)
    #                     # for condition in [c.text for c in tree.findall('.//condition', {})]:
    #                     #     try:
    #                     #         cond = Condition.objects.get(name=condition)
    #                     #     except Condition.DoesNotExist:
    #                     #         cond = Condition(name=condition)
    #                     #         cond.save()
    #                     #     t.condition.add(cond) 

    #                 pbar.update(1)

    # df = pd.DataFrame.from_dict(records)
    # df.to_csv('data/ages.csv', index=False)

    ### Cache count of countries
    # trials = Trial.objects.all().values('nct_id', 'countries__name')
    # df = pd.DataFrame(trials)
    # df['countries__name'].value_counts().to_csv('data/cache/countries.csv', header=['Count'])

    trials = Trial.objects.values('nct_id', 
                        'condition__name',
                        'agent__name',
                        'title',
                        'brief_summary',
                        'description',
                        # 'arms',
                        'primary_outcome',
                        'secondary_outcome',
                        'other_outcome'
                        )

    df = pd.DataFrame(trials)
    df.drop_duplicates(subset='nct_id', keep='first', inplace=True)
    
    for i in range(0, df.shape[0], 10000):
        df.iloc[i:i+10000].to_csv('export/export-'+str(int(i/10000)+1)+'.csv')



def export_to_pandas():
    trials = Trial.objects.all()
    df = pd.DataFrame(list(trials.values()))
    df.to_csv('export.csv')


if __name__ == '__main__':
    args = parser.parse_args()

    if args.action == 'cleanfill':
        clear_fill()
    elif args.action == 'removejunk':
        remove_junk()
    elif args.action == 'import':
        _import(args.input)
    elif args.action == 'update':
        # download_update()
        new_pk, updated_pk = update_data('update.csv')
        notify_update(new_pk, updated_pk, datetime.now())
    elif args.action == 'manual':
        manual(args.input)
    elif args.action == 'terminal':
        embed()
    elif args.action == 'pipeline':
        make_pipeline()
    elif args.action == 'export':
        export_to_pandas()
