import argparse
import requests
from datetime import datetime
from pytrials.client import ClinicalTrials
import pandas as pd
import json
from visual import settings
from panels.utils.parser import FullStudyParser


# Defining constants in our code
BASE_URL = 'https://clinicaltrials.gov/ct2/results/download_fields?down_count=10000&down_flds=all&down_fmt=csv&flds=a&flds=b&flds=y'
START_KEY = 'lupd_s'             # First Posted Starting Date Key
END_KEY = 'lupd_e'               # First Posted Ending Date Key
SLASH_CODE = '%2F'          # The encoded characters for backslash (\) in url


def validate_date(date):
    """
        Checks if a string is valid date format

        - Parameters
        ============================
        + date:        URL of the file that should be downloaded

        - Return
        ============================
        + datime.datetime: Returns parsed object if the format is correct (raises an exception if not)
    """
    try:
        datetime.strptime(date, "%m/%d/%Y")
        return date
    except ValueError:
        msg = "Not a valid date: '{0}'.".format(date)
        raise argparse.ArgumentTypeError(msg)


def encode_url(url):
    """
        Encode characters of a URL to a format that can be transmitted over web

        - Parameters
        ============================
        + url:        Url that is goging to be encoded

        - Return
        ============================
        + string: Encoded url
    """
    return url.replace('/', SLASH_CODE)


def download_file(url, save_name='SearchResults'):
    """
        Downloads file from given url and save it on drive
        
        - Parameters
        ============================
        + url:         URL of the file that should be downloaded
        + save_name:   Name of the file to save after downloading 
        
    """
    r = requests.get(url, allow_redirects=True)
    open(settings.BASE_DIR+'/data/'+save_name+'.csv', 'wb').write(r.content)


def get_trial(nct_id, columns=None):
    """
        Download a trials using pytrials API

        - Parameters
        ============================
        + nct_ids:        Trials nct_id
        + columns:        Keys of column that need to retrieve

        - Return
        ============================
        + dict: Downloaded columns as a dictionary
    """
    if not columns:
        columns = [
            "NCTId", 
            "OfficialTitle",
            "Phase",
            "OverallStatus",
            "DesignPrimaryPurpose",
            "EligibilityCriteria",
            "LeadSponsorClass",
            "OrgStudyId", 
            "PrimaryOutcomeMeasure", 
            "PrimaryOutcomeTimeFrame", 
            "PrimaryOutcomeDescription",
            "SecondaryOutcomeMeasure",
            "SecondaryOutcomeTimeFrame",
            "SecondaryOutcomeDescription",
            "OtherOutcomeMeasure",
            "OtherOutcomeTimeFrame",
            "OtherOutcomeDescription",
            "EnrollmentCount",
            "ArmGroupDescription",
            "ArmGroupInterventionName",
            "ArmGroupLabel",
            "ArmGroupType",
            "Condition",
            "CompletionDate",
            "PrimaryCompletionDate",
            "StartDate",
            "StudyFirstPostDate",
            "LastUpdatePostDate",
            "MaximumAge",
            "MinimumAge",
            "LocationCountry",            
        ]


    r = requests.get('https://clinicaltrials.gov/api/query/full_studies?expr={}&max_rnk=1&fmt=xml'
            .format(nct_id))

    _parser = FullStudyParser(r.content)
    data = _parser.data

    return data


def download_trials(start_date=None, end_date=None, f_name=None):
    """
        Download all trials that are updated in the given period 

            - Parameters
            ============================
            + start_date:     String of start date of period in format MM/DD/YYYY
            + end_date:       String of end date of period in format MM/DD/YYYY
            + f_name:         Name of file to save the result into without .csv postfix
    """
    url = BASE_URL
    file_name = ''

    if start_date:
        file_name = start_date + '-'
        start_date = start_date
        url = url + encode_url('&' + START_KEY + '=' + start_date)
    else:
        file_name = 'NODATE-'


    if end_date:
        file_name = file_name + end_date
        url = url + encode_url('&' + END_KEY + '=' + end_date)
    else:
        file_name = 'NODATE'

    file_name = file_name.replace('/', '')
    if f_name:
        file_name = f_name

    download_file(url, file_name)


def download_single_trial(nct_id):
    TRIAL_URL = 'https://clinicaltrials.gov/ct2/results/download_fields?down_count=10000&down_flds=all&down_fmt=csv&term=' + nct_id + '&flds=a&flds=b&flds=y'