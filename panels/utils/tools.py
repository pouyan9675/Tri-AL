import re
import pandas as pd
from panels.models import *
from datetime import datetime


def read_date(date_str: str) -> datetime:
    """
        Converts date in string format to datetime object in order to use it or
        insert it into the database.
    """
    if not date_str:
        return None

    if ',' in date_str:
        date_format = '%B %d, %Y'
    else:
        date_format = '%B %Y'
    
    return datetime.strptime(date_str, date_format)


def trial_to_dataframe(trial: dict) -> pd.DataFrame:
    """
        Transform a single trials as dictionary to a single row dataframe
        to pass it to the processor module. 
    """
    pass


def create_object(data: dict) -> Trial:
    """
        Returns an instance of Trial class using the parsed data from the 
        XML file. To use this function there is no need to call parse function
        since it will be called in the constructor.
    """
    t = Trial()

    if len(data['Countries']) == 1 and 'United States' in data['Countries']:
        t.location = Trial.US
    elif len(data['Countries']) > 1 and 'United States' in data['Countries']:
        t.location = Trial.BOTH
    else:
        t.location = Trial.NONUS

    t.save()

    for agent in data['Agents']:
        try:
            ag = Agent.objects.get(name=agent['Name'], type=Agent.get_type_choice(agent['Type']))
        except Agent.DoesNotExist:
            ag = Agent(name=agent['Name'], type=Agent.get_type_choice(agent['Type']))
            ag.save()
        t.agent.add(ag) 

    for c in data['Countries']:
        try:
            country = Country.objects.get(name=c)
        except Country.DoesNotExist:
            country = Country(name=c)
            country.save()
        t.countries.add(country)

    for s in data['Sponsors']['All']:
        try:
            sponsor = Sponsor.objects.get(name=s['Name'])
        except Sponsor.DoesNotExist:
            sponsor = Sponsor(name=s['Name'])
            sponsor.save()
        t.sponsor.add(sponsor)

    
    return t