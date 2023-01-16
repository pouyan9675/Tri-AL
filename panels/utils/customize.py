from panels.utils.decorators import column
from django.db import models


# from nltk.tokenize import sent_tokenize

class Functions:
    """
        A class to define user to define extendable modules.
    """

    # @column('mmse')
    # def extract_mmse(trial: dict) -> str:
    #     # preprocessing eligibility criteria
    #     criteria = trial['criteria'].replace('−', '-') \
    #             .replace('greater than', '>') \
    #             .replace('less than', '<') \
    #             .replace('≤', '<=') \
    #             .replace('≥', '>=')
        
    #     # finding target sentence
    #     for sent in sent_tokenize(criteria):
    #         if 'mmse' in sent.lower() or    \
    #             'mini-mental state examination' in sent.lower():
    #             sentence = sent
        
    #     # extract example patterns using regular expression
    #     results = []
    #     results.extend([re.sub(r'\s?to\s?', '-', r) for r in re.findall(r'\d+\s?to\s?\d+', text)])
    #     results.extend([r.replace(' ', '') for r in re.findall(r'[<>]\s?\d+', text)])
    #     results.extend([r.replace(' ', '') for r in re.findall(r'>=\s?\d+', text)])
    #     results.extend([r.replace(' and ', '-') for r in re.findall(r'\d+ and \d+', text)])
        
    #     return ' | '.join(results)

    
    # @column('csf')
    # def age_extractor(trial: dict) -> bool:
    #     return 'csf' in trial['criteria'].lower()



class Database:
    columns = {
        # 'mmse' : models.CharField(max_length=50, null=True),
        # 'csf' : models.BooleanField(default=False),
    }




def get_functions() -> list:
    """
        Returns a list of user-defined cutomized functions
    """
    attrs = [f for f in dir(Functions) if callable(getattr(Functions, f)) and not f.startswith('__')]
    return [getattr(Functions, f) for f in attrs]
