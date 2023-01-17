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
actions = ('import', 'update', 'manual', 'terminal', 'export')
parser.add_argument('action', help='Actions to perform on database.', choices=actions)
parser.add_argument('--input', '-i', help='Input file or directory.')
parser.add_argument('--output', '-o', help='The name of output file.')
    


def clear_data():
    """
        Clears the data from database
    """
    Trial.objects.all().delete()
    Agent.objects.all().delete()
    Condition.objects.all().delete()
    Biomarker.objects.all().delete()
    Sponsor.objects.all().delete()
    UpdatesLog.objects.all().delete()


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


def update_data(csv_name: str) -> list:
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

                        # TODO: Make it more efficient by having all 
                        # trials as a single dataframe and write all 
                        # at the same time (bulk update)

                        row = pd.DataFrame.from_dict([data])
                        row = processor.build_columns(row)
                        t = processor.data_mapper(row.to_dict(orient='index')[0])
                        trials[data['NCTID']] = t

                    pbar.update(1)

    return trials        




def manual(input_):
    """
        You can add any manual script that you want here to run it through
        the data_manager to apply any changes to the database!
    """
    trials = Trial.objects.values('nct_id', 
                        'condition__name',
                        'agent__name',
                        'title',
                        'brief_summary',
                        'description',
                        'primary_outcome',
                        'secondary_outcome',
                        'other_outcome'
                        )

    df = pd.DataFrame(trials)
    df.drop_duplicates(subset='nct_id', keep='first', inplace=True)
    
    for i in range(0, df.shape[0], 10000):
        df.iloc[i:i+10000].to_csv('export/export-'+str(int(i/10000)+1)+'.csv')



def export_to_csv(file_name='export.csv'):
    """
        Export and save whole database to a CSV file for simple analysis
    """
    trials = Trial.objects.all()
    df = pd.DataFrame(list(trials.values()))
    df.to_csv(file_name)



if __name__ == '__main__':
    args = parser.parse_args()

    if args.action == 'import':
        _import(args.input)
    elif args.action == 'update':
        download_update()
        new_pk, updated_pk = update_data('update.csv')
        notify_update(new_pk, updated_pk, datetime.now())
    elif args.action == 'manual':
        manual(args.input)
    elif args.action == 'terminal':
        embed()
    elif args.action == 'export':
        if args.output:
            export_to_csv(args.output)
        else:
            export_to_csv()
